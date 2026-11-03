# How Hull works

The technical guide. For what Hull is, see the [README](../README.md).

Hull is the ship under [Rudder](https://github.com/Hassleware/rudder): the heavy, local compute that decides what YouTube shows you.

Rudder, a Firefox extension, reads every recommendation before it's shown and runs it through a pipeline of stages. Hull plugs its own stages into that pipeline through Rudder's local API. Then Gemma, running on your own GPU, builds a map of the internet culture you're exposed to and decides what you see from it:

- **No repeats.** A video Rudder has put on screen once never comes back, and neither does a re-upload of it.
- **An internet culture graph.** Gemma names every video's topics, from its exact subject up to its field. Topics become nodes, and topics that share videos get linked.
- **Block and focus by meaning.** `block = ["grand theft auto"]` also hides Los Santos and Michael De Santa. `focus = ["bayesian statistics"]` turns YouTube into a study feed: only videos near that topic in the graph get through. Gemma settles the borderline cases using the graph.

```
YouTube ─▶ Rudder (Firefox) ─▶ Rudder's bridge (127.0.0.1:7833) ◀─▶ Hull ─▶ Ollama (Gemma, on your GPU)
                                                                      └──▶ data/: hull.db, shown.bloom, thumbs/
```

## Run it

You need:
- **Rudder**, with its bridge: from the Rudder repo, `cd bridge`, then `python bridge.py`. Open Firefox with Rudder.
- **[Ollama](https://ollama.com)** with the two models:

  ```
  ollama pull gemma4:e4b
  ollama pull embeddinggemma
  ```

  Gemma takes about 10 GB of graphics memory while loaded. Ollama unloads it after 30 minutes idle.

Then start Hull from this folder:

```
pip install -e .
python -m hull
```

Hull opens its window, loads the models, joins Rudder's pipeline right after Rudder's `your-clicks` stage (so only your own ratings come before it, and Rudder's keywords after), and shows a **Hull** panel in Rudder's popup.

Hull checks every video Rudder filters (the home page, the sidebar beside a video, search results, channel pages, Shorts) before it's shown. It also maps every video Rudder reports, whichever stage decided it, and every video you like or dislike, watched or not (`WatchFeedback`): Gemma tags it in the background, so your map holds all of it.

## The app

- **The banner** says what Hull is doing, first thing:
  - blue, *Hull is steering Rudder*: Hull's stages are in Rudder's pipeline;
  - paper, *Hull is watching*: Rudder filters on its own, and Hull keeps recording;
  - striped, *Rudder isn't running*: start Rudder's bridge and Firefox.
- **Two switches.**
  - *Hull steers Rudder* puts Hull's stages into Rudder's pipeline or takes them out.
  - *Rudder filtering* is Rudder's own on/off switch, the same as in Rudder's popup.

  Neither moves anything already on the YouTube page: the change applies to the videos not shown yet.
- **Your goals.** As many as you like, all at once, one row each with *Edit* and ×. Write what you want YouTube for and *Draft with Gemma*: a window opens with the goal's topics, *for* (show only what's near) and *against* (never show what's near), to remove or add before *Apply*. Goals add up; when two disagree about a topic, that's fine, and against wins for it. They're kept in `data/settings.json` and replace the internet culture stage's `focus` and `block` from `hull.toml`. The sidebar never scrolls: the title stays on top.
- **Your internet culture map.**
  - Every topic is a pin, sized by how many videos you've seen on it, and topics that share videos are joined by lines.
  - Pins sit by meaning and by neighbours, so your internet culture forms clusters.
  - One border runs round your whole map, traced where the topics' combined glow reaches a level (`LEVEL` in `hull/mapview.py`), so themes that come close flow into one smooth shape and lone ones stay islands. Inside it, a colour field: every topic glows blue if your goal shows it, red if it hides it, beige if neither, bigger topics further, and each point leans blue or red by the balance of the glows around it, beige where they're even. Where a new video lands, the colour under it is its neighbours' consensus: it will most likely go the same way.
  - Themes (communities found with Louvain: music, gaming, cooking…) carry one name while small on screen; hover a theme for how much of it is shown and hidden. Zoomed out, each theme shows one name, its most-seen topic and how many topics it holds, and the lines between two themes become one thick line. Zoom in and a theme opens: its topics' names and every line come back.
  - A name is drawn only where it has room: the most-seen go first, and a name that would touch another waits until you zoom in. Every dot is always drawn, and hovering one shows its name.
  - Blue is near your focus, red near what you block, and dashed where Gemma still decides.
  - Wheel to zoom, drag to move, hover a pin for its name and how often you've seen it, click one to mark it.
  - The *growth* slider replays how the map grew: topics, lines and themes appear in place as they were first seen, light while you drag and in full detail once you stop.
- **The tray.** Closing the window keeps Hull steering from the tray: a blue hull while it steers, grey when it doesn't. Quit there takes Hull's stages out of Rudder.
- **In Rudder's popup.** Hull's panel shows whether it's steering, your goal, and its numbers. If Hull stops without cleaning up, Rudder's pipeline marks Hull's stages as "hull not running", striped while they hide what they'd check.

If Hull crashes, Rudder hides what Hull would have checked (Rudder is strict) until you start Hull again or run `python -m hull leave`.

| Command | Does |
|---|---|
| `python -m hull` | Opens the app |
| `python -m hull run` | Runs Hull without a window |
| `python -m hull stats` | Shows what Hull has recorded |
| `python -m hull leave` | Takes Hull's stages out of Rudder's pipeline |

## Configure it

Everything is in `hull.toml`. Each `[[stage]]` becomes one stage in Rudder's pipeline, in this order:

| Kind | Does |
|---|---|
| `repeats` | Hides any video Rudder has put on screen before: by its id (a Bloom filter), or as a copy of a shown one (same title or thumbnail, found by LSH) |
| `rules` | Your own regular expressions over the title, channel, description and thumbnail text. The first rule that matches decides |
| `internet-culture` | Has Gemma tag the video into your internet culture graph, then hides by `block` and `focus` |

A learning harness, for example:

```toml
[[stage]]
id = "internet-culture"
kind = "internet-culture"
[stage.config]
focus = ["bayesian statistics"]   # only videos near this in the internet culture graph
block = ["grand theft auto"]      # never this, or anything near it
```

Editing a stage's config, or applying a goal, makes Rudder judge again the videos not on screen yet.

## How it decides

**Repeats.** Rudder reports every video it puts on screen (`WatchShown`). Hull adds each id to a Bloom filter: about 1.8 MB holds a million videos, with a 0.1% chance of calling a new video a repeat. That is the strict side to err on. The filter can't catch a re-upload under a new id, so shown videos' titles and thumbnails also go into two locality-sensitive hash indexes:
- **Titles:** MinHash over the title's words. A copy shares at least 80% of its words, so "ep 12" and "ep 13" are different videos.
- **Thumbnails:** a 256-bit dHash. A copy differs by at most 12 bits, which survives resizing and recompression; a new face on the same template counts as a different thumbnail.

Hull's stages ask Rudder to ask again every time YouTube sends a video (`remember: false`). Without that, Rudder would reuse Hull's first answer forever and a repeat would never be caught.

**Internet culture graph.** For each new video, Gemma (`gemma4:e4b`) sees:
- the title, channel, description and thumbnail;
- the text Rudder read from the thumbnail;
- the known topics nearest to the video, so it reuses their names.

It names 3 to 6 topics, from the subject up to the field. For example, "I spent 100 days in Los Santos" becomes *los santos → grand theft auto v → video games*. Every name is embedded with `embeddinggemma`, and names within 0.94 cosine of a known topic merge into it ("gta" is "grand theft auto"). A video is tagged once. A batch of 12 takes about 4 seconds, well inside Rudder's 25-second limit. Videos not tagged in time stay hidden and are asked about again the next time they come.

**What you watch.** Rudder asks YouTube's player for English captions on every video you watch and streams each line to Hull as you reach it (`WatchCaptions`). Hull keeps them (table `captions`). Once about 600 characters have been said, Gemma tags the video again from its title and what's said in it, and those topics join your map. A watched video is mapped by its content. Captions stay hidden on the video unless you press CC or C.

**Block and focus: areas of your map.** A goal covers an area of your internet culture map:
1. its topics, and near-synonyms of them (cosine ≥ `area_seed`, 0.85: "비디오 게임" for "video games");
2. then, one edge out (`focus_hops` / `block_hops`), each neighbour where at least half its videos (`focus_link` / `block_link`) are already in the area.

A topic that mostly lives around your goal joins it: around "video games", Roblox, Frostpunk and League of Legends join. A big separate subject that touched it once stays out: music only shares a game soundtrack, 1 of its 25 videos. A video with a topic in the block area is hidden. With a focus, a video with a topic in the focus area is shown.

*Draft with Gemma* drafts both sides of the goal and covers your whole map:
1. Gemma lists what the goal is for (the field, its kinds, examples, people and communities) and what it's against (what you don't want and what pulls you away from it).
2. Then every topic on your map gets a label, for, against or neither, in batches side by side (about a minute for a few hundred topics).
3. Your map's consensus checks Gemma: a topic labelled "for" stays only if it's clearly alike in meaning or sits in the area around clearly-wanted topics, and a topic labelled "against" that sits in that area is dropped unless you named it.

A video is then decided by its topics: the goal's own topics are fixed, then the areas around them; with both sides, the video's topics vote, the most specific counting most (a GTA trailer is a game video even if trailers are against the goal); with only things to avoid, any one of them hides it.

Topics outside every area (new ones without links yet) are judged by meaning. How near a video is to a topic is the best of its topics' relatedness to it. Relatedness is the larger of:
- how alike the two topics' meanings are;
- the same, through a neighbour: the share of this topic's videos that are also on a neighbour topic, times how alike that neighbour is.

So "pymc" becomes near "bayesian statistics" once most videos about pymc are Bayesian.

| | Hidden at or above | Gemma decides |
|---|---|---|
| `block` | `block_at` 0.85 | from `block_ask` 0.7 up to `block_at` |
| `focus` (hidden below) | below `focus_ask` 0.62 | from `focus_ask` up to `focus_at` 0.75 |

In the zone where Gemma decides, it is asked "is *pymc* part of *bayesian statistics*?". It gets the topic's neighbours and some videos about it as context. It answers once per pair, and the answer is kept.

## Data

Everything is in `data/`:

- `hull.db` (SQLite):

  | Table | Holds |
  |---|---|
  | `videos` | Every video's record: title, channel, description, published, duration, where it was seen, and fields from Rudder's stages such as thumbnail text |
  | `outcomes` | What Rudder's pipeline decided each time |
  | `stage_results` | What each Hull stage said, and how long it took |
  | `shown`, `shown_prints` | When videos were put on screen; shown titles and thumbnail hashes |
  | `topics`, `video_topics` | The internet culture graph: topics with their embeddings, and which videos attest to which |
  | `judgements` | Gemma's answers to "is X part of Y?" |
  | `ratings` | Your likes and dislikes |
  | `captions`, `watched` | What was said in the videos you watched, line by line; when each was tagged again from it |

- `shown.bloom`: the Bloom filter of shown ids.
- `settings.json`: whether Hull steers, and your goal.
- `thumbs/`: every thumbnail Rudder read.

## Develop

```
python -m unittest                                   # tests: a fake Rudder and a fake Ollama stand in
python scripts/sync_proto.py <path to Rudder repo>   # after Rudder's API changes
```

Rudder's API contract is copied into `hull/rudder/` with its generated stubs; don't edit those by hand. Hull needs a Rudder with `WatchShown` and `remember: false`.
