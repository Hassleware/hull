"""Hull's checks, no Firefox needed. Run: python -m unittest
A fake Rudder (an in-process gRPC server speaking Rudder's real contract) stands in for Rudder's bridge."""
import asyncio, io, math, tempfile, time, unittest, urllib.error, zlib

import grpc
import numpy as np
from pathlib import Path
from google.protobuf.json_format import MessageToDict

from hull.config import load
from hull.link import Hull
from hull.rudder import rudder_pb2 as pb, rudder_pb2_grpc as rpc
from hull.bloom import Bloom
from hull.graph import PREFIX, Graph
from hull.stages.internet_culture import InternetCulture
from hull.stages.repeats import Repeats
from hull.stages.rules import Rules
from hull.settings import Settings
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


class TestNearDuplicates(unittest.TestCase):
    def jpg(self, shade, text, box=(40, 100, 300, 260)):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (480, 360), shade)
        ImageDraw.Draw(img).rectangle(box, fill="white")
        ImageDraw.Draw(img).text((60, 150), text, fill="black")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        return buf.getvalue()

    def test_copies_are_repeats_episodes_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            r = Repeats({}, store)
            orig = Video("a", title="I spent 100 days in Los Santos", thumbnail=self.jpg((200, 40, 40), "100 DAYS"))
            self.assertEqual(r.decide([orig])[0].decision, "pass")
            r.shown(["a"])
            small = io.BytesIO()
            from PIL import Image
            Image.open(io.BytesIO(orig.thumbnail)).resize((320, 240)).save(small, "JPEG", quality=60)  # same image, smaller
            rs = r.decide([Video("b", title="I SPENT 100 DAYS IN LOS SANTOS!!"), Video("c", title="totally different", thumbnail=small.getvalue()),
                           Video("d", title="Minecraft hardcore ep 12"), Video("e", title="Bread", thumbnail=self.jpg((20, 90, 200), "BREAD", (200, 20, 460, 200)))])
            self.assertEqual([x.decision for x in rs], ["hide", "hide", "pass", "pass"])
            self.assertIn("same title", rs[0].why)
            self.assertIn("same thumbnail", rs[1].why)
            r.shown(["d"])
            self.assertEqual(r.decide([Video("f", title="Minecraft hardcore ep 13")])[0].decision, "pass")
            self.assertEqual(Repeats({}, store).decide([Video("g", title="i spent 100 days in los santos")])[0].decision, "hide")  # from disk
            store.db.close()


class FakeOllama:
    """Gemma and embeddinggemma in miniature: topics from a table, embeddings from hashed words"""
    TOPICS = {"GTA 6 trailer": ["gta vi", "rockstar games", "video games"], "Bayes in 10 minutes": ["bayes theorem", "statistics"],
              "Rockstar's next game": ["grand theft auto vi", "video games"], "PyMC models": ["pymc", "statistics"],
              "PyMC install": ["pymc", "python"], "Minecraft redstone": ["minecraft", "video games"]}
    SAME = {"grand theft auto vi": "gta vi"}  # names embeddinggemma would put together

    def __init__(self, delay=0):
        self.delay, self.calls, self.up, self.unloaded = delay, 0, True, []

    def ping(self):
        return self.up

    def unload(self, model):
        self.unloaded.append(model)

    def json(self, model, prompt, schema, images=(), system="", timeout=None):
        if not self.up:
            raise urllib.error.URLError("Ollama isn't there")
        time.sleep(self.delay)
        self.calls += 1
        if "What's said in it" in prompt:
            self.heard_prompt = prompt
            return {"topics": ["bayes theorem", "probability theory"]}
        if prompt.startswith("A viewer's goal"):  # sorting the map: a label for every topic
            return {t: "for" if t in ("bayes theorem", "probability theory") else "against" if t == "video games" else "neither"
                    for t in schema["properties"]}
        if "against" in schema["properties"]:
            return {"for": ["Statistics ", "statistics"], "against": ["video games", "drama"]}
        if "part_of" in schema["properties"]:
            self.asked = prompt
            return {"part_of": prompt.startswith('On a viewer\'s map of the topics of the YouTube videos they see, is "video games"'), "why": "it's a game"}
        return {"topics": next(t for title, t in self.TOPICS.items() if f"Title: {title}" in prompt)}

    def embed(self, model, texts):
        out = np.zeros((len(texts), 64), np.float32)
        for i, t in enumerate(texts):
            t = t.removeprefix(PREFIX)
            for w in self.SAME.get(t, t).split():
                out[i, zlib.crc32(w.encode()) % 64] += 1
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


def internet_culture(store, ollama):
    c = InternetCulture({"budget": 2}, store)
    c.ollama = c.graph.ollama = ollama
    c.graph.vecs = c.graph.vecs[:, :64]
    return c


class TestInternetCulture(unittest.TestCase):
    def test_tags_into_the_graph_merging_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            rs = c.decide([Video("a", title="GTA 6 trailer"), Video("b", title="Bayes in 10 minutes")])
            self.assertEqual([r.fields["topics"] for r in rs], ["gta vi; rockstar games; video games", "bayes theorem; statistics"])
            r = c.decide([Video("c", title="Rockstar's next game")])[0]
            self.assertEqual(r.fields["topics"], "gta vi; video games")  # "grand theft auto vi" is "gta vi"
            n = c.ollama.calls
            c.decide([Video("a", title="GTA 6 trailer")])
            self.assertEqual(c.ollama.calls, n)  # tagged once
            self.assertEqual(dict(c.graph.stats()["top"])["video games"], 2)
            self.assertEqual(c.panel()[0][0], "Internet culture: 5 topics from 3 videos. Most seen:")
            store.db.close()

    def test_slow_tagging_hides_then_catches_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama(delay=3))
            self.assertEqual(c.decide([Video("a", title="GTA 6 trailer")])[0].why, "not tagged yet")
            c.pool.shutdown(wait=True)
            self.assertEqual(c.graph.topics_of("a"), ["gta vi", "rockstar games", "video games"])
            store.db.close()


class TestBlockAndFocus(unittest.TestCase):
    def test_block_and_focus_through_the_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            c.block, c.focus, c.focus_at, c.focus_ask = ["video games"], ["statistics"], 0.6, 0.6
            rs = c.decide([Video("a", title="GTA 6 trailer"), Video("b", title="Bayes in 10 minutes"), Video("m", title="Minecraft redstone")])
            self.assertEqual([r.why for r in rs], ["gta vi is in what you block (video games)", "", "minecraft is in what you block (video games)"])
            self.assertEqual(rs[1].fields["focus"], "in your focus area: bayes theorem")  # every bayes video is about statistics
            c.block = []
            self.assertEqual(c.decide([Video("m", title="Minecraft redstone")])[0].why, "off focus (nearest: minecraft, 0.00)")
            # "pymc" isn't worded like "statistics"; once most of its videos are about statistics, it's in the area
            self.assertEqual(c.decide([Video("i", title="PyMC install")])[0].decision, "hide")
            for i in range(3):
                c.graph.attest(f"p{i}", ["pymc", "statistics"])
            r = c.decide([Video("j", title="PyMC install")])[0]
            self.assertEqual((r.decision, r.fields["focus"]), ("pass", "in your focus area: pymc"))  # 3 of its 5 videos
            store.db.close()


class TestGemmaJudges(unittest.TestCase):
    def test_in_between_gemma_decides_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            c.block, c.block_at, c.block_ask, c.seed = ["games"], 1.01, 0.5, 1.01  # no area: "video games" is in between
            r = c.decide([Video("m", title="Minecraft redstone")])[0]
            self.assertEqual((r.decision, r.why), ("hide", "video games is near games: it's a game"))
            n = c.ollama.calls
            c.decide([Video("m", title="Minecraft redstone")])
            self.assertEqual(c.ollama.calls, n)  # asked once
            store.db.close()

    def test_focus_asks_with_the_graph_as_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            c.focus, c.focus_at, c.focus_ask, c.seed = ["statistics"], 1.01, 0.0, 1.01
            store._keep(Video("m", title="Minecraft redstone"), 0)
            r = c.decide([Video("m", title="Minecraft redstone")])[0]
            self.assertEqual(r.why, "off focus: minecraft isn't statistics (it's a game)")
            self.assertIn('Videos about "minecraft": Minecraft redstone', c.ollama.asked)
            self.assertEqual(InternetCulture({}, store).verdicts[("minecraft", "statistics")][0], False)  # on disk
            store.db.close()


class FakeRudder(rpc.RudderServicer):
    """Rudder's bridge, in miniature: a pipeline, one stage request, one video event, panels."""

    def __init__(self):
        self.stages = [pb.Stage(id=i, kind=i) for i in ("your-clicks", "keywords", "learned", "thumbnail-text")]
        self.apps, self.panels, self.replies, self.answered = set(), [], asyncio.Queue(), False
        self.enabled, self.changed = True, asyncio.Event()

    def state(self):
        return pb.State(connected=True, enabled=self.enabled, apps=sorted(self.apps), stages=[s.id for s in self.stages])

    def touch(self):
        self.changed.set()
        self.changed = asyncio.Event()

    async def GetState(self, request, context):
        return self.state()

    async def WatchState(self, request, context):
        while True:
            changed = self.changed
            yield self.state()
            await changed.wait()

    async def SetEnabled(self, request, context):
        self.enabled = request.enabled
        self.touch()
        return self.state()

    async def GetPipeline(self, request, context):
        return pb.Pipeline(stages=self.stages)

    async def SetPipeline(self, request, context):
        self.stages = list(request.stages) or [pb.Stage(id=i, kind=i) for i in ("your-clicks", "keywords", "learned", "thumbnail-text")]
        self.touch()
        return pb.Pipeline(stages=self.stages)

    async def Stage(self, requests, context):
        hello = await anext(requests)
        self.apps.add(hello.hello.name)
        self.touch()
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

    async def WatchFeedback(self, request, context):
        while not self.answered:
            await asyncio.sleep(0.05)
        yield pb.Feedback(video=pb.Video(id="liked", title="A video you liked"), like=True)
        await asyncio.Event().wait()

    async def WatchCaptions(self, request, context):
        await asyncio.Event().wait()
        yield pb.Caption()

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
            self.assertEqual([s.id for s in fake.stages], ["your-clicks", "hull-rules", "keywords", "learned", "thumbnail-text"])  # before the keywords
            config = MessageToDict(fake.stages[1].config)
            self.assertEqual((config["name"], config["stage"], config["when_missing"], config["remember"]), ("hull", "rules", "hide", False))
            self.assertEqual([(r.decision, r.why) for r in reply.results], [(pb.HIDE, "GTA"), (pb.PASS, "")])

            for _ in range(100):  # the video event and the panel
                if fake.panels and store.stats()["videos"] == 3 and store.stats()["shown"] and store.stats()["rated"]:
                    break
                await asyncio.sleep(0.05)
            s = store.stats()
            self.assertEqual((s["videos"], s["thumbnails"], s["hid_by_stage"], s["shown"], s["rated"]), (3, 1, {"rules": 1}, 1, 1))
            self.assertEqual(s["recent"], [("GTA 6 trailer", "rules", "GTA")])
            self.assertEqual(fake.panels[-1].title, "Hull")
            self.assertIn("<svg", fake.panels[-1].icon)  # Rudder's popup shows it while Hull is connected

            task.cancel()  # like Ctrl-C: Hull takes its stage and panel back out
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual([s.id for s in fake.stages], ["your-clicks", "keywords", "learned", "thumbnail-text"])
            self.assertEqual(len(fake.panels[-1].blocks), 0)
            store.db.close()
        await server.stop(None)

    async def test_switches_and_goals(self):
        fake, server = FakeRudder(), grpc.aio.server()
        rpc.add_RudderServicer_to_server(fake, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load(tmp + "/none.toml")
            cfg["rudder"]["address"] = f"127.0.0.1:{port}"
            cfg["stage"] = [{"id": "rules", "kind": "rules", "config": RULES}]
            store, settings = Store(tmp), Settings(tmp)
            hull, seen = Hull(cfg, store, settings), []
            hull.listeners.append(seen.append)
            task = asyncio.create_task(hull.main())

            async def until(ok):
                for _ in range(100):
                    if ok():
                        return
                    await asyncio.sleep(0.05)
                self.fail("timed out")

            await until(lambda: hull.status["steering"] and hull.status["filtering"])
            hull.set_steering(False)  # out of the pipeline, still connected
            await until(lambda: not hull.status["steering"])
            self.assertNotIn("hull-rules", [s.id for s in fake.stages])
            self.assertEqual((hull.status["rudder"], Settings(tmp).get("steering")), (True, False))
            await until(lambda: "watching" in fake.panels[-1].blocks[0].text)
            hull.set_filtering(False)  # Rudder's own switch
            await until(lambda: not hull.status["filtering"])
            self.assertFalse(fake.enabled)
            hull.set_steering(True)
            await until(lambda: hull.status["steering"])
            hull.set_goals([{"text": "learn stats", "focus": ["statistics"], "block": []},
                            {"text": "no games", "focus": [], "block": ["video games", "statistics"]}])  # they disagree: allowed
            self.assertEqual([g["text"] for g in Settings(tmp).get("goals")], ["learn stats", "no games"])
            Hull(cfg, store, Settings(tmp))  # a restart with a saved goal
            await until(lambda: "Goals: learn stats; no games" in fake.panels[-1].blocks[0].text)
            self.assertTrue(any(s["steering"] is False for s in seen))  # the app heard about the switch
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            store.db.close()
        await server.stop(None)

    async def test_news_reaches_stages_and_a_failing_one_doesnt_stop_hull(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            hull = Hull({"rudder": {"address": ""}, "pipeline": {"after": "your-clicks", "when_missing": "hide"},
                         "stage": [{"id": "repeats", "kind": "repeats", "config": {}}]}, store)
            got = []
            hull.stages["broken"] = type("B", (), {"seen": lambda self, v: 1 / 0})()
            hull.stages["ok"] = type("O", (), {"seen": lambda self, v: got.append(v.id)})()
            with self.assertLogs("hull", "ERROR"):
                await hull.tell("seen", Video("a", title="x"))  # repeats has no seen hook; broken raises; ok still hears
            self.assertEqual(got, ["a"])
            store.db.close()

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



class TestAreas(unittest.TestCase):
    def test_a_goal_covers_its_area_of_the_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            g = c.graph
            for vid, topics in {"1": ["video games", "minecraft"], "2": ["video games", "frostpunk", "city building"], "3": ["city building", "frostpunk"],
                                "4": ["video games", "music"], **{f"m{i}": ["music", "pop music"] for i in range(5)}}.items():
                g.attest(vid, topics)
            c.focus, c.reach["focus"] = ["video games"], (0.5, 2)  # frostpunk: one edge; city building: two
            area = c.area("focus")
            self.assertEqual(area, {"video games", "minecraft", "frostpunk", "city building"})  # music touched it once: 1 of 6
            self.assertEqual(c.judge(["minecraft", "pirates"]).fields["focus"], "in your focus area: minecraft")
            self.assertEqual(c.marks(["frostpunk", "music"]), {"frostpunk": "focus"})
            c.focus, c.block = [], ["video games"]
            self.assertEqual(c.judge(["city building"]).decision, "hide")
            self.assertEqual(c.judge(["pop music"]).decision, "pass")
            store.db.close()


class TestSides(unittest.TestCase):
    def test_both_sides_vote_most_specific_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            for vid, topics in {"1": ["gta vi", "trailer", "video games"], "2": ["trailer", "movies"], "3": ["drama", "trailer"]}.items():
                c.graph.attest(vid, topics)
            c.focus, c.block = ["gta vi", "video games"], ["trailer", "drama"]
            self.assertEqual(c.judge(["gta vi", "trailer", "video games"]).decision, "pass")  # a game trailer
            self.assertEqual(c.judge(["trailer", "movies"]).decision, "hide")
            self.assertEqual(c.side("video games"), "focus")  # the goal's own topics stay put, whatever's around them
            c.focus = []
            self.assertEqual(c.judge(["gta vi", "trailer", "video games"]).decision, "hide")  # only things to avoid: any hides
            store.db.close()


class TestManyGoals(unittest.TestCase):
    def test_goals_add_up_and_against_wins_a_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, settings = Store(tmp), Settings(tmp)
            settings.update(goal={"text": "old", "focus": ["cooking"], "block": []})  # one goal, as kept before
            hull = Hull({"rudder": {"address": ""}, "pipeline": {"after": "your-clicks", "when_missing": "hide"},
                         "stage": [{"id": "internet-culture", "kind": "internet-culture", "config": {}}]}, store, settings)
            c = hull.stages["internet-culture"]
            self.assertEqual((c.focus, [g["text"] for g in hull.goals]), (["cooking"], ["old"]))
            hull.set_goals([{"text": "a", "focus": ["cooking", "music"], "block": []}, {"text": "b", "focus": [], "block": ["music"]}])
            self.assertEqual((c.focus, c.block), (["cooking"], ["music"]))
            store.db.close()


class TestGoal(unittest.TestCase):
    def test_gemma_drafts_both_sides_and_sorts_the_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            for vid, topics in {"1": ["bayes theorem", "statistics"], "2": ["video games", "minecraft"], "3": ["probability theory"]}.items():
                c.graph.attest(vid, topics)
            g = c.draft_goal(" learn stats, no games ", batch=2)  # the map's 5 topics in 3 batches
            self.assertEqual(g["text"], "learn stats, no games")
            self.assertEqual(g["sorted"], 5)
            # bayes theorem shares a video with statistics: kept; probability theory, labelled "for" but alone on the map
            # and unlike statistics in meaning: a stray, dropped
            self.assertEqual(set(g["focus"]), {"statistics", "bayes theorem"})
            self.assertEqual(g["block"], ["video games", "drama"])
            # progress: told at each step, fractions rising to 1; the first draft has no pace to go on, the next does
            seen = []
            c.draft_goal("learn stats", batch=2, progress=lambda **p: seen.append(p))
            self.assertEqual([p["step"] for p in seen][:2], ["Gemma reads your goal", "Gemma sorts 5 topics"])
            self.assertEqual((seen[-1]["step"], seen[-1]["fraction"], seen[-1]["eta"]), ("Done", 1.0, 0.0))
            self.assertIsNotNone(seen[0]["eta"])  # the earlier draft's pace, measured and kept
            fractions = [p["fraction"] for p in seen if p["eta"] is not None]
            self.assertEqual(fractions, sorted(fractions))
            store.db.close()


class TestIngest(unittest.TestCase):
    def test_videos_seen_or_rated_are_tagged_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            c.seen(Video("a", title="GTA 6 trailer")).result()  # hidden by a stage before Hull's tagging, say
            self.assertEqual(c.graph.topics_of("a"), ["gta vi", "rockstar games", "video games"])
            n = c.ollama.calls
            self.assertIsNone(c.seen(Video("a", title="GTA 6 trailer")))  # already on the map
            self.assertEqual(c.ollama.calls, n)
            store.db.close()


class TestTaste(unittest.TestCase):
    def test_learns_from_likes_and_dislikes(self):
        from hull.stages.taste import Taste
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            t = Taste({"near": 0.6, "topic_dislikes": 2}, store)
            t.ollama = FakeOllama()
            self.assertEqual(t.decide([Video("x", title="GTA 6 gameplay")])[0].decision, "pass")  # nothing disliked yet
            store.rated(Video("d1", title="GTA 6 trailer reaction", channel="Hype"), False)
            store.rated(Video("l1", title="Sourdough bread at home", channel="Baker"), True)
            rs = t.decide([Video("x", title="GTA 6 trailer breakdown", channel="Hype"), Video("y", title="Sourdough bread for beginners", channel="Baker"),
                           Video("d1", title="GTA 6 trailer reaction", channel="Hype")])
            self.assertEqual([r.decision for r in rs], ["hide", "pass", "pass"])  # rated ones are Rudder's
            self.assertIn("which you disliked", rs[0].why)
            # a topic disliked twice and never liked hides wherever it turns up
            g = Graph(store, FakeOllama(), merge=0.99)
            g.vecs = g.vecs[:, :64]
            for vid, topics in {"d1": ["true crime", "news"], "d2": ["true crime"], "z": ["true crime", "podcasts"]}.items():
                g.attest(vid, topics)
            store.rated(Video("d2", title="Another case", channel="Crime"), False)
            r = t.decide([Video("z", title="Totally new words here", channel="Pod")])[0]
            self.assertEqual(r.why, "you've disliked 2 videos about true crime")
            store.db.close()


class TestGemmaSwitch(unittest.TestCase):
    def test_off_queues_judges_by_title_and_catches_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            health = []
            c.listeners.append(lambda h, q: health.append((h, q)))
            c.block = ["video games"]
            c.set_llm(False)
            self.assertEqual((c.health, c.ollama.unloaded), ("off", ["gemma4:e4b"]))  # off the graphics card
            store._keep(Video("a", title="GTA 6 trailer"), 0)
            store._keep(Video("b", title="Bayes in 10 minutes"), 0)
            rs = c.decide([Video("a", title="GTA 6 trailer"), Video("b", title="Bayes in 10 minutes")])
            self.assertEqual(c.ollama.calls, 0)  # no Gemma
            self.assertEqual(c.queued(), 2)
            self.assertEqual([r.fields.get("queued") for r in rs], ["for Gemma", "for Gemma"])  # judged by title meanwhile
            c.heard("b", "x" * 700)  # a watched video's captions: queued too
            self.assertEqual(c.queued(), 3)
            self.assertEqual(health[-1], ("off", 3))
            c.set_llm(True)
            c.drain()  # what the watch does once Gemma's back
            self.assertEqual(c.queued(), 0)
            self.assertEqual(c.graph.topics_of("a"), ["gta vi", "rockstar games", "video games"])
            store.db.close()

    def test_a_crash_is_noticed_and_its_work_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            c.ollama.up = False  # Ollama crashed
            store._keep(Video("a", title="GTA 6 trailer"), 0)
            r = c.decide([Video("a", title="GTA 6 trailer")])[0]
            self.assertEqual(c.health, "down")
            self.assertEqual(r.fields.get("queued"), "for Gemma")  # judged by its title instead, and queued
            c.decide([Video("a", title="GTA 6 trailer")])  # now known to be down: queued, by title
            self.assertEqual(c.queued(), 1)
            c.ollama.up = True
            c.set_health("ready")
            c.drain()
            self.assertEqual((c.queued(), c.graph.topics_of("a")), (0, ["gta vi", "rockstar games", "video games"]))
            store.db.close()


class TestStartup(unittest.TestCase):
    def test_runs_rudders_bridge_only_when_none_is_running(self):
        import socket
        hull = Hull({"rudder": {"address": "127.0.0.1:7833"}, "pipeline": {"after": "your-clicks", "when_missing": "hide"}, "stage": []}, None)
        try:
            socket.create_connection(("127.0.0.1", 7833), timeout=1).close()
            self.assertFalse(hull.ensure_bridge())  # one's running (Rudder's own): Hull uses it
        except OSError:
            self.assertTrue(hull.ensure_bridge())  # none: Hull runs Rudder's bridge
            for _ in range(50):
                try:
                    socket.create_connection(("127.0.0.1", 7833), timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.1)
            self.assertFalse(hull.ensure_bridge())  # and now it answers

    def test_uninstall_removes_startup_and_data_only_when_asked(self):
        from hull import autostart, uninstall
        calls = []
        real, autostart.set_on = autostart.set_on, lambda on, config: calls.append(on)  # not the real startup list
        try:
            with tempfile.TemporaryDirectory() as tmp:
                data = Path(tmp) / "data"
                Store(data).db.close()
                uninstall.remove(Path(tmp) / "hull.toml", data, delete_data=False)
                self.assertTrue((data / "hull.db").exists())  # kept
                uninstall.remove(Path(tmp) / "hull.toml", data, delete_data=True)
                self.assertFalse(data.exists())
            self.assertEqual(calls, [False, False])  # out of Windows startup both times
            self.assertFalse(uninstall.delete_exe_later())  # not Hull.exe: nothing to delete
        finally:
            autostart.set_on = real

    def test_the_app_loads(self):
        import hull.app  # the window's code: a typo there breaks Hull.exe, and no other test loads it
        self.assertTrue(hull.app.run)

    def test_start_with_windows_command(self):
        from hull import autostart
        self.assertIn("-m hull --tray --config", autostart.command("hull.toml"))


class TestDraftScales(unittest.TestCase):
    def test_sorts_only_the_nearest_and_remembers(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            c.graph.attest("x", ["video games", "drama", "statistics"])
            c.graph.attest("y", ["cooking", "baking"])
            c.graph.attest("z", ["statistics", "baking"])
            c.draft_near, c.draft_linked = 1, 1
            # the closest by meaning, then one that shares its videos (baking: on half of statistics' videos)
            self.assertEqual(c.nearest_topics(["statistics"]), ["statistics", "baking"])
            c.draft_near = 3
            g = c.draft_goal("learn stats", batch=2)
            self.assertEqual((g["sorted"], g["asked"], g["map"]), (4, 4, 5))  # 3 nearest + 1 on the same videos
            calls = c.ollama.calls
            g2 = c.draft_goal("  Learn   stats ", batch=2)  # the same goal again: all remembered
            self.assertEqual((g2["asked"], c.ollama.calls - calls), (0, 1))  # only Gemma's first read of the goal
            self.assertEqual((g2["focus"], g2["block"]), (g["focus"], g["block"]))
            store.db.close()


class TestDraftHoldsUp(unittest.TestCase):
    def test_a_failing_batch_is_retried_and_tagging_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            c.graph.attest("x", ["video games", "drama", "statistics"])
            real, fails = c.ollama.json, [1]

            def flaky(model, prompt, schema, images=(), system="", timeout=None):
                if "neither" in str(schema) and fails[0]:  # the first sort batch times out once
                    fails[0] -= 1
                    raise TimeoutError("timed out")
                if "neither" in str(schema):  # while a batch runs, a new video arrives: it waits in the queue
                    store._keep(Video("new", title="GTA 6 trailer"), 0)
                    seen.append(c.decide([Video("new", title="GTA 6 trailer")])[0].fields.get("queued"))
                return real(model, prompt, schema, images, system)
            seen = []
            c.ollama.json = flaky
            g = c.draft_goal("learn stats", batch=2)
            self.assertEqual(g["sorted"], 3)  # nothing lost to the timeout
            self.assertIn("for Gemma", seen)
            self.assertFalse(c.drafting)
            self.assertEqual(c.queued(), 1)
            store.db.close()

    def test_reads_json_with_extra_text_after(self):
        import hull.ollama as ho
        o = ho.Ollama()
        o._post = lambda path, body, timeout=None: {"response": '{"topics": ["a"]}\n\n}'}
        self.assertEqual(o.json("m", "p", {}), {"topics": ["a"]})


class TestCaptions(unittest.TestCase):
    def test_a_watched_video_is_tagged_again_from_whats_said(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            c = internet_culture(store, FakeOllama())
            c.heard_chars = 40
            c.decide([Video("b", title="Bayes in 10 minutes")])  # tagged from its title: bayes theorem, statistics
            store._keep(Video("b", title="Bayes in 10 minutes"), 0)
            self.assertIsNone(c.heard("b", "today we update our beliefs"))  # not enough said yet
            c.heard("b", "with the likelihood and a prior").result()
            self.assertIn("update our beliefs with the likelihood", c.ollama.heard_prompt)
            self.assertEqual(c.graph.topics_of("b"), ["bayes theorem", "statistics", "probability theory"])  # each once
            self.assertEqual(dict(c.graph.stats()["top"])["bayes theorem"], 1)
            n = c.ollama.calls
            c.heard("b", "more and more words, and many more of them")
            self.assertEqual(c.ollama.calls, n)  # once per video
            self.assertIn("b", InternetCulture({}, store).retagged)  # kept
            store.db.close()


class TestMapLayout(unittest.TestCase):
    def test_theme_shares(self):
        from hull.mapview import theme_share
        self.assertEqual(theme_share(["focus", "focus", None, "block"], focused=False), (0.5, 0.25))
        self.assertEqual(theme_share(["focus", None, None, "ask"], focused=True), (0.25, 0.5))  # outside a focus: hidden

    def test_colour_field_blends_by_distance(self):
        from hull.mapview import colour_field, rgb, BLUE, RED, PAPER
        xy = np.array([[0.0, 0.0], [100.0, 0.0]])
        px = colour_field(xy, [1.0, -1.0], [1.0, 1.0], (-200, -50, 500, 100), (50, 10), 20)[0].astype(float)[..., :3]
        at = lambda x: px[5, int((x + 200) / 10)]
        near = lambda c, x: np.linalg.norm(at(x) - rgb(c))
        self.assertLess(near(BLUE, 0), near(RED, 0))  # blue by the shown topic
        self.assertLess(near(RED, 100), near(BLUE, 100))  # red by the hidden one
        self.assertLess(near(PAPER, 290), 3)  # paper far from both
        mid = at(50)
        self.assertTrue(near(PAPER, 50) > 3 and abs(mid[0] - mid[2]) < abs(at(0)[0] - at(0)[2]))  # in between: a blend

    def test_border_merges_close_topics(self):
        from hull.mapview import colour_field, contour
        box = (-150, -100, 400, 200)
        _, apart = colour_field(np.array([[0.0, 0.0], [100.0, 0.0]]), [0, 0], [1, 1], box, (200, 100), 12)
        _, close = colour_field(np.array([[0.0, 0.0], [30.0, 0.0]]), [0, 0], [1, 1], box, (200, 100), 12)
        mid = lambda g, x: g[50, int((x + 150) / 2)]  # the glow halfway between the two
        self.assertLess(mid(apart, 50), 0.22)  # far apart: a gap between two shapes
        self.assertGreater(mid(close, 15), 0.22)  # close: one shape round both
        r = [abs(complex(x1, y1)) for (x1, y1), _ in contour(apart, 0.22, box) if x1 < 50]
        self.assertAlmostEqual(np.mean(r), 12 * math.sqrt(2 * math.log(1 / 0.22)), delta=3)  # a circle where the glow is 0.22

    def test_communities_split_where_links_thin(self):
        from hull.mapview import communities
        # two tight groups of four, joined by one thin link
        edges = [(a, b, 3) for g in ((0, 1, 2, 3), (4, 5, 6, 7)) for a in g for b in g if a < b] + [(3, 4, 1)]
        g = communities(8, edges, [3] * 8)
        self.assertEqual(len({g[i] for i in range(4)}), 1)
        self.assertEqual(len({g[i] for i in range(4, 8)}), 1)
        self.assertNotEqual(g[0], g[4])

    def test_linked_topics_end_up_closer(self):
        from hull.mapview import layout
        start = np.random.default_rng(1).normal(0, 0.5, (6, 2))
        pos = layout(start, [(0, 1, 5), (1, 2, 5), (3, 4, 5)])
        d = lambda i, j: np.linalg.norm(pos[i] - pos[j])
        self.assertLess(d(0, 1), d(0, 4))
        self.assertLess(d(3, 4), d(3, 1))


if __name__ == "__main__":
    unittest.main()
