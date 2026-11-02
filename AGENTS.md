# Hull: guide for agents

Hull is a Python program that runs its own stages inside Rudder's filtering pipeline, through Rudder's local gRPC API (127.0.0.1:7833, served by Rudder's bridge). Rudder is a separate project: a Firefox extension that filters YouTube recommendations before they're shown. Read `README.md` first.

## Map

| Path | What |
|---|---|
| `hull/__main__.py` | `python -m hull [run | stats] [--config hull.toml]` |
| `hull/link.py` | The link to Rudder: joins and leaves the pipeline, serves stage requests, records videos, draws the popup panel, reconnects |
| `hull/stages/` | Stage kinds; `KINDS` in `__init__.py` lists them |
| `hull/video.py` | `Video` (Rudder's video record as a dataclass) and `Result` (hide / show / pass, why, fields) |
| `hull/store.py` | SQLite (`data/hull.db`) and thumbnails (`data/thumbs/`) |
| `hull/config.py`, `hull.toml` | Settings |
| `hull/rudder/` | Rudder's `rudder.proto` and generated stubs: never edit by hand; `scripts/sync_proto.py` refreshes them |
| `tests/test_hull.py` | Tests, with a fake Rudder (an in-process gRPC server) |

## Adding a stage

1. Write a class in `hull/stages/<name>.py` with `__init__(self, config)`, `decide(self, videos) -> list[Result]` (one per video, in order) and `describe(self) -> str`.
2. Add it to `KINDS` in `hull/stages/__init__.py`.
3. Add a `[[stage]]` for it in `hull.toml`.
4. Add a test to `tests/`.

`decide` runs in a worker thread and may be slow (models, the GPU). It must return exactly one `Result` per video; an exception hides the whole batch.

## Commands

```
python -m hull                 # run (needs Rudder's bridge and Firefox with Rudder)
python -m hull stats           # what's recorded
python -m unittest             # tests, no Firefox needed
```

## Rules

- **Strict, like Rudder.** Anything that fails or can't answer hides. Never add a path that passes or shows a video because something went wrong.
- **Leave cleanly.** On exit Hull removes its stages from Rudder's pipeline; keep that working.
- **Rudder's API is the contract.** Talk to Rudder only through it. When Rudder's `rudder.proto` changes, run `scripts/sync_proto.py` rather than editing `hull/rudder/`.
- **No requests to YouTube.** Use what Rudder sends; Hull doesn't fetch from YouTube either.
- **The GPU is allowed**, but ask the user before running anything on it during development: they may be gaming.
- **Comments:** short and plain, saying why.
