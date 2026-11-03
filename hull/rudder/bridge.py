# Copied from the Rudder repo by scripts/sync_proto.py: don't edit here.
# Rudder's local gRPC server. Firefox (extension/api.js) connects here over a WebSocket on 127.0.0.1:7834; your apps
# connect over gRPC on 127.0.0.1:7833 (rudder.proto). Apps run "app" stages of Rudder's filtering pipeline, change the
# pipeline, read every video Rudder sees, test, time, and show panels in the popup.
# Usage: pip install -r requirements.txt, then python bridge.py
import asyncio, collections, itertools, json, os, time
import grpc, websockets
from google.protobuf.json_format import MessageToDict, ParseDict
from grpc_reflection.v1alpha import reflection
from hull.rudder import rudder_pb2 as pb, rudder_pb2_grpc as rpc

# other ports only for tests (RUDDER_WS_PORT, RUDDER_GRPC_PORT), so a test bridge never meets your own Firefox
WS_PORT, GRPC_PORT = int(os.environ.get("RUDDER_WS_PORT", 7834)), int(os.environ.get("RUDDER_GRPC_PORT", 7833))
TIMEOUT = 25  # under the extension's own 30 s
as_dict = lambda m: MessageToDict(m, preserving_proto_field_name=True)


def video_pb(d):
    """the extension's video record (JSON) → Video"""
    return ParseDict({k: v for k, v in d.items() if v is not None}, pb.Video(), ignore_unknown_fields=True)


class Bridge(rpc.RudderServicer):
    def __init__(self):
        self.ext = None  # Firefox's WebSocket
        self.state = pb.State()
        self.changed = asyncio.Event()
        self.state_watchers, self.video_watchers, self.shown_watchers, self.caption_watchers, self.feedback_watchers, self.clicks = set(), set(), set(), set(), set(), set()  # one queue per streaming call
        self.videos = collections.deque(maxlen=500)  # newest first
        self.apps = {}  # stage app name → queue of StageRequests
        self.pending = {}  # (app name, request id) → future of its results
        self.panels = {}  # id → panel (as JSON), sent again when Firefox reconnects
        self.asks = {}  # request id → future of Firefox's answer
        self.ids = itertools.count(1)

    # ---- Firefox side ----
    async def extension(self, ws):
        self.ext = ws  # a newer connection replaces an older one
        await self.sync_apps()
        for p in self.panels.values():
            await ws.send(json.dumps({"type": "panel", "panel": p}))
        try:
            async for raw in ws:
                m = json.loads(raw)
                t = m["type"]
                if t == "state":
                    self.set_state(m)
                elif t == "video":
                    ev = pb.VideoEvent(video=video_pb(m["video"]), outcome=pb.Outcome(**m["outcome"]))
                    self.videos.appendleft(ev)
                    for q in self.video_watchers:
                        q.put_nowait(ev)
                elif t == "shown":
                    ev = pb.Shown(ids=[str(i) for i in m["ids"]], at_ms=int(m.get("at") or time.time() * 1000))
                    for q in self.shown_watchers:
                        q.put_nowait(ev)
                elif t == "feedback":
                    ev = pb.Feedback(video=video_pb(m["video"]), like=bool(m["like"]), at_ms=int(m.get("at") or time.time() * 1000))
                    for q in self.feedback_watchers:
                        q.put_nowait(ev)
                elif t == "captions":
                    for line in m["lines"]:
                        ev = pb.Caption(video_id=str(line["video_id"]), start_ms=int(line["start_ms"]), end_ms=int(line["end_ms"]),
                                        text=str(line["text"]), language=str(line["language"]), auto=bool(line["auto"]))
                        for q in self.caption_watchers:
                            q.put_nowait(ev)
                elif t == "stage":
                    asyncio.create_task(self.run_stage(m))
                elif t == "panel-event":
                    for q in self.clicks:
                        q.put_nowait(pb.PanelEvent(panel=m["panel"], button=m["button"]))
                elif m.get("id") in self.asks:  # an answer: pipeline, timings, test-result
                    f = self.asks.pop(m["id"])
                    if not f.done():
                        f.set_result(m)
                elif t == "error":
                    print("rudder:", m["error"], flush=True)
        finally:
            if self.ext is ws:
                self.ext = None
                for f in self.asks.values():
                    if not f.done():
                        f.set_exception(ConnectionError("Firefox disconnected"))
                self.asks.clear()
                self.state.connected = False
                self.publish()

    async def sync_apps(self):
        if self.ext:
            await self.ext.send(json.dumps({"type": "apps", "names": sorted(self.apps)}))

    def set_state(self, m):
        s, learn = m.get("stats", {}), m.get("stats", {}).get("learning", {})
        self.state = pb.State(
            connected=True, enabled=bool(m.get("enabled")), filters=m.get("filters", []), stages=m.get("stages", []),
            stats=pb.Stats(checked=s.get("checked", 0), hidden=s.get("hidden", 0), hidden_by_filter=s.get("by", {}), hidden_by_stage=s.get("byStage", {}),
                           likes=learn.get("likes", 0), dislikes=learn.get("dislikes", 0), learning=bool(learn.get("learning"))),
            recent=[pb.Hidden(id=h["id"], title=h["title"], channel=h["channel"], why=h["why"], stage=h.get("stage") or "") for h in m.get("recent", [])])
        self.publish()

    def publish(self):
        self.state.apps[:] = sorted(self.apps)
        for q in self.state_watchers:
            q.put_nowait(self.state)
        self.changed.set()
        self.changed = asyncio.Event()

    async def run_stage(self, m):
        """Firefox asks an app stage about some videos; the app's answer (or the error) goes back"""
        name, n = m["name"], len(m["videos"])
        q = self.apps.get(name)
        out = {"type": "stage-result", "id": m["id"]}
        if not q:
            out["error"] = f"app {name} isn't connected"
        else:
            f = asyncio.get_running_loop().create_future()
            self.pending[(name, m["id"])] = f
            req = pb.StageRequest(id=m["id"], videos=[video_pb(v) for v in m["videos"]])
            req.config.update(m.get("config") or {})
            q.put_nowait(req)
            try:
                rs = await asyncio.wait_for(f, TIMEOUT)
                if len(rs) != n:
                    raise ValueError(f"{len(rs)} results for {n} videos")
                out["results"] = [{"decision": pb.Decision.Name(r.decision).lower(), "why": r.why, "fields": dict(r.fields)} for r in rs]
            except Exception as err:
                out["error"] = f"app {name}: {str(err) or type(err).__name__}"
            finally:
                self.pending.pop((name, m["id"]), None)
        if self.ext:
            await self.ext.send(json.dumps(out))

    async def ask(self, m, context, timeout=60):
        """send Firefox a request and wait for its answer"""
        if not self.ext:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "Firefox isn't connected to the bridge")
        m["id"] = next(self.ids)
        f = self.asks[m["id"]] = asyncio.get_running_loop().create_future()
        await self.ext.send(json.dumps(m))
        try:
            return await asyncio.wait_for(f, timeout)
        except (asyncio.TimeoutError, ConnectionError) as err:
            await context.abort(grpc.StatusCode.UNAVAILABLE, f"no answer from Firefox: {str(err) or 'timed out'}")
        finally:
            self.asks.pop(m["id"], None)

    # ---- gRPC side: state ----
    async def GetState(self, request, context):
        return self.state

    async def WatchState(self, request, context):
        q = asyncio.Queue()
        self.state_watchers.add(q)
        try:
            yield self.state
            while True:
                yield await q.get()
        finally:
            self.state_watchers.discard(q)

    async def SetFilters(self, request, context):
        if not self.ext:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "Firefox isn't connected to the bridge")
        changed = self.changed
        await self.ext.send(json.dumps({"type": "set-filters", "filters": list(request.filters)}))
        await asyncio.wait_for(changed.wait(), 5)
        return self.state

    async def SetEnabled(self, request, context):
        if not self.ext:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "Firefox isn't connected to the bridge")
        changed = self.changed
        await self.ext.send(json.dumps({"type": "set-enabled", "enabled": request.enabled}))
        await asyncio.wait_for(changed.wait(), 5)
        return self.state

    # ---- the pipeline ----
    async def pipeline(self, m, context):
        r = await self.ask(m, context)
        if r.get("error"):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, r["error"])
        return ParseDict({"stages": r["stages"], "kinds": r["kinds"]}, pb.Pipeline())

    async def GetPipeline(self, request, context):
        return await self.pipeline({"type": "get-pipeline"}, context)

    async def SetPipeline(self, request, context):
        return await self.pipeline({"type": "set-pipeline", "stages": [as_dict(s) for s in request.stages]}, context)

    async def Stage(self, requests, context):
        first = await anext(requests, None)
        name = first.hello.name.strip() if first and first.HasField("hello") else ""
        if not name or name in self.apps:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "send a hello with a name no other connected app uses, first")
        q = asyncio.Queue()
        self.apps[name] = q
        await self.sync_apps()
        self.publish()

        async def read():
            async for msg in requests:
                if msg.HasField("reply"):
                    f = self.pending.get((name, msg.reply.id))
                    if f and not f.done():
                        f.set_result(list(msg.reply.results))

        reader = asyncio.create_task(read())
        try:
            while True:
                get = asyncio.create_task(q.get())
                await asyncio.wait({get, reader}, return_when=asyncio.FIRST_COMPLETED)
                if not get.done():  # the app closed its side
                    get.cancel()
                    break
                yield get.result()
        finally:
            reader.cancel()
            del self.apps[name]
            for (app, _), f in list(self.pending.items()):
                if app == name and not f.done():
                    f.set_exception(ConnectionError("app left"))
            asyncio.create_task(self.sync_apps())
            self.publish()

    # ---- video data ----
    async def WatchVideos(self, request, context):
        q = asyncio.Queue()
        self.video_watchers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self.video_watchers.discard(q)

    async def WatchShown(self, request, context):
        q = asyncio.Queue()
        self.shown_watchers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self.shown_watchers.discard(q)

    async def WatchCaptions(self, request, context):
        q = asyncio.Queue()
        self.caption_watchers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self.caption_watchers.discard(q)

    async def WatchFeedback(self, request, context):
        q = asyncio.Queue()
        self.feedback_watchers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self.feedback_watchers.discard(q)

    async def GetVideos(self, request, context):
        out = pb.VideoEvents()
        for ev in itertools.islice(self.videos, request.limit or None):
            e = out.events.add()
            e.CopyFrom(ev)
            if not request.thumbnails:
                e.video.ClearField("thumbnail")
        return out

    async def Test(self, request, context):
        t = time.perf_counter()
        m = await self.ask({"type": "test", "videos": [as_dict(v) for v in request.videos]}, context, timeout=120)
        if m.get("error"):
            await context.abort(grpc.StatusCode.INTERNAL, m["error"])
        return pb.TestResults(ms=(time.perf_counter() - t) * 1000, results=[
            pb.TestResult(id=r["id"], outcome=pb.Outcome(hidden=r["hidden"], decided_by=r["decided_by"], why=r["why"]), fields=r["fields"],
                          trace=[pb.StageTrace(**x) for x in r["trace"]])
            for r in m["results"]])

    # ---- panels ----
    async def SetPanel(self, request, context):
        if not request.id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "a panel needs an id")
        p = as_dict(request)
        if request.blocks:
            self.panels[request.id] = p
        else:
            self.panels.pop(request.id, None)
        if self.ext:
            await self.ext.send(json.dumps({"type": "panel", "panel": p}))
        return pb.Empty()

    async def PanelEvents(self, request, context):
        q = asyncio.Queue()
        self.clicks.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self.clicks.discard(q)

    # ---- timing ----
    async def GetTimings(self, request, context):
        m = await self.ask({"type": "timings", "reset": request.reset}, context)
        return pb.Timings(timings=[pb.Timing(name=t["name"], count=t["count"], mean_ms=t["mean"], p50_ms=t["p50"], p95_ms=t["p95"],
                                             max_ms=t["max"], last_ms=t["last"]) for t in m["timings"]])


async def main():
    bridge = Bridge()
    server = grpc.aio.server(options=[("grpc.max_send_message_length", 64 << 20), ("grpc.max_receive_message_length", 64 << 20)])  # thumbnails
    rpc.add_RudderServicer_to_server(bridge, server)
    # lets Postman, grpcurl and other tools list the calls without the .proto
    reflection.enable_server_reflection([pb.DESCRIPTOR.services_by_name["Rudder"].full_name, reflection.SERVICE_NAME], server)
    server.add_insecure_port(f"127.0.0.1:{GRPC_PORT}")  # this computer only
    await server.start()
    async with websockets.serve(bridge.extension, "127.0.0.1", WS_PORT, max_size=None):  # thumbnails make messages large
        print(f"bridge: Firefox on ws://127.0.0.1:{WS_PORT}, apps on grpc 127.0.0.1:{GRPC_PORT}", flush=True)
        await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(main())
