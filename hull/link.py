"""Hull's link to Rudder, through Rudder's gRPC API (its bridge, 127.0.0.1:7833).

While running, Hull:
  - serves its stages: Rudder sends batches of videos, each Hull stage decides them in a worker thread;
  - steers, when switched on: one Rudder "app" stage per Hull stage sits in Rudder's pipeline, after the stage named
    in hull.toml. Switched off, Hull takes them out and Rudder filters on its own;
  - always records every video Rudder decides (WatchVideos) and puts on screen (WatchShown), and tells the stages
    what was shown, so the culture graph and the repeats list keep growing even while Hull isn't steering;
  - shows a "Hull" panel in Rudder's popup, saying whether it steers.
It reconnects on its own. On a clean exit it takes its stages back out of Rudder's pipeline, so YouTube works normally
without Hull; if it crashes instead, Rudder hides what Hull would have checked (when_missing = "hide"), as Rudder is
strict, until Hull runs again or `python -m hull leave`.

The desktop app (hull/app.py) runs this on a thread of its own and calls the thread-safe methods at the bottom.
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
    def __init__(self, cfg, store, settings=None):
        self.address, self.store = cfg["rudder"]["address"], store
        self.after, self.when_missing = cfg["pipeline"]["after"], cfg["pipeline"]["when_missing"]
        self.settings = settings  # hull/settings.py: steering and the goal, kept between runs
        self.steering = settings.get("steering", True) if settings else True
        self.stages = {}  # Hull stage id → its instance
        self.kinds = {}  # Hull stage id → (kind, config) from hull.toml
        for s in cfg["stage"]:
            if s["kind"] not in KINDS:
                raise ValueError(f"hull.toml: unknown stage kind {s['kind']!r} (kinds: {', '.join(KINDS)})")
            self.stages[s["id"]] = KINDS[s["kind"]](s["config"], store)
            self.kinds[s["id"]] = (s["kind"], s["config"])
        if settings and settings.get("goal"):
            self._use_goal(settings.get("goal"))
        self.status = {"rudder": False, "firefox": False, "filtering": False, "steering": False, "warming": False, "stages": []}
        self.listeners = []  # called with the status (on Hull's thread) whenever it changes
        self.loop, self.rudder = None, None

    # ---- what the app sees ----
    def _set(self, **changes):
        if all(self.status.get(k) == v for k, v in changes.items()):
            return
        self.status.update(changes)
        for fn in self.listeners:
            fn(dict(self.status))

    def configs(self):
        """the config of each Hull stage's Rudder stage; its version changes with the stage's settings, so Rudder judges
        every video again after an edit or a new goal"""
        out = {}
        for sid, (kind, config) in self.kinds.items():
            st = self.stages[sid]
            goal = {"focus": getattr(st, "focus", None), "block": getattr(st, "block", None)}
            version = hashlib.sha1(json.dumps([kind, config, goal], sort_keys=True).encode()).hexdigest()[:10]
            # remember: false, so Rudder asks again each time YouTube sends a video: Hull's answers change as it learns
            # (a video shown once is a repeat the next time). Hull keeps its own per-video work, so asking again is cheap.
            out[sid] = {"name": APP, "stage": sid, "version": version, "when_missing": self.when_missing, "remember": False}
        return out

    def rudder_stages(self):
        out = []
        for sid, config in self.configs().items():
            s = pb.Stage(id=f"hull-{sid}", kind="app")
            s.config.update(config)
            out.append(s)
        return out

    # ---- running ----
    async def main(self):
        self.loop = asyncio.get_running_loop()
        try:
            await self.warm()
            await self.run()
        finally:
            await self.leave()

    async def warm(self):
        """load stages' models before joining, so Rudder's first batches don't time out"""
        self._set(warming=True)
        for sid, st in self.stages.items():
            if hasattr(st, "warm"):
                log.info("warming up %s", sid)
                try:
                    await asyncio.to_thread(st.warm)
                except Exception as e:  # it hides what it can't answer (strict), so Hull still runs
                    log.warning("couldn't warm up %s: %s", sid, e)
        self._set(warming=False)

    async def run(self):
        """connect, and keep reconnecting"""
        while True:
            try:
                async with grpc.aio.insecure_channel(self.address) as channel:
                    self.rudder = rpc.RudderStub(channel)
                    await self.session(self.rudder)
            except grpc.aio.AioRpcError as e:
                log.warning("Rudder isn't reachable (%s); trying again in 5 s", e.details() or e.code().name)
            finally:
                self.rudder = None
                self._set(rudder=False, firefox=False, steering=False)
            await asyncio.sleep(5)

    async def session(self, rudder):
        tasks = [asyncio.create_task(t) for t in (self.serve(rudder), self.watch(rudder), self.watch_shown(rudder), self.watch_state(rudder))]
        try:
            await self.wait_for_app(rudder)
            await (self.join(rudder) if self.steering else self.leave_pipeline(rudder))
            tasks.append(asyncio.create_task(self.panel(rudder)))
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.result()  # a stream that broke raises here
        finally:
            for t in tasks:
                t.cancel()

    async def wait_for_app(self, rudder):
        for _ in range(50):  # Rudder must know Hull's app is there first, or it hides "app hull isn't running"
            if APP in (await rudder.GetState(pb.Empty())).apps:
                return
            await asyncio.sleep(0.1)

    async def watch_state(self, rudder):
        async for s in rudder.WatchState(pb.Empty()):
            self._set(rudder=True, firefox=s.connected, filtering=s.connected and s.enabled,
                      steering=any(i.startswith("hull-") for i in s.stages), stages=list(s.stages))

    async def join(self, rudder):
        """put Hull's stages into Rudder's pipeline, after self.after (replacing any older Hull stages)"""
        p = await rudder.GetPipeline(pb.Empty())
        keep = [s for s in p.stages if not ours(s)]
        at = next((i + 1 for i, s in enumerate(keep) if s.id == self.after), len(keep))
        p = await rudder.SetPipeline(pb.Pipeline(stages=keep[:at] + self.rudder_stages() + keep[at:]))
        log.info("steering Rudder: %s", " → ".join(s.id for s in p.stages))

    async def leave_pipeline(self, rudder, timeout=None):
        p = await rudder.GetPipeline(pb.Empty(), timeout=timeout)
        keep = [s for s in p.stages if not ours(s)]
        if len(keep) != len(p.stages):
            p = await rudder.SetPipeline(pb.Pipeline(stages=keep), timeout=timeout)  # none left: Rudder's default
            log.info("not steering: %s", " → ".join(s.id for s in p.stages))

    async def leave(self):
        """take Hull's stages and panel back out of Rudder (on exit)"""
        try:
            async with grpc.aio.insecure_channel(self.address) as channel:
                rudder = rpc.RudderStub(channel)
                await self.leave_pipeline(rudder, timeout=5)
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
            await rudder.SetPanel(self.panel_message())
            await asyncio.sleep(5)

    def panel_message(self):
        s = self.store.stats()
        goal = self.settings.get("goal") if self.settings else None
        head = ("Hull is steering Rudder" if self.steering else "Hull is running but not steering: Rudder filters on its own") + \
               (f". Goal: {goal['text']}" if goal and goal.get("text") and self.steering else "")
        return pb.Panel(id=APP, title="Hull", blocks=[
            pb.Block(text=head),
            pb.Block(stats=pb.StatGrid(stats=[
                pb.Stat(label="recorded", value=str(s["videos"])),
                pb.Stat(label="shown", value=str(s["shown"])),
                pb.Stat(label="hull hid", value=str(sum(s["hid_by_stage"].values()))),
            ])),
            pb.Block(bars=pb.BarList(bars=[pb.Bar(label=f"{sid} · {st.describe()} · {s['ms_by_stage'].get(sid, 0):.1f} ms", value=s["hid_by_stage"].get(sid, 0))
                                           for sid, st in self.stages.items()])),
            *[b for st in self.stages.values() if hasattr(st, "panel") for title, bars in st.panel()
              for b in (pb.Block(text=title), pb.Block(bars=pb.BarList(bars=[pb.Bar(label=l, value=v) for l, v in bars])))],
            *([pb.Block(table=pb.Table(columns=["hidden by hull", "why"], rows=[pb.Row(cells=[title, f"{stage}: {why}"]) for title, stage, why in s["recent"]]))]
              if s["recent"] else []),
        ])

    # ---- switches and goals: safe to call from any thread (the app's) ----
    def _soon(self, fn):
        """run fn(rudder) on Hull's thread, if Rudder is there (if not, the next connection applies the settings)"""
        if self.loop and self.rudder:
            async def go(r=self.rudder):
                await fn(r)
            asyncio.run_coroutine_threadsafe(go(), self.loop)

    def set_steering(self, on):
        """join (on) or leave (off) Rudder's pipeline; Hull keeps watching either way"""
        self.steering = on
        if self.settings:
            self.settings.update(steering=on)
        self._soon(lambda r: self.join(r) if on else self.leave_pipeline(r))
        self._soon(lambda r: r.SetPanel(self.panel_message()))

    def set_filtering(self, on):
        """Rudder's own on/off switch"""
        self._soon(lambda r: r.SetEnabled(pb.Enabled(enabled=on)))

    def _use_goal(self, goal):
        for st in self.stages.values():
            if hasattr(st, "set_goal"):
                st.set_goal(goal.get("focus", []), goal.get("block", []))

    def set_goal(self, goal):
        """a new goal: {"text", "focus": [...], "block": [...]}; while steering, Rudder judges again with it"""
        self._use_goal(goal)
        if self.settings:
            self.settings.update(goal=goal)
        if self.steering:
            self._soon(self.join)
        self._soon(lambda r: r.SetPanel(self.panel_message()))
