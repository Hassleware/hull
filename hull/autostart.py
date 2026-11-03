"""Start with Windows: Hull in your user's startup list (HKCU\\...\\Run, no admin needed), opening quietly in the tray
at login. Hull then starts Ollama and Rudder's bridge itself if they aren't running."""
import sys
from pathlib import Path

KEY, NAME = r"Software\Microsoft\Windows\CurrentVersion\Run", "Hull"


def command(config):
    """how Windows should start Hull: Hull.exe, or Python without a console (pythonw) for a source install"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else sys.executable}" -m hull --tray --config "{Path(config).resolve()}"'


def is_on():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            winreg.QueryValueEx(k, NAME)
            return True
    except OSError:
        return False


def set_on(on, config):
    if sys.platform != "win32":
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, command(config))
        else:
            try:
                winreg.DeleteValue(k, NAME)
            except OSError:
                pass
