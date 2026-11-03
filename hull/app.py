"""Hull's desktop app (Qt): whether Hull is steering Rudder, two switches (Hull steers / Rudder filters), your goal, and
your internet culture map. Hull itself (hull/link.py) runs on a thread of its own; the window only shows and switches it.
Closing the window keeps Hull going in the system tray; Quit there takes Hull's stages out of Rudder and stops.

Styled like Rudder's popup: paper, ink, square 2px borders, monospace, uppercase headings, Rudder blue."""
import asyncio, bisect, copy, html, logging, sys, threading, time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFontMetrics, QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QMessageBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSystemTrayIcon, QVBoxLayout, QWidget)

from hull import autostart, uninstall
from hull.link import Hull
from hull.mapview import InternetCultureMap, theme_share

ASSETS = Path(__file__).parent / "assets"
PAPER, INK, FAINT, BLUE, RED = "#f2ede1", "#111111", "#d9d2c1", "#5BB8F0", "#E5484D"
STYLE = f"""
* {{ font-family: "Cascadia Mono", Consolas, "SF Mono", Menlo, monospace; font-size: 12px; color: {INK}; }}
QMainWindow, QDialog, QMessageBox, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {PAPER}; }}
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
QLineEdit {{ min-height: 20px; }}
QLineEdit:focus, QPlainTextEdit:focus {{ background: #ffffff; }}
QScrollArea {{ border: 0; }}
QScrollBar:vertical {{ width: 8px; background: {PAPER}; margin: 0; }}
QScrollBar::handle:vertical {{ background: {FAINT}; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSlider::groove:horizontal {{ height: 2px; background: {INK}; }}
QSlider::handle:horizontal {{ width: 10px; margin: -7px 0; background: {INK}; }}
QProgressBar {{ border: 2px solid {INK}; background: {PAPER}; }}
QProgressBar::chunk {{ background: {BLUE}; }}
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


class Banner(QFrame):
    """the one thing to read first: is Hull steering Rudder right now? While Rudder can't be reached (its bridge or
    Firefox), Rudder's own rudder shows beside the message"""
    def __init__(self):
        super().__init__()
        self.setObjectName("banner")
        self.setMinimumHeight(54)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        self.rudder = QSvgWidget(str(ASSETS / "rudder-icon.svg"))
        self.rudder.setFixedSize(30, 30)
        self.rudder.setToolTip("Rudder can't be reached")
        row.addWidget(self.rudder)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setStyleSheet("border: 0; background: transparent; font-weight: 700; letter-spacing: 1px;")
        row.addWidget(self.text, 1)

    def show_status(self, s):
        if not s["rudder"]:
            text, bg = "RUDDER ISN'T RUNNING · start Rudder's bridge (bridge/bridge.py) and Firefox with Rudder",                 "qlineargradient(x1:0,y1:0,x2:0.02,y2:0.02,spread:repeat,stop:0 #f2ede1,stop:0.7 #f2ede1,stop:0.71 #d9d2c1,stop:1 #d9d2c1)"
        elif not s["firefox"]:
            text, bg = "FIREFOX ISN'T CONNECTED · open Firefox with Rudder", PAPER
        elif s["steering"]:
            text, bg = "HULL IS STEERING RUDDER · your goal and internet culture map decide what YouTube shows", BLUE
        else:
            text, bg = "HULL IS WATCHING · Rudder filters on its own", PAPER
        if s.get("warming"):
            text += " · loading Gemma…"
        self.rudder.setVisible(not (s["rudder"] and s["firefox"]))
        self.text.setText(text)
        self.setStyleSheet(f"QFrame#banner {{ background: {bg}; border: 2px solid {INK}; }}")


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


class Chips(QWidget):
    """a list of topics as chips, each with ×, and a box to add one"""
    def __init__(self, title, changed=None):
        super().__init__()
        self.items, self.changed = [], changed
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(label(title, "lbl"))
        self.flow = QLabel()
        self.flow.setWordWrap(True)
        self.flow.setTextFormat(Qt.TextFormat.RichText)
        self.flow.linkActivated.connect(lambda t: self.set([x for x in self.items if x != t]))
        v.addWidget(self.flow)
        self.add = QLineEdit()
        self.add.setPlaceholderText("+ add a topic")
        self.add.returnPressed.connect(self._add)
        v.addWidget(self.add)

    def _add(self):
        t = self.add.text().strip().lower()
        self.add.clear()
        if t and t not in self.items:
            self.set(self.items + [t])

    def set(self, items, quiet=False):
        self.items = list(items)
        if self.changed and not quiet:
            self.changed()
        self.flow.setText(" ".join(f'<span style="border:2px solid {INK}">&nbsp;{html.escape(t)} <a href="{html.escape(t)}" style="color:{INK};text-decoration:none"><b>×</b></a>&nbsp;</span>'
                                   for t in self.items) or "—")


class GoalWindow(QDialog):
    """one goal, shown as what it does: your map coloured as if only this goal were on (blue shown, red hidden). Click
    a topic to change it: for, against, neither. The topic lists are there too, folded away"""
    embedded = Signal()

    def __init__(self, parent, goal, note="", stage=None, positions=None):
        super().__init__(parent)
        self.setWindowTitle("Hull · goal")
        self.resize(980, 780) if stage else self.resize(560, 680)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)
        v.addWidget(label("GOAL", "h2"))
        self.text = QPlainTextEdit(goal.get("text", ""))
        self.text.setFixedHeight(52)
        v.addWidget(self.text)
        if note:
            v.addWidget(label(note, "lbl"))
        self.focus = Chips("FOR · SHOW ONLY WHAT'S NEAR (empty: everything)", self.recolour)
        self.block = Chips("AGAINST · NEVER SHOW WHAT'S NEAR", self.recolour)
        self.focus.set(goal.get("focus", []), quiet=True)
        self.block.set(goal.get("block", []), quiet=True)
        self.preview = None
        if stage and stage.graph.names:
            # a copy of the stage holding only this goal: it shares the map and what's known, the real goals don't change
            self.preview = copy.copy(stage)
            self.map = InternetCultureMap()
            self.map.positions = dict(positions or {})  # where your main map has each topic
            self.map.picked.connect(self.cycle)
            v.addWidget(self.map, 1)
            self.summary = label("", "lbl")
            v.addWidget(self.summary)
            self.embedded.connect(self.recolour)
            self.recolour()
            threading.Thread(target=self.embed, daemon=True).start()
        topics = QWidget()
        t = QVBoxLayout(topics)
        t.setContentsMargins(0, 0, 8, 0)
        t.addWidget(self.focus)
        t.addWidget(self.block)
        t.addStretch(1)
        scroll = QScrollArea()  # a big draft is hundreds of topics: this window scrolls, the sidebar never does
        scroll.setWidget(topics)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        v.addWidget(scroll, 1)
        row = QHBoxLayout()
        ok, cancel = QPushButton("APPLY"), QPushButton("CANCEL")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        row.addStretch(1)
        if self.preview:  # the map says it; the lists are for looking closer
            scroll.hide()
            lists = QPushButton("SHOW TOPICS")
            lists.clicked.connect(lambda: (scroll.setVisible(not scroll.isVisible()), self.map.setVisible(not scroll.isVisible()),
                                           lists.setText("SHOW MAP" if scroll.isVisible() else "SHOW TOPICS")))
            row.addWidget(lists)
        v.addLayout(row)

    def embed(self):
        """the goal's topics as vectors, for its colours: map topics already have theirs; others need embeddinggemma"""
        g, p = self.preview.graph, self.preview
        for t in self.focus.items + self.block.items:
            if t in g.index:
                p.anchor_vecs.setdefault(t, g.vecs[g.index[t]])
        try:
            p.anchors(self.focus.items + self.block.items)
        except Exception as e:
            log.warning("couldn't embed the goal's topics: %s", e)
        self.embedded.emit()

    def recolour(self):
        if not self.preview:
            return
        self.preview.set_goal(self.focus.items, self.block.items)
        g = self.preview.graph
        for t in self.focus.items + self.block.items:  # a clicked map topic has its vector already
            if t in g.index:
                self.preview.anchor_vecs.setdefault(t, g.vecs[g.index[t]])
        self.map.key = None
        self.map.draw(self.preview)
        marks = self.preview.marks(g.names)
        if marks is None:
            self.summary.setText("WORKING OUT WHAT THIS GOAL DOES…")
            return
        focused = bool(self.preview.focus)
        shown = sum(m == "focus" for m in marks.values())
        hidden = sum(m == "block" or (focused and m is None) for m in marks.values())
        self.summary.setText(f"AS THIS GOAL SEES YOUR MAP: {shown} TOPICS SHOWN (BLUE), {hidden} HIDDEN (RED) OF {len(g.names)}"
                             f"{' · EVERYTHING AWAY FROM BLUE IS HIDDEN' if focused else ''}. CLICK A TOPIC: FOR → AGAINST → NEITHER.")

    def cycle(self, name, members):
        """a click on a topic: for → against → neither → for"""
        if not name:
            return
        if name in self.focus.items:
            self.focus.set([t for t in self.focus.items if t != name], quiet=True)
            self.block.set(self.block.items + [name], quiet=True)
        elif name in self.block.items:
            self.block.set([t for t in self.block.items if t != name], quiet=True)
        else:
            self.focus.set(self.focus.items + [name], quiet=True)
        self.recolour()

    def goal(self):
        return {"text": self.text.toPlainText().strip(), "focus": self.focus.items, "block": self.block.items}


class Focus(QFrame):
    """the panel a click on the map opens: telemetry for the theme (and the topic) under the pointer"""
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("focus")
        self.setFixedWidth(330)
        self.setStyleSheet(f"QFrame#focus {{ background: {PAPER}; border: 2px solid {INK}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 10)
        head = QHBoxLayout()
        self.title = label("", "h2")
        self.title.setStyleSheet("margin-top: 0; border: 0;")
        head.addWidget(self.title, 1)
        close = QPushButton("×")
        close.setFixedSize(24, 24)
        close.setStyleSheet("padding: 0;")
        close.clicked.connect(self.hide)
        head.addWidget(close)
        v.addLayout(head)
        self.body = QLabel()
        self.body.setStyleSheet("border: 0;")
        self.body.setFixedWidth(306)  # known width, so its wrapped height is measured right
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.body)
        self.hide()

    def show_text(self, title, body):
        self.title.setText(title)
        self.body.setText(body)
        self.body.setFixedHeight(self.body.heightForWidth(306))
        self.adjustSize()
        p = self.parentWidget()
        self.move(p.width() - self.width() - 10, 10)
        self.show()
        self.raise_()


class Goals(QFrame):
    """your goals, all at once: one row each (Edit, ×), and a box to draft a new one with Gemma"""
    drafted = Signal(object)
    progressed = Signal(dict)

    def __init__(self, hull, internet_culture, applied, positions=dict):
        super().__init__()
        self.hull, self.internet_culture, self.applied = hull, internet_culture, applied
        self.positions = positions  # where the main map has each topic, for the goal window's map
        self.goals = list(hull.goals)
        self.setProperty("box", True)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(4)
        v.addLayout(self.rows)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("A new goal: what do you want YouTube for?")
        self.text.setFixedHeight(46)
        v.addWidget(self.text)
        row = QHBoxLayout()
        self.draft = QPushButton("DRAFT WITH GEMMA")
        self.draft.clicked.connect(self.ask)
        row.addWidget(self.draft)
        row.addStretch(1)
        v.addLayout(row)
        self.bar = QProgressBar()  # the draft's progress, measured as it goes
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(12)
        self.bar.hide()
        v.addWidget(self.bar)
        self.note = label("", "lbl")
        v.addWidget(self.note)
        self.drafted.connect(self.show_draft)
        self.progressed.connect(self.show_progress)
        self.last = None  # the latest progress, and when it came: the bar runs on from it between reports
        self.ticker = QTimer(self, interval=100, timeout=self.tick)
        self.show_rows()

    def show_rows(self):
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not self.goals:
            self.rows.addWidget(label("No goals: Gemma maps your internet culture, Rudder filters as it does.", "lbl"))
        for i, g in enumerate(self.goals):
            line = QFrame()
            h = QHBoxLayout(line)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            what = label("", None)
            what.setWordWrap(False)
            name = QFontMetrics(what.font()).elidedText(g.get("text") or "(untitled)", Qt.TextElideMode.ElideRight, 150)
            what.setText(f"<b>{html.escape(name)}</b><br><span style='font-size:10px'>{len(g.get('focus', []))} FOR · {len(g.get('block', []))} AGAINST</span>")
            what.setToolTip(g.get("text", ""))
            h.addWidget(what, 1)
            edit, drop = QPushButton("EDIT"), QPushButton("×")
            edit.clicked.connect(lambda _=False, i=i: self.edit(i))
            drop.clicked.connect(lambda _=False, i=i: self.save([x for k, x in enumerate(self.goals) if k != i]))
            h.addWidget(edit)
            h.addWidget(drop)
            self.rows.addWidget(line)

    def ask(self):
        text = self.text.toPlainText().strip()
        if not text:
            return
        self.draft.setEnabled(False)
        self.bar.setValue(0)
        self.bar.show()
        self.note.setText("STARTING…")
        self.started, self.last, self.shown = time.monotonic(), None, 0.0
        self.ticker.start()

        def work():
            try:
                self.drafted.emit(self.internet_culture.draft_goal(text, progress=lambda **p: self.progressed.emit(p)))
            except Exception as e:  # Ollama not running, say
                self.drafted.emit(e)
        threading.Thread(target=work, daemon=True).start()

    def gemma(self, up):
        """drafting needs Gemma"""
        busy = self.ticker.isActive()
        self.draft.setEnabled(up and not busy)
        self.draft.setToolTip("" if up else "Gemma is off or not responding: switch it on, or reboot it")

    def show_progress(self, p):
        self.last = (p, time.monotonic())
        self.tick()

    def tick(self):
        """the bar and the time left, run on from the latest measured estimate; the bar never goes backwards"""
        if not self.last:
            return
        p, at = self.last
        now = time.monotonic()
        eta = None if p["eta"] is None else max(0.0, p["eta"] - (now - at))
        spent = now - self.started
        fraction = p["fraction"] if eta is None else spent / (spent + eta) if spent + eta else 1.0
        if eta is not None and eta == 0 and p["step"] != "Done":
            fraction = min(fraction, 0.99)  # running over the estimate: wait at the end, not past it
        self.shown = max(self.shown, min(1.0, fraction))
        self.bar.setValue(int(1000 * self.shown))
        left = "ESTIMATING…" if eta is None else "ALMOST DONE" if eta < 1.5 else f"ABOUT {round(eta)} S LEFT" if eta < 90 else f"ABOUT {eta / 60:.1f} MIN LEFT"
        batches = f" · BATCH {p['done']} OF {p['total']}" if p["total"] and p["step"].startswith("Gemma sorts") else ""
        self.note.setText(f"{p['step'].upper()}{batches} · {left}")

    def show_draft(self, goal):
        self.draft.setEnabled(True)
        self.ticker.stop()
        self.last = None
        self.bar.hide()
        if isinstance(goal, Exception):
            self.note.setText(f"COULDN'T REACH GEMMA: {goal}"[:80])
            return
        self.note.setText("")
        w = GoalWindow(self, goal, f"GEMMA SORTED THE {goal.get('sorted', 0)} OF {goal.get('map', 0)} MAP TOPICS NEAREST YOUR GOAL.",
                       self.internet_culture, self.positions())
        if w.exec():
            self.text.clear()
            self.save(self.goals + [w.goal()])

    def edit(self, i):
        w = GoalWindow(self, self.goals[i], "", self.internet_culture, self.positions())
        if w.exec():
            self.save([w.goal() if k == i else g for k, g in enumerate(self.goals)])

    def save(self, goals):
        self.goals = goals
        self.show_rows()

        def work():  # embedding the topics needs Ollama: off the window's thread
            self.hull.set_goals(goals)
            together = [t for g in goals for t in g.get("focus", []) + g.get("block", [])]
            try:
                self.internet_culture.anchors(list(dict.fromkeys(together)))
            except Exception as e:
                log.warning("couldn't embed the goals' topics: %s", e)
            self.applied.emit()
        threading.Thread(target=work, daemon=True).start()


class TitleBar(QFrame):
    """Hull's own window bar, in Rudder's style: the hull, HULL, and square minimise / maximise / close buttons.
    Moving and snapping go through the system (startSystemMove), so Windows' snap layouts still work."""
    def __init__(self, window):
        super().__init__()
        self.window_ = window
        self.setFixedHeight(32)  # the rule under it is its own line (Window), so the buttons' dividers meet it cleanly
        self.setStyleSheet(f"TitleBar {{ background: {PAPER}; border: 0; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 0, 0)
        row.setSpacing(8)
        icon = QSvgWidget(str(ASSETS / "hull-icon.svg"))
        icon.setFixedSize(18, 18)
        row.addWidget(icon)
        name = label("HULL")
        name.setStyleSheet("font-weight: 700; letter-spacing: 2px;")
        row.addWidget(name)
        row.addStretch(1)
        buttons = QHBoxLayout()  # flush together: no gaps between their dividers
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(0)
        row.addLayout(buttons)
        self.max = None
        for text, tip, act, hover in (("—", "Minimise", window.showMinimized, INK), ("▢", "Maximise", self.toggle, INK),
                                      ("×", "Close: Hull keeps steering from the tray", window.close, RED)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedSize(46, 32)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(f"QPushButton {{ border: 0; border-left: 2px solid {INK}; font-size: 15px; padding: 0; margin: 0; }}"
                            f"QPushButton:hover {{ background: {hover}; color: {PAPER}; }}")
            b.clicked.connect(act)
            buttons.addWidget(b)
            if text == "▢":
                self.max = b

    def toggle(self):
        w = self.window_
        w.showNormal() if w.isMaximized() else w.showMaximized()

    def maximised(self, on):
        self.max.setText("❐" if on else "▢")
        self.max.setToolTip("Restore" if on else "Maximise")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.window_.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        self.toggle()


EDGE = 6  # px at the window's edge that resize it


class Window(QMainWindow):
    goal_applied = Signal()

    def __init__(self, hull, engine, tray, config="hull.toml"):
        super().__init__()
        self.hull, self.engine, self.tray, self.config = hull, engine, tray, config
        self.setWindowTitle("Hull")
        self.setWindowIcon(QIcon(str(ASSETS / "hull-icon.svg")))
        self.resize(1180, 760)
        # no system frame: Hull draws its own bar and a 2px ink border, and resizes from its edges
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setMouseTracking(True)
        frame = QWidget()
        frame.setObjectName("frame")
        frame.setMouseTracking(True)
        frame.setStyleSheet(f"QWidget#frame {{ border: 2px solid {INK}; background: {PAPER}; }}")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(0)
        self.bar = TitleBar(self)
        outer.addWidget(self.bar)
        rule = QFrame()
        rule.setFixedHeight(2)
        rule.setStyleSheet(f"background: {INK}; border: 0;")
        outer.addWidget(rule)
        self.setCentralWidget(frame)
        page = QWidget()
        page.setObjectName("page")
        page.setMouseTracking(True)
        outer.addWidget(page, 1)
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
        self.gemma = Switch("GEMMA", hull.set_llm)
        self.reboot = QPushButton("REBOOT")
        self.reboot.setToolTip("Restart Ollama and load Gemma again")
        self.reboot.setStyleSheet("border-width: 0 0 0 2px;")
        self.reboot.clicked.connect(hull.reboot_llm)
        self.gemma.layout().insertWidget(1, self.reboot)
        side.addWidget(self.steer)
        side.addWidget(self.filtering)
        side.addWidget(self.gemma)
        if sys.platform == "win32":
            self.login = Switch("START WITH WINDOWS", self.set_login)
            self.login.setToolTip("Opens Hull in the tray when you log in; Hull starts Ollama and Rudder's bridge if they aren't running")
            self.login.show_state(autostart.is_on())
            side.addWidget(self.login)
        self.numbers = Numbers(["recorded", "shown", "watched", "hull hid"])
        side.addWidget(self.numbers)
        self.internet_culture = next((st for st in hull.stages.values() if hasattr(st, "graph")), None)
        self.goals_box = None
        if self.internet_culture:
            side.addWidget(label("YOUR GOALS", "h2"))
            self.goals_box = Goals(hull, self.internet_culture, self.goal_applied, lambda: self.map.positions)
            side.addWidget(self.goals_box)
            self.goal_applied.connect(lambda: (setattr(self.map, "key", None), self.redraw()))
        self.side = side
        side.addStretch(1)
        holder = QWidget()  # never scrolls: the title stays on top, and the window grows to fit what's below it
        holder.setObjectName("page")
        holder.setLayout(side)
        holder.setFixedWidth(360)
        self.columns.addWidget(holder)

        main = QVBoxLayout()
        main.setSpacing(6)
        head = QHBoxLayout()
        title = label("YOUR INTERNET CULTURE MAP", "h2")
        title.setWordWrap(False)
        head.addWidget(title)
        head.addStretch(1)
        self.legend = label("● near your focus   ● near what you block   ◌ Gemma decides", "lbl")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setText(f'<span style="color:{BLUE}">●</span> NEAR YOUR FOCUS &nbsp; <span style="color:{RED}">●</span> NEAR WHAT YOU BLOCK &nbsp; ◌ GEMMA DECIDES'
                            f' &nbsp; GROUND: <span style="color:{BLUE}">■</span> SHOWN <span style="color:{RED}">■</span> HIDDEN')
        head.addWidget(self.legend)
        main.addLayout(head)
        self.map = InternetCultureMap()
        self.map.picked.connect(self.pick)
        self.focus = Focus(self.map)
        self.map.overlay = self.focus
        main.addWidget(self.map, 1)
        when = QHBoxLayout()
        when.addWidget(label("GROWTH", "lbl"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(1000)
        self.slider.valueChanged.connect(self.slide)
        self.sharpen = QTimer(self, singleShot=True, interval=160, timeout=lambda: self.map.show_time(self.since(), fine=True))
        self.times = []  # every video's first sighting, sorted: the slider's dates and counts without asking the database
        when.addWidget(self.slider, 1)
        self.when = label("NOW", "lbl")
        self.when.setMinimumWidth(190)
        when.addWidget(self.when)
        main.addLayout(when)
        self.columns.addLayout(main, 1)
        self.map_timer = QTimer(self, interval=10000, timeout=self.redraw)
        self.map_timer.start()
        QTimer.singleShot(0, self.redraw)

        engine.status.connect(self.show_status)
        self.show_status(dict(hull.status))
        self.timer = QTimer(self, interval=2000, timeout=self.refresh)
        self.timer.start()
        self.refresh()
        self.told = False

    def uninstall(self, app):
        """take Hull out of Rudder and Windows startup, optionally delete its data, close (and Hull.exe deletes itself)"""
        frozen = getattr(sys, "frozen", False)
        box = QMessageBox(self)
        box.setWindowTitle("Uninstall Hull")
        box.setText("Uninstall Hull?\n\nHull takes its stages out of Rudder (YouTube filters as before), leaves Windows startup "
                    "and closes." + (" Hull.exe then deletes itself." if frozen else " To remove the program too, run: pip uninstall hull") +
                    "\n\nOllama and its models stay.")
        wipe = QCheckBox("Also delete my internet culture map and data (hull.db, thumbnails, settings, goals)")
        box.setCheckBox(wipe)
        go = box.addButton("UNINSTALL", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("CANCEL", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not go:
            return
        delete_data = wipe.isChecked()

        def finish():  # after the engine has left Rudder (it's connected to aboutToQuit first)
            self.hull.store.db.close()
            uninstall.remove(self.config, self.hull.store.folder, delete_data)
            uninstall.delete_exe_later(self.hull.store.folder if delete_data else None)
        app.aboutToQuit.connect(finish)
        self.tray.hide()
        app.quit()

    def set_login(self, on):
        autostart.set_on(on, self.config)
        self.login.show_state(autostart.is_on())

    def show_status(self, s):
        self.banner.show_status(s)
        connected = s["rudder"] and s["firefox"]
        self.steer.show_state(s["steering"] if connected else self.hull.steering, connected)
        self.filtering.show_state(s["filtering"], connected)
        g, q = s.get("gemma", "starting"), s.get("queued", 0)
        self.gemma.show_state(self.hull.llm)
        self.gemma.text.setText({"ready": "GEMMA · READY", "starting": "GEMMA · LOADING…", "off": "GEMMA · OFF", "down": "GEMMA · NOT RESPONDING",
                                 "rebooting": "GEMMA · REBOOTING…"}.get(g, "GEMMA") + (f" · {q} QUEUED" if q else ""))
        self.gemma.text.setStyleSheet(f"font-weight: 700; padding: 0 8px; color: {RED if g == 'down' else INK};")
        self.reboot.setEnabled(g != "rebooting")
        if self.goals_box:
            self.goals_box.gemma(g in ("ready", "starting") and self.hull.llm)
        self.tray.setIcon(QIcon(str(ASSETS / ("hull-icon.svg" if s["steering"] else "hull-icon-off.svg"))))
        self.tray.setToolTip("Hull: steering Rudder" if s["steering"] else "Hull: watching while Rudder filters on its own")
        if hasattr(self, "steer_action"):  # the tray menu's switch
            self.steer_action.setChecked(self.hull.steering)

    def refresh(self):
        s = self.hull.store.stats()
        self.numbers.set("recorded", s["videos"])
        self.numbers.set("shown", s["shown"])
        self.numbers.set("watched", s["watched"])
        self.numbers.set("hull hid", sum(s["hid_by_stage"].values()))

    def since(self):
        """the slider's time (Unix seconds), or None at the right end: now, growing live"""
        if self.slider.value() >= 1000 or not self.times:
            return None
        first = self.times[0]
        return first + (time.time() - first) * self.slider.value() / 1000

    def show_when(self):
        t = self.since()
        n = len(self.times) if t is None else bisect.bisect_right(self.times, t)
        self.when.setText(("NOW" if t is None else time.strftime("%d %b %H:%M", time.localtime(t)).upper()) + f" · {n} VIDEOS")

    def slide(self):
        """the growth slider: show the map as it was, light while it moves, in full detail once it stops"""
        self.show_when()
        self.map.show_time(self.since(), fine=False)
        self.sharpen.start()

    def redraw(self):
        if not self.internet_culture:
            return
        self.times = [r[0] for r in self.hull.store.db.execute("select first_recorded from videos where first_recorded is not null order by 1")]
        self.show_when()
        self.map.at = self.since()
        self.map.draw(self.internet_culture)

    def pick(self, name, members):
        """a click on the map: the theme's telemetry in the focus panel; empty paper closes it"""
        self.map.selected = name or None
        self.map.key = None
        self.redraw()
        if not members:
            self.focus.hide()
            return
        db, e, c = self.hull.store.db, html.escape, self.internet_culture
        marks = c.marks(members)
        guess = marks is None  # Gemma's not ready: go by the goals' own topics only
        if guess:
            marks = {n: "block" if n in c.block else "focus" if n in c.focus else None for n in members}
        q = ",".join("?" * len(members))
        counts = dict(db.execute(f"select t.name, count(*) from video_topics vt join topics t on t.id = vt.topic_id where t.name in ({q}) group by t.name", members))
        top = sorted(members, key=lambda n: -counts.get(n, 0))
        theme = f"select vt.video_id from video_topics vt join topics t on t.id = vt.topic_id where t.name in ({q})"
        one = lambda sql: db.execute(sql.format(theme=theme), members).fetchone()[0]
        videos = one("select count(distinct video_id) from ({theme})")
        shown = one("select count(distinct video_id) from shown where video_id in ({theme})")
        hidden = one("select count(distinct video_id) from outcomes where hidden = 1 and video_id in ({theme})")
        watched = one("select count(distinct video_id) from captions where video_id in ({theme})")
        liked = one("select count(distinct video_id) from ratings where liked = 1 and video_id in ({theme})")
        disliked = one("select count(distinct video_id) from ratings where liked = 0 and video_id in ({theme})")
        focused = bool(c.focus)
        go, stop = theme_share([marks.get(n) for n in members], focused)
        rest = max(0.0, 1 - go - stop)
        likely = ("<b style='color:#2a7fb8'>SHOWN</b>" if go > stop else f"<b style='color:{RED}'>HIDDEN</b>") if max(go, stop) >= 0.5 \
            else "<b>DECIDED BY ITS OWN TOPICS</b>"
        bar = (f"<table width='100%' cellspacing='0' cellpadding='0' style='border:2px solid {INK}'><tr>"
               + "".join(f"<td width='{max(1, round(100 * w))}%' style='background:{col}'>&nbsp;</td>" for w, col in ((go, BLUE), (rest, FAINT), (stop, RED)) if w > 0)
               + "</tr></table>")
        body = (f"{len(members)} topics · {videos} videos<br>{bar}"
                f"<span style='font-size:10px'>{go:.0%} SHOWN · {rest:.0%} UNTOUCHED · {stop:.0%} HIDDEN</span><br>"
                f"A new video here will most likely be {likely}.<br>"
                + ("<span style='font-size:10px'>GEMMA ISN'T RUNNING: BY YOUR GOALS' OWN TOPICS ONLY</span><br>" if guess else ""))
        if name:
            side = {"focus": f"<span style='background:{BLUE}'>&nbsp;SHOWN&nbsp;</span>", "block": f"<span style='background:{RED}'>&nbsp;HIDDEN&nbsp;</span>",
                    "ask": "GEMMA HASN'T DECIDED"}.get(marks.get(name), "HIDDEN (outside your focus)" if focused else "UNTOUCHED")
            said = [f"{'for' if name in g.get('focus', []) else 'against'}: {e(g.get('text') or 'untitled')}" for g in self.hull.goals
                    if name in g.get("focus", []) + g.get("block", [])]
            body += (f"<br><b>{e(name)}</b> · {counts.get(name, 0)} videos · {side}"
                     + (f"<br><span style='font-size:10px'>{'<br>'.join(said)}</span>" if said else "") + "<br>")
        body += (f"<br><b>SEEN</b> {videos} &nbsp; <b>SHOWN</b> {shown} &nbsp; <b>HIDDEN</b> {hidden}<br>"
                 f"<b>WATCHED</b> {watched} &nbsp; <b>▲</b> {liked} &nbsp; <b>▼</b> {disliked}<br>"
                 "<br><b>MOST SEEN</b><br>" + " · ".join(f"{e(n)} {counts.get(n, 0)}" for n in top[:6]))
        recent = db.execute(f"""select v.title, exists(select 1 from shown s where s.video_id = v.id),
                                       (select o.hidden from outcomes o where o.video_id = v.id order by o.at desc limit 1)
                                from videos v where v.id in ({theme}) and trim(v.title) != '' order by v.first_recorded desc limit 5""", members).fetchall()
        if recent:
            body += "<br><br><b>LATEST</b><br>" + "<br>".join(f"{'▣' if s else ('▢' if h is None else '▨')} {e(t[:36])}" for t, s, h in recent) \
                    + "<br><span style='font-size:10px'>▣ SHOWN · ▨ HIDDEN · ▢ NOT ON SCREEN</span>"
        self.focus.show_text(f"{top[0].upper()} · {len(members)}", body)

    def edges(self, pos):
        """which window edges a point is on, for resizing"""
        if self.isMaximized():
            return Qt.Edge(0)
        r, e = self.rect(), Qt.Edge(0)
        if pos.x() <= EDGE: e |= Qt.Edge.LeftEdge
        if pos.x() >= r.width() - EDGE: e |= Qt.Edge.RightEdge
        if pos.y() <= EDGE: e |= Qt.Edge.TopEdge
        if pos.y() >= r.height() - EDGE: e |= Qt.Edge.BottomEdge
        return e

    def mouseMoveEvent(self, e):
        edges = self.edges(e.position().toPoint())
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        shape = (Qt.CursorShape.SizeFDiagCursor if edges in (L | T, R | B) else Qt.CursorShape.SizeBDiagCursor if edges in (R | T, L | B)
                 else Qt.CursorShape.SizeHorCursor if edges & (L | R) else Qt.CursorShape.SizeVerCursor if edges & (T | B) else None)
        self.setCursor(shape) if shape else self.unsetCursor()

    def mousePressEvent(self, e):
        edges = self.edges(e.position().toPoint())
        if e.button() == Qt.MouseButton.LeftButton and edges:
            self.windowHandle().startSystemResize(edges)

    def changeEvent(self, e):
        if e.type() == e.Type.WindowStateChange:
            self.bar.maximised(self.isMaximized())
        super().changeEvent(e)

    def closeEvent(self, e):  # keep steering from the tray
        e.ignore()
        self.hide()
        if not self.told:
            self.told = True
            self.tray.showMessage("Hull", "Hull keeps steering from the tray. Quit there to stop it.", QIcon(str(ASSETS / "hull-icon.svg")), 4000)


def run(cfg, store, settings, tray=False, config="hull.toml"):
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("Hull")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    hull = Hull(cfg, store, settings)
    engine = Engine(hull)
    quiet = tray  # started by Windows at login: just the tray icon
    tray = QSystemTrayIcon(QIcon(str(ASSETS / "hull-icon-off.svg")))
    window = Window(hull, engine, tray, config)

    menu = QMenu()
    menu.addAction("Open Hull", lambda: (window.showNormal(), window.raise_(), window.activateWindow()))
    steer = QAction("Hull steers Rudder", menu, checkable=True, checked=hull.steering)
    steer.toggled.connect(lambda on: on != hull.steering and hull.set_steering(on))
    window.steer_action = steer
    menu.addAction(steer)
    menu.addSeparator()
    menu.addAction("Quit Hull", app.quit)
    menu.addAction("Uninstall Hull…", lambda: window.uninstall(app))
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and (window.showNormal(), window.activateWindow()))
    tray.show()

    app.aboutToQuit.connect(engine.stop)
    engine.start()
    if not quiet:
        window.show()
    return app.exec()
