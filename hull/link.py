"""Hull's link to Rudder, through Rudder's gRPC API (its bridge, 127.0.0.1:7833).

While running, Hull:
  - serves its stages: Rudder sends batches of videos, each Hull stage decides them in a worker thread;
  - sits in Rudder's pipeline: one Rudder "app" stage per Hull stage, placed after the stage named in hull.toml;
  - records every video Rudder decides (WatchVideos) and every one it puts on screen (WatchShown) into the store, and
    tells the stages what was shown;
  - shows a "Hull" panel in Rudder's popup.
It reconnects on its own when the bridge or Firefox isn't there yet. On a clean exit it takes its stages back out of
Rudder's pipeline, so YouTube works normally without Hull; if it crashes instead, Rudder hides what Hull would have
checked (when_missing = "hide"), as Rudder is strict.
"""
import asyncio, hashlib, json, logging, time

import grpc
from google.protobuf.json_format import MessageToDict

from hull.rudder import rudder_pb2 as pb, rudder_pb2_grpc as rpc
from hull.stages import KINDS
from hull.video import Result, Video

APP = "hull"  # the name Hull says hello with; Rudder's app stages point at it
DECISION = {"pass": pb.PASS, "hide": pb.HIDE, "show": pb.SHOW}
log = logging.getLogger("hull")


def ours(stage):
    return stage.kind == "app" and MessageToDict(stage.config).get("name") == APP


class Hull:
    def __init__(self, cfg, store):
        self.address, self.store = cfg["rudder"]["address"], store
        self.after, self.when_missing = cfg["pipeline"]["after"], cfg["pipeline"]["when_missing"]
        self.stages = {}  # Hull stage id → its instance
        self.configs = {}  # Hull stage id → the config of its Rudder stage
        for s in cfg["stage"]:
            if s["kind"] not in KINDS:
                raise ValueError(f"hull.toml: unknown stage kind {s['kind']!r} (kinds: {', '.join(KINDS)})")
            self.stages[s["id"]] = KINDS[s["kind"]](s["config"], store)
            # the version changes with the stage's config, so Rudder judges every video again after an edit
            version = hashlib.sha1(json.dumps([s["kind"], s["config"]], sort_keys=True).encode()).hexdigest()[:10]
            # remember: false, so Rudder asks again each time YouTube sends a video: Hull's answers change as it learns
            # (a video shown once is a repeat the next time). Hull keeps its own per-video work, so asking again is cheap.
            self.configs[s["id"]] = {"name": APP, "stage": s["id"], "version": version, "when_missing": self.when_missing, "remember": False}

    def rudder_stages(self):
        out = []
        for sid, config in self.configs.items():
            s = pb.Stage(id=f"hull-{sid}", kind="app")
            s.config.update(config)
            out.append(s)
        return out

    async def main(self):
        try:
            await self.run()
        finally:
            await self.leave()

    async def run(self):
        """connect, and keep reconnecting"""
        while True:
            try:
                async with grpc.aio.insecure_channel(self.address) as channel:
                    await self.session(rpc.RudderStub(channel))
            except grpc.aio.AioRpcError as e:
                log.warning("Rudder isn't reachable (%s); trying again in 5 s", e.details() or e.code().name)
            await asyncio.sleep(5)

    async def session(self, rudder):
        tasks = [asyncio.create_task(self.serve(rudder)), asyncio.create_task(self.watch(rudder)), asyncio.create_task(self.watch_shown(rudder))]
        try:
            await self.join(rudder)
            tasks.append(asyncio.create_task(self.panel(rudder)))
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.result()  # a stream that broke raises here
        finally:
            for t in tasks:
                t.cancel()

    async def join(self, rudder):
        """put Hull's stages into Rudder's pipeline, after self.after (replacing any older Hull stages)"""
        for _ in range(50):  # Rudder must know Hull's app is there first, or it hides "app hull isn't running"
            if APP in (await rudder.GetState(pb.Empty())).apps:
                break
            await asyncio.sleep(0.1)
        p = await rudder.GetPipeline(pb.Empty())
        keep = [s for s in p.stages if not ours(s)]
        at = next((i + 1 for i, s in enumerate(keep) if s.id == self.after), len(keep))
        p = await rudder.SetPipeline(pb.Pipeline(stages=keep[:at] + self.rudder_stages() + keep[at:]))
        log.info("in Rudder's pipeline: %s", " → ".join(s.id for s in p.stages))

    async def leave(self):
        """take Hull's stages and panel back out of Rudder"""
        try:
            async with grpc.aio.insecure_channel(self.address) as channel:
                rudder = rpc.RudderStub(channel)
                p = await rudder.GetPipeline(pb.Empty(), timeout=5)
                keep = [s for s in p.stages if not ours(s)]
                if len(keep) != len(p.stages):
                    p = await rudder.SetPipeline(pb.Pipeline(stages=keep), timeout=5)  # none left: Rudder's default
                    log.info("left Rudder's pipeline: %s", " → ".join(s.id for s in p.stages))
                await rudder.SetPanel(pb.Panel(id=APP), timeout=5)
        except grpc.aio.AioRpcError as e:
            log.warning("couldn't leave Rudder's pipeline (%s); Rudder hides what Hull's stages would check", e.details() or e.code().name)

    async def serve(self, rudder):
        out = asyncio.Queue()
        out.put_nowait(pb.StageMessage(hello=pb.StageHello(name=APP)))

        async def outgoing():
            while True:
                yield await out.get()

        async for request in rudder.Stage(outgoing()):
            asyncio.create_task(self.answer(request, out))

    async def answer(self, request, out):
        sid = MessageToDict(request.config).get("stage", "")
        videos = [Video.from_pb(v) for v in request.videos]
        t = time.perf_counter()
        try:
            results = await asyncio.to_thread(self.stages[sid].decide, videos)
            if len(results) != len(videos):
                raise ValueError(f"{len(results)} results for {len(videos)} videos")
        except Exception as e:  # strict: a stage that fails hides its batch
            log.exception("stage %s failed", sid)
            results = [Result("hide", f"hull {sid} failed: {e}") for _ in videos]
        ms = (time.perf_counter() - t) * 1000
        out.put_nowait(pb.StageMessage(reply=pb.StageReply(id=request.id, results=[
            pb.StageResult(decision=DECISION[r.decision], why=r.why, fields=r.fields) for r in results])))
        self.store.stage_results(sid, videos, results, ms)

    async def watch(self, rudder):
        async for e in rudder.WatchVideos(pb.Empty()):
            self.store.record(Video.from_pb(e.video), e.outcome.hidden, e.outcome.decided_by, e.outcome.why)

    async def watch_shown(self, rudder):
        async for e in rudder.WatchShown(pb.Empty()):
            ids = list(e.ids)
            self.store.shown(ids, e.at_ms)
            for st in self.stages.values():
                if hasattr(st, "shown"):
                    await asyncio.to_thread(st.shown, ids)

    async def panel(self, rudder):
        """Hull's panel in Rudder's popup, redrawn every 5 s"""
        while True:
            s = self.store.stats()
            await rudder.SetPanel(pb.Panel(id=APP, title="Hull", blocks=[
                pb.Block(stats=pb.StatGrid(stats=[
                    pb.Stat(label="recorded", value=str(s["videos"])),
                    pb.Stat(label="thumbnails", value=str(s["thumbnails"])),
                    pb.Stat(label="hull hid", value=str(sum(s["hid_by_stage"].values()))),
                ])),
                pb.Block(bars=pb.BarList(bars=[pb.Bar(label=f"{sid} · {st.describe()} · {s['ms_by_stage'].get(sid, 0):.1f} ms", value=s["hid_by_stage"].get(sid, 0))
                                               for sid, st in self.stages.items()])),
                *([pb.Block(table=pb.Table(columns=["hidden by hull", "why"], rows=[pb.Row(cells=[title, f"{stage}: {why}"]) for title, stage, why in s["recent"]]))]
                  if s["recent"] else []),
            ]))
            await asyncio.sleep(5)
