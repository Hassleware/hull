"""python -m hull [app | run | stats | leave] [--config hull.toml]"""
import argparse, asyncio, json, logging

from hull.config import load
from hull.link import Hull
from hull.settings import Settings
from hull.store import Store


def main():
    ap = argparse.ArgumentParser(prog="hull", description="Hull: local algorithms for Rudder's pipeline.")
    ap.add_argument("command", nargs="?", default="app", choices=["app", "run", "stats", "leave"],
                    help="app: the desktop app (default); run: Hull without a window; stats: what Hull has recorded; "
                         "leave: take Hull's stages out of Rudder's pipeline (after a crash, Rudder hides what they'd check)")
    ap.add_argument("--config", default="hull.toml")
    args = ap.parse_args()
    cfg = load(args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if args.command == "leave":
        asyncio.run(Hull(dict(cfg, stage=[]), None).leave())
        return
    store = Store(cfg["data"]["folder"])
    if args.command == "stats":
        print(json.dumps(store.stats(), indent=2, ensure_ascii=False))
        return
    if args.command == "app":
        from hull.app import run  # Qt only loads for the app
        raise SystemExit(run(cfg, store, Settings(cfg["data"]["folder"])))
    try:
        asyncio.run(Hull(cfg, store, Settings(cfg["data"]["folder"])).main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
