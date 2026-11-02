"""python -m hull [run | stats] [--config hull.toml]"""
import argparse, asyncio, json, logging

from hull.config import load
from hull.link import Hull
from hull.store import Store


def main():
    ap = argparse.ArgumentParser(prog="hull", description="Hull: local algorithms for Rudder's pipeline.")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "stats"],
                    help="run: join Rudder and serve Hull's stages (default); stats: what Hull has recorded")
    ap.add_argument("--config", default="hull.toml")
    args = ap.parse_args()
    cfg = load(args.config)
    store = Store(cfg["data"]["folder"])
    if args.command == "stats":
        print(json.dumps(store.stats(), indent=2, ensure_ascii=False))
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        asyncio.run(Hull(cfg, store).main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
