# Hull

Hull is the ship under [Rudder](https://github.com/Hassleware/rudder): the heavy, local compute that decides what YouTube shows you.

Rudder, a Firefox extension, reads every recommendation before it's shown and runs it through a pipeline of stages. Hull plugs its own stages into that pipeline through Rudder's local API, so algorithms too big for a browser extension (local models, the GPU, anything Python can run) decide what you see. Hull also records every video Rudder sees, building the data that better algorithms learn from.

```
YouTube ─▶ Rudder (Firefox) ─▶ Rudder's bridge (127.0.0.1:7833) ◀─▶ Hull: your stages, your data
```

## Run it

1. Start Rudder's bridge (from the Rudder repo): `cd bridge`, then `python bridge.py`.
2. Open Firefox with Rudder.
3. Start Hull from this folder:

   ```
   pip install -e .
   python -m hull
   ```

Hull joins Rudder's pipeline right after Rudder's `keywords` stage and shows a **Hull** panel in Rudder's popup. Stop it with Ctrl-C: it takes its stages back out, so YouTube works normally without it. If Hull crashes instead, Rudder hides what Hull would have checked, because Rudder is strict.

`python -m hull stats` shows what Hull has recorded.

## Configure it

Everything is in `hull.toml`: where Rudder is, where Hull's stages go in Rudder's pipeline, where data is kept, and the stages themselves. Each `[[stage]]` becomes one stage in Rudder's pipeline. Editing a stage's config makes Rudder judge every video again.

## Stages

| Kind | Does |
|---|---|
| `rules` | Your own regular expressions over the title, channel, description and thumbnail text. The first rule that matches hides, shows or passes the video |

A stage is a small Python class in `hull/stages/`: it takes its config, and `decide(videos)` returns one result (hide, show or pass, with a reason) per video. Stages run in a worker thread, so slow ones don't hold anything else up. If a stage fails, its videos are hidden.

## Data

Hull keeps everything it sees in `data/`:

- `hull.db` (SQLite) has three tables:
  - `videos`: every video's record (title, channel, description, publish time, duration, where it was seen, and fields from Rudder's stages such as thumbnail text);
  - `outcomes`: what Rudder's pipeline decided each time;
  - `stage_results`: what each Hull stage said, and how long it took.
- `thumbs/`: every thumbnail Rudder read.

## Develop

```
python -m unittest                                   # tests; a fake Rudder stands in, no Firefox needed
python scripts/sync_proto.py <path to Rudder repo>   # after Rudder's API changes
```

Rudder's API contract is copied into `hull/rudder/` with its generated stubs; don't edit those by hand.
