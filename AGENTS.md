# Hull: guide for agents

Hull is a Python desktop app (Qt) that runs its own stages inside Rudder's filtering pipeline, through Rudder's local gRPC API (127.0.0.1:7833, served by Rudder's bridge). Rudder is a separate project: a Firefox extension that filters YouTube recommendations before they're shown. Hull's stages:
- block repeats (a Bloom filter plus LSH);
- run Gemma in Ollama to tag videos into a culture graph;
- hide by `block` and `focus` topics through that graph.

Read `README.md` (what Hull is) and `docs/how-it-works.md` (how) first.

## Map

| Path | What |
|---|---|
| `hull/__main__.py` | `python -m hull [app \| run \| stats \| leave] [--config hull.toml]` (default: app) |
| `hull/app.py` | The desktop app (Qt, PySide6): banner, switches, goal box, topic details, tray. Rudder's popup styling |
| `hull/mapview.py` | The culture map: force layout over the graph, pins coloured by the goal, growth slider data |
| `hull/settings.py` | `data/settings.json`: steering on/off and the goal |
| `hull/assets/` | Logo, icons (`make` them as SVG; the tray uses `hull-icon.svg` / `hull-icon-off.svg`) |
| `hull/link.py` | The link to Rudder: warms models, joins and leaves the pipeline (`remember: false`), serves stage requests, records videos (WatchVideos) and what's shown (WatchShown), draws the popup panel, reconnects; thread-safe `set_steering`, `set_filtering`, `set_goal` for the app |
| `hull/stages/` | Stage kinds; `KINDS` in `__init__.py` lists them, and the interface |
| `hull/stages/repeats.py` | Shown once, never again: Bloom filter of ids plus near-duplicate titles and thumbnails |
| `hull/stages/culture.py` | Gemma tags videos into the graph; block, focus, and Gemma's in-between judgements |
| `hull/stages/rules.py` | Regular expressions |
| `hull/graph.py` | The culture graph: topics, merging, neighbours, relatedness |
| `hull/bloom.py`, `hull/lsh.py` | Bloom filter; MinHash and dHash LSH |
| `hull/ollama.py` | Ollama's HTTP API (standard library) |
| `hull/video.py` | `Video` (Rudder's video record) and `Result` (hide / show / pass, why, fields) |
| `hull/store.py` | SQLite (`data/hull.db`) and thumbnails (`data/thumbs/`) |
| `hull/config.py`, `hull.toml` | Settings |
| `hull/rudder/` | Rudder's `rudder.proto` and generated stubs: never edit by hand; `scripts/sync_proto.py` refreshes them |
| `tests/test_hull.py` | Tests, with a fake Rudder (an in-process gRPC server) and a fake Ollama |

## Adding a stage

1. Write a class in `hull/stages/<name>.py` with `__init__(self, config, store)`, `decide(self, videos) -> list[Result]` (one per video, in order) and `describe(self) -> str`. Optional: `shown(ids)`, `warm()`, `panel()`.
2. Add it to `KINDS` in `hull/stages/__init__.py`.
3. Add a `[[stage]]` for it in `hull.toml`.
4. Add a test to `tests/`.

`decide` runs in a worker thread and must answer within Rudder's 25 s (the culture stage keeps to an 18 s budget). It must return exactly one `Result` per video, and an exception hides the whole batch. Rudder asks again on every sighting, so cache your own per-video work, as the culture stage does in the graph.

## Commands

```
python -m hull                 # the app (needs Rudder's bridge, Firefox with Rudder, and Ollama with gemma4:e4b and embeddinggemma)
python -m hull run             # the same, without a window
python -m hull stats           # what's recorded
python -m hull leave           # take Hull's stages out of Rudder's pipeline
python -m unittest             # tests, no Firefox or Ollama needed
```

## Rules

- **Strict, like Rudder.** Anything that fails, can't answer in time or isn't tagged yet hides. Never add a path that passes or shows a video because something went wrong.
- **Leave cleanly.** On exit Hull removes its stages from Rudder's pipeline; keep that working.
- **Always say whether Hull is steering.** The app's banner and tray icon, and the panel in Rudder's popup, follow Rudder's real pipeline (`status["steering"]`), not what was asked for.
- **Look like Rudder.** Paper `#f2ede1`, ink `#111`, Rudder blue `#5BB8F0`, red `#E5484D`, square 2px borders, monospace, uppercase headings.
- **The app never blocks on Gemma or Rudder.** Anything that calls Ollama or the API runs off the window's thread.
- **Rudder's API is the contract.** Talk to Rudder only through it. When Rudder's `rudder.proto` changes, run `scripts/sync_proto.py` rather than editing `hull/rudder/`.
- **No requests to YouTube.** Use what Rudder sends; Hull doesn't fetch from YouTube either.
- **The GPU is allowed** (Gemma in Ollama), but ask the user before running anything on it during development: they may be gaming.
- **Comments:** short and plain, saying why. A deliberate shortcut gets a `ponytail:` comment naming its limit.
