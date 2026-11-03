"""Uninstalling Hull cleanly: out of Rudder (its stages and panel), out of Windows startup, and, if you say so, your
data (the internet culture map, thumbnails, settings, goals). Hull.exe also deletes itself once it has closed. Ollama
and its models stay: other programs may use them.

The app does this from its tray menu (Uninstall Hull…); `Hull.exe uninstall [--delete-data]` or
`python -m hull uninstall [--delete-data]` does it without the window."""
import logging, shutil, subprocess, sys
from pathlib import Path

from hull import autostart


def remove(config, data_folder, delete_data):
    """everything but leaving Rudder (Hull.leave does that) and the exe itself (delete_exe_later)"""
    autostart.set_on(False, config)
    if delete_data:
        logging.shutdown()  # Hull.exe logs into the data folder: close the log, or Windows won't delete it
        shutil.rmtree(data_folder, ignore_errors=True)
        if getattr(sys, "frozen", False):
            Path(config).unlink(missing_ok=True)  # Hull.exe's own settings, written on its first run


def delete_exe_later(data_folder=None):
    """Hull.exe can't delete itself while it runs: a hidden command waits a few seconds, then deletes it (and what's
    left of the data folder, if that's being deleted: anything Hull still had open)"""
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        rest = f' & rmdir /s /q "{data_folder}"' if data_folder else ""
        subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 4 > nul & del /f /q "{sys.executable}"{rest}',
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW, close_fds=True)
        return True
    return False
