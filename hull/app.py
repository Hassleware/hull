"""Hull's desktop app (Qt): whether Hull is steering Rudder, two switches (Hull steers / Rudder filters), your goal, and
your culture map. Hull itself (hull/link.py) runs on a thread of its own; the window only shows and switches it.
Closing the window keeps Hull going in the system tray; Quit there takes Hull's stages out of Rudder and stops.

Styled like Rudder's popup: paper, ink, square 2px borders, monospace, uppercase headings, Rudder blue."""
import asyncio, logging, sys, threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from hull.link import Hull

ASSETS = Path(__file__).parent / "assets"
PAPER, INK, FAINT, BLUE, RED = "#f2ede1", "#111111", "#d9d2c1", "#5BB8F0", "#E5484D"
STYLE = f"""
* {{ font-family: "Cascadia Mono", Consolas, "SF Mono", Menlo, monospace; font-size: 12px; color: {INK}; }}
QMainWindow, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {PAPER}; }}
QLabel {{ background: transparent; }}
QLabel[role="h2"] {{ font-weight: 700; letter-spacing: 1px; margin-top: 10px; }}
QLabel[role="lbl"] {{ font-size: 10px; letter-spacing: 1px; }}
QLabel[role="num"] {{ font-size: 20px; font-weight: 700; }}
QFrame[box="true"] {{ border: 2px solid {INK}; background: {PAPER}; }}
QFrame[cell="true"] {{ border: 0; border-right: 2px solid {INK}; }}
QPushButton {{ border: 2px solid {INK}; background: {PAPER}; font-weight: 700; padding: 4px 12px; }}
QPushButton:hover {{ background: {INK}; color: {PAPER}; }}
QPushButton:checked {{ background: {INK}; color: {PAPER}; }}
QPushButton:disabled {{ color: #9a958a; border-color: #9a958a; }}
QLineEdit, QPlainTextEdit, QListWidget {{ border: 2px solid {INK}; background: {PAPER}; padding: 4px; selection-background-color: {INK}; selection-color: {PAPER}; }}
QLineEdit:focus, QPlainTextEdit:focus {{ background: #ffffff; }}
QSlider::groove:horizontal {{ height: 2px; background: {INK}; }}
QSlider::handle:horizontal {{ width: 10px; margin: -7px 0; background: {INK}; }}
QToolTip {{ background: {PAPER}; color: {INK}; border: 2px solid {INK}; }}
"""
log = logging.getLogger("hull")


def label(text, role=None):
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(role not in ("num", "lbl"))
    return w


def box():
    f = QFrame()
    f.setProperty("box", True)
    return f


class Engine(QObject):
    """Hull on its own thread, reporting its status to the window as a Qt signal (delivered on the window's thread)"""
    status = Signal(dict)

    def __init__(self, hull):
        super().__init__()
        self.hull, self.task = hull, None
        hull.listeners.append(self.status.emit)
        self.thread = threading.Thread(target=self._run, name="hull", daemon=True)

    def _run(self):
        async def main():
            self.task = asyncio.current_task()
            await self.hull.main()
        try:
            asyncio.run(main())
        except asyncio.CancelledError:
            pass

    def start(self):
        self.thread.start()

    def stop(self):
        """take Hull's stages out of Rudder (hull.main's finally) and wait for it, at most 8 s"""
        if self.hull.loop and self.task:
            self.hull.loop.call_soon_threadsafe(self.task.cancel)
        self.thread.join(8)


class Switch(QFrame):
    """Rudder's on/off switch: a label, then ON and OFF, the active one inked"""
    def __init__(self, text, on_change):
        super().__init__()
        self.setProperty("box", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.text = label(text)
        self.text.setStyleSheet("font-weight: 700; padding: 0 8px;")
        row.addWidget(self.text, 1)
        self.on, self.off = QPushButton("ON"), QPushButton("OFF")
        for b, value in ((self.on, True), (self.off, False)):
            b.setCheckable(True)
            b.setStyleSheet("border-width: 0 0 0 2px;")
            b.clicked.connect(lambda _=False, v=value: on_change(v))
            row.addWidget(b)

    def show_state(self, on, enabled=True):
        self.on.setChecked(bool(on))
        self.off.setChecked(not on)
        self.on.setEnabled(enabled)
        self.off.setEnabled(enabled)


class Banner(QLabel):
    """the one thing to read first: is Hull steering Rudder right now?"""
    def __init__(self):
        super().__init__()
        self.setWordWrap(True)
        self.setMinimumHeight(54)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def show_status(self, s):
        if not s["rudder"]:
            text, bg, fg = "RUDDER ISN'T RUNNING · start Rudder's bridge (bridge/bridge.py) and Firefox with Rudder", \
                "qlineargradient(x1:0,y1:0,x2:0.02,y2:0.02,spread:repeat,stop:0 #f2ede1,stop:0.7 #f2ede1,stop:0.71 #d9d2c1,stop:1 #d9d2c1)", INK
        elif not s["firefox"]:
            text, bg, fg = "FIREFOX ISN'T CONNECTED · open Firefox with Rudder", PAPER, INK
        elif s["steering"]:
            text, bg, fg = "HULL IS STEERING RUDDER · your goal and culture map decide what YouTube shows", BLUE, INK
        else:
            text, bg, fg = "HULL IS WATCHING, NOT STEERING · Rudder filters on its own", PAPER, INK
        if s.get("warming"):
            text += " · loading Gemma…"
        self.setText(text)
        self.setStyleSheet(f"background: {bg}; color: {fg}; border: 2px solid {INK}; padding: 8px 10px; font-weight: 700; letter-spacing: 1px;")


class Numbers(QFrame):
    """big numbers in a ruled grid, like the popup's"""
    def __init__(self, names):
        super().__init__()
        self.setProperty("box", True)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        self.nums = {}
        for i, name in enumerate(names):
            cell = QFrame()
            cell.setProperty("cell", i < len(names) - 1)
            v = QVBoxLayout(cell)
            v.setContentsMargins(8, 6, 8, 6)
            self.nums[name] = label("0", "num")
            v.addWidget(self.nums[name])
            v.addWidget(label(name.upper(), "lbl"))
            grid.addWidget(cell, 0, i)

    def set(self, name, value):
        self.nums[name].setText(str(value))


class Window(QMainWindow):
    def __init__(self, hull, engine, tray):
        super().__init__()
        self.hull, self.engine, self.tray = hull, engine, tray
        self.setWindowTitle("Hull")
        self.setWindowIcon(QIcon(str(ASSETS / "hull-icon.svg")))
        self.resize(1180, 760)
        page = QWidget()
        page.setObjectName("page")
        self.setCentralWidget(page)
        self.columns = QHBoxLayout(page)
        self.columns.setContentsMargins(16, 16, 16, 16)
        self.columns.setSpacing(16)

        side = QVBoxLayout()
        side.setSpacing(8)
        mark = QSvgWidget(str(ASSETS / "wordmark.svg"))
        mark.setFixedSize(300, 118)
        side.addWidget(mark)
        self.banner = Banner()
        side.addWidget(self.banner)
        self.steer = Switch("HULL STEERS RUDDER", hull.set_steering)
        self.filtering = Switch("RUDDER FILTERING", hull.set_filtering)
        side.addWidget(self.steer)
        side.addWidget(self.filtering)
        self.numbers = Numbers(["recorded", "shown", "hull hid"])
        side.addWidget(self.numbers)
        self.side = side
        side.addStretch(1)
        holder = QWidget()
        holder.setLayout(side)
        holder.setFixedWidth(360)
        self.columns.addWidget(holder)

        engine.status.connect(self.show_status)
        self.show_status(dict(hull.status))
        self.timer = QTimer(self, interval=2000, timeout=self.refresh)
        self.timer.start()
        self.refresh()
        self.told = False

    def show_status(self, s):
        self.banner.show_status(s)
        connected = s["rudder"] and s["firefox"]
        self.steer.show_state(s["steering"] if connected else self.hull.steering, connected)
        self.filtering.show_state(s["filtering"], connected)
        self.tray.setIcon(QIcon(str(ASSETS / ("hull-icon.svg" if s["steering"] else "hull-icon-off.svg"))))
        self.tray.setToolTip("Hull: steering Rudder" if s["steering"] else "Hull: not steering")
        if hasattr(self, "steer_action"):  # the tray menu's switch
            self.steer_action.setChecked(self.hull.steering)

    def refresh(self):
        s = self.hull.store.stats()
        self.numbers.set("recorded", s["videos"])
        self.numbers.set("shown", s["shown"])
        self.numbers.set("hull hid", sum(s["hid_by_stage"].values()))

    def closeEvent(self, e):  # keep steering from the tray
        e.ignore()
        self.hide()
        if not self.told:
            self.told = True
            self.tray.showMessage("Hull", "Hull keeps steering from the tray. Quit there to stop it.", QIcon(str(ASSETS / "hull-icon.svg")), 4000)


def run(cfg, store, settings):
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("Hull")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    hull = Hull(cfg, store, settings)
    engine = Engine(hull)
    tray = QSystemTrayIcon(QIcon(str(ASSETS / "hull-icon-off.svg")))
    window = Window(hull, engine, tray)

    menu = QMenu()
    menu.addAction("Open Hull", lambda: (window.showNormal(), window.raise_(), window.activateWindow()))
    steer = QAction("Hull steers Rudder", menu, checkable=True, checked=hull.steering)
    steer.toggled.connect(lambda on: on != hull.steering and hull.set_steering(on))
    window.steer_action = steer
    menu.addAction(steer)
    menu.addSeparator()
    menu.addAction("Quit Hull", app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and (window.showNormal(), window.activateWindow()))
    tray.show()

    app.aboutToQuit.connect(engine.stop)
    engine.start()
    window.show()
    return app.exec()
