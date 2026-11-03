"""python -m hull [app | run | stats | leave] [--config hull.toml]; Hull.exe the same (scripts/build_exe.py)"""
import argparse, asyncio, json, logging, shutil, sys
from pathlib import Path

from hull.config import load
from hull.link import Hull
from hull.settings import Settings
from hull.store import Store


def main():
    ap = argparse.ArgumentParser(prog="hull", description="Hull: local algorithms for Rudder's pipeline.")
    ap.add_argument("command", nargs="?", default="app", choices=["app", "run", "stats", "leave"],
                    help="app: the desktop app (default); run: Hull without a window; stats: what Hull has recorded; "
                         "leave: take Hull's stages out of Rudder's pipeline (after a crash, Rudder hides what they'd check)")
    frozen = getattr(sys, "frozen", False)  # Hull.exe: its settings and data live next to it
    home = Path(sys.executable).parent if frozen else Path.cwd()
    ap.add_argument("--config", default=str(home / "hull.toml"))
    ap.add_argument("--tray", action="store_true", help="start in the tray, no window (how Windows starts Hull at login)")
    args = ap.parse_args()
    if frozen and not Path(args.config).exists():  # first run: the default settings, to edit
        shutil.copy(Path(sys._MEIPASS) / "hull.toml", args.config)
    cfg = load(args.config)
    log = {"filename": str(Path(cfg["data"]["folder"]) / "hull.log")} if frozen else {}  # no console for an exe's window
    if log:
        Path(cfg["data"]["folder"]).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", **log)
    if args.command == "leave":
        asyncio.run(Hull(dict(cfg, stage=[]), None).leave())
        return
    store = Store(cfg["data"]["folder"])
    if args.command == "stats":
        print(json.dumps(store.stats(), indent=2, ensure_ascii=False))
        return
    if args.command == "app":
        from hull.app import run  # Qt only loads for the app
        raise SystemExit(run(cfg, store, Settings(cfg["data"]["folder"]), tray=args.tray, config=args.config))
    try:
        asyncio.run(Hull(cfg, store, Settings(cfg["data"]["folder"])).main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
