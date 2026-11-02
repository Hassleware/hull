"""Hull's checks, no Firefox needed. Run: python -m unittest
A fake Rudder (an in-process gRPC server speaking Rudder's real contract) stands in for Rudder's bridge."""
import asyncio, tempfile, unittest

import grpc
from google.protobuf.json_format import MessageToDict

from hull.config import load
from hull.link import Hull
from hull.rudder import rudder_pb2 as pb, rudder_pb2_grpc as rpc
from hull.bloom import Bloom
from hull.stages.repeats import Repeats
from hull.stages.rules import Rules
from hull.store import Store
from hull.video import Result, Video

RULES = {"rules": [{"pattern": "los santos|\\bgta\\b", "action": "hide", "why": "GTA"},
                   {"pattern": "^calm", "action": "show", "why": "calm"}]}


class TestRules(unittest.TestCase):
    def test_first_match_decides(self):
        rs = Rules(RULES, None).decide([Video("a", title="listening to bangers on the Los Santos train"), Video("b", title="Calm piano"),
                                  Video("c", title="Bread", fields={"thumbnail_text": "GTA 6"}), Video("d", title="Bread")])
        self.assertEqual([(r.decision, r.why) for r in rs], [("hide", "GTA"), ("show", "calm"), ("hide", "GTA"), ("pass", "")])

    def test_bad_action_refused(self):
        with self.assertRaises(ValueError):
            Rules({"rules": [{"pattern": "x", "action": "maybe"}]}, None)


class TestRepeats(unittest.TestCase):
    def test_bloom_never_forgets_and_rarely_lies(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Bloom(tmp + "/b", capacity=10_000)
            for i in range(10_000):
                b.add(f"v{i}")
            b.save()
            b = Bloom(tmp + "/b", capacity=10_000)  # from disk
            self.assertTrue(all(f"v{i}" in b for i in range(10_000)))
            self.assertLess(sum(f"x{i}" in b for i in range(10_000)), 30)  # ~0.1%

    def test_shown_once_never_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.shown(["old"], 1)  # shown before Hull had the stage
            r = Repeats({}, store)
            self.assertEqual([x.decision for x in r.decide([Video("old"), Video("new")])], ["hide", "pass"])
            r.shown(["new"])
            self.assertEqual(Repeats({}, store).decide([Video("new")])[0].why, "shown before")  # kept on disk
            store.db.close()


class FakeRudder(rpc.RudderServicer):
    """Rudder's bridge, in miniature: a pipeline, one stage request, one video event, panels."""

    def __init__(self):
        self.stages = [pb.Stage(id=i, kind=i) for i in ("your-clicks", "keywords", "learned", "thumbnail-text")]
        self.apps, self.panels, self.replies, self.answered = set(), [], asyncio.Queue(), False

    async def GetState(self, request, context):
        return pb.State(connected=True, apps=sorted(self.apps), stages=[s.id for s in self.stages])

    async def GetPipeline(self, request, context):
        return pb.Pipeline(stages=self.stages)

    async def SetPipeline(self, request, context):
        self.stages = list(request.stages) or [pb.Stage(id=i, kind=i) for i in ("your-clicks", "keywords", "learned", "thumbnail-text")]
        return pb.Pipeline(stages=self.stages)

    async def Stage(self, requests, context):
        hello = await anext(requests)
        self.apps.add(hello.hello.name)
        while not any(s.kind == "app" for s in self.stages):  # wait for Hull to join the pipeline
            await asyncio.sleep(0.05)
        mine = next(s for s in self.stages if s.kind == "app")
        req = pb.StageRequest(id=7, videos=[pb.Video(id="gta", title="GTA 6 trailer"), pb.Video(id="bread", title="Bread at home")])
        req.config.CopyFrom(mine.config)
        yield req
        reply = await anext(requests)
        await self.replies.put(reply.reply)
        self.answered = True
        async for _ in requests:
            pass

    async def WatchVideos(self, request, context):
        yield pb.VideoEvent(video=pb.Video(id="bread", title="Bread at home", thumbnail=b"\xff\xd8jpg", thumbnail_type="image/jpeg"),
                            outcome=pb.Outcome(hidden=False))
        await asyncio.Event().wait()

    async def WatchShown(self, request, context):
        while not self.answered:  # after the stage answered
            await asyncio.sleep(0.05)
        yield pb.Shown(ids=["bread"], at_ms=1)
        await asyncio.Event().wait()

    async def SetPanel(self, request, context):
        self.panels.append(request)
        return pb.Empty()


class TestHullWithRudder(unittest.IsolatedAsyncioTestCase):
    async def test_joins_answers_records_and_leaves(self):
        fake, server = FakeRudder(), grpc.aio.server()
        rpc.add_RudderServicer_to_server(fake, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load(tmp + "/none.toml")  # defaults
            cfg["rudder"]["address"] = f"127.0.0.1:{port}"
            cfg["stage"] = [{"id": "rules", "kind": "rules", "config": RULES}]
            store = Store(tmp)
            hull = Hull(cfg, store)
            task = asyncio.create_task(hull.main())

            reply = await asyncio.wait_for(fake.replies.get(), 10)
            self.assertEqual([s.id for s in fake.stages], ["your-clicks", "keywords", "hull-rules", "learned", "thumbnail-text"])
            config = MessageToDict(fake.stages[2].config)
            self.assertEqual((config["name"], config["stage"], config["when_missing"], config["remember"]), ("hull", "rules", "hide", False))
            self.assertEqual([(r.decision, r.why) for r in reply.results], [(pb.HIDE, "GTA"), (pb.PASS, "")])

            for _ in range(100):  # the video event and the panel
                if fake.panels and store.stats()["videos"] == 2 and store.stats()["shown"]:
                    break
                await asyncio.sleep(0.05)
            s = store.stats()
            self.assertEqual((s["videos"], s["thumbnails"], s["hid_by_stage"], s["shown"]), (2, 1, {"rules": 1}, 1))
            self.assertEqual(s["recent"], [("GTA 6 trailer", "rules", "GTA")])
            self.assertEqual(fake.panels[-1].title, "Hull")

            task.cancel()  # like Ctrl-C: Hull takes its stage and panel back out
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual([s.id for s in fake.stages], ["your-clicks", "keywords", "learned", "thumbnail-text"])
            self.assertEqual(len(fake.panels[-1].blocks), 0)
            store.db.close()
        await server.stop(None)

    async def test_a_failing_stage_hides(self):
        class Broken:
            def decide(self, videos):
                raise RuntimeError("out of memory")
        hull = Hull({"rudder": {"address": ""}, "pipeline": {"after": "keywords", "when_missing": "hide"}, "stage": []}, None)
        hull.stages["broken"] = Broken()
        hull.store = type("S", (), {"stage_results": lambda *a: None})()
        req = pb.StageRequest(id=1, videos=[pb.Video(id="a", title="x")])
        req.config.update({"name": "hull", "stage": "broken"})
        out = asyncio.Queue()
        with self.assertLogs("hull", "ERROR"):
            await hull.answer(req, out)
        r = (await out.get()).reply.results[0]
        self.assertEqual((r.decision, r.why), (pb.HIDE, "hull broken failed: out of memory"))


if __name__ == "__main__":
    unittest.main()
