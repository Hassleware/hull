"""Hull's desktop app (Qt): whether Hull is steering Rudder, two switches (Hull steers / Rudder filters), your goal, and
your culture map. Hull itself (hull/link.py) runs on a thread of its own; the window only shows and switches it.
Closing the window keeps Hull going in the system tray; Quit there takes Hull's stages out of Rudder and stops.

Styled like Rudder's popup: paper, ink, square 2px borders, monospace, uppercase headings, Rudder blue."""
import asyncio, html, logging, sys, threading, time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSystemTrayIcon, QVBoxLayout, QWidget)

from hull.link import Hull
from hull.mapview import CultureMap

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
QLineEdit {{ min-height: 20px; }}
QLineEdit:focus, QPlainTextEdit:focus {{ background: #ffffff; }}
QScrollArea {{ border: 0; }}
QScrollBar:vertical {{ width: 8px; background: {PAPER}; margin: 0; }}
QScrollBar::handle:vertical {{ background: {FAINT}; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
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
            text, bg, fg = "HULL IS WATCHING · Rudder filters on its own", PAPER, INK
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


class Chips(QWidget):
    """a list of topics as chips, each with ×, and a box to add one"""
    def __init__(self, title):
        super().__init__()
        self.items = []
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

    def set(self, items):
        self.items = list(items)
        self.flow.setText(" ".join(f'<span style="border:2px solid {INK}">&nbsp;{html.escape(t)} <a href="{html.escape(t)}" style="color:{INK};text-decoration:none"><b>×</b></a>&nbsp;</span>'
                                   for t in self.items) or "—")


class GoalBox(QFrame):
    """your goal in plain words → Gemma drafts focus and block topics → you edit them → Apply"""
    drafted = Signal(object)

    def __init__(self, hull, culture, applied):
        super().__init__()
        self.hull, self.culture, self.applied = hull, culture, applied
        self.setProperty("box", True)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("What do you want YouTube for?  e.g. I'm a student learning Bayesian statistics. Nothing else.")
        self.text.setFixedHeight(58)
        v.addWidget(self.text)
        row = QHBoxLayout()
        self.draft = QPushButton("DRAFT WITH GEMMA")
        self.draft.clicked.connect(self.ask)
        row.addWidget(self.draft)
        self.note = label("", "lbl")
        row.addWidget(self.note, 1)
        v.addLayout(row)
        self.focus, self.block = Chips("SHOW ONLY WHAT'S NEAR (empty: everything)"), Chips("NEVER SHOW WHAT'S NEAR")
        v.addWidget(self.focus)
        v.addWidget(self.block)
        row = QHBoxLayout()
        self.apply = QPushButton("APPLY")
        self.apply.clicked.connect(self.use)
        clear = QPushButton("CLEAR GOAL")
        clear.clicked.connect(lambda: (self.text.clear(), self.focus.set([]), self.block.set([]), self.use()))
        row.addWidget(self.apply)
        row.addWidget(clear)
        row.addStretch(1)
        v.addLayout(row)
        self.drafted.connect(self.show_draft)
        goal = (hull.settings.get("goal") if hull.settings else None) or {"text": "", "focus": culture.focus, "block": culture.block}
        self.text.setPlainText(goal.get("text", ""))
        self.focus.set(goal.get("focus", []))
        self.block.set(goal.get("block", []))

    def ask(self):
        text = self.text.toPlainText().strip()
        if not text:
            return
        self.draft.setEnabled(False)
        self.note.setText("GEMMA IS THINKING…")

        def work():
            try:
                self.drafted.emit(self.culture.draft_goal(text))
            except Exception as e:  # Ollama not running, say
                self.drafted.emit(e)
        threading.Thread(target=work, daemon=True).start()

    def show_draft(self, goal):
        self.draft.setEnabled(True)
        if isinstance(goal, Exception):
            self.note.setText(f"COULDN'T REACH GEMMA: {goal}"[:80])
            return
        self.note.setText("CHECK THE TOPICS, THEN APPLY")
        self.focus.set(goal["focus"])
        self.block.set(goal["block"])

    def use(self):
        goal = {"text": self.text.toPlainText().strip(), "focus": self.focus.items, "block": self.block.items}
        self.note.setText("APPLIED" if goal["focus"] or goal["block"] else "NO GOAL: GEMMA ONLY MAPS YOUR CULTURE")

        def work():  # embedding the topics needs Ollama: off the window's thread
            self.hull.set_goal(goal)
            try:
                self.culture.anchors(goal["focus"] + goal["block"])
            except Exception as e:
                log.warning("couldn't embed the goal's topics: %s", e)
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

    def __init__(self, hull, engine, tray):
        super().__init__()
        self.hull, self.engine, self.tray = hull, engine, tray
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
        side.addWidget(self.steer)
        side.addWidget(self.filtering)
        self.numbers = Numbers(["recorded", "shown", "watched", "hull hid"])
        side.addWidget(self.numbers)
        self.culture = next((st for st in hull.stages.values() if hasattr(st, "graph")), None)
        if self.culture:
            side.addWidget(label("YOUR GOAL", "h2"))
            side.addWidget(GoalBox(hull, self.culture, self.goal_applied))
            self.goal_applied.connect(lambda: (setattr(self.map, "key", None), self.redraw()))
        side.addWidget(label("TOPIC", "h2"))
        self.details = label("Click a topic on your culture map.")
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.details.setStyleSheet(f"border: 2px solid {INK}; padding: 8px;")
        self.details.linkActivated.connect(self.pick)
        side.addWidget(self.details)
        self.side = side
        side.addStretch(1)
        holder = QWidget()
        holder.setObjectName("page")
        holder.setLayout(side)
        scroll = QScrollArea()  # the side column scrolls on small screens
        scroll.setWidget(holder)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(372)
        self.columns.addWidget(scroll)

        main = QVBoxLayout()
        main.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(label("YOUR CULTURE MAP", "h2"))
        head.addStretch(1)
        self.legend = label("● near your focus   ● near what you block   ◌ Gemma decides", "lbl")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setText(f'<span style="color:{BLUE}">●</span> NEAR YOUR FOCUS &nbsp; <span style="color:{RED}">●</span> NEAR WHAT YOU BLOCK &nbsp; ◌ GEMMA DECIDES')
        head.addWidget(self.legend)
        main.addLayout(head)
        self.map = CultureMap()
        self.map.picked.connect(self.pick)
        main.addWidget(self.map, 1)
        when = QHBoxLayout()
        when.addWidget(label("GROWTH", "lbl"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(1000)
        self.slider.valueChanged.connect(self.redraw)
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

    def show_status(self, s):
        self.banner.show_status(s)
        connected = s["rudder"] and s["firefox"]
        self.steer.show_state(s["steering"] if connected else self.hull.steering, connected)
        self.filtering.show_state(s["filtering"], connected)
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
        first = self.hull.store.db.execute("select min(first_recorded) from videos").fetchone()[0]
        if self.slider.value() >= 1000 or not first:
            return None
        return first + (time.time() - first) * self.slider.value() / 1000

    def redraw(self):
        if not self.culture:
            return
        t = self.since()
        n = self.hull.store.db.execute("select count(*) from videos where ? is null or first_recorded <= ?", (t, t)).fetchone()[0]
        self.when.setText(("NOW" if t is None else time.strftime("%d %b %H:%M", time.localtime(t)).upper()) + f" · {n} VIDEOS")
        self.map.draw(self.culture, t)

    def pick(self, name):
        """a topic's details: how often, what the goal does with it, its neighbours, its videos"""
        if not self.culture or name not in self.culture.graph.index:
            return
        self.map.selected = name
        self.redraw()
        db, e = self.hull.store.db, html.escape
        mark = self.culture.marks([name]).get(name)
        why = next((w for (t, _), (_, w) in self.culture.verdicts.items() if t == name), None)
        goal = {"focus": f'<span style="background:{BLUE}">&nbsp;NEAR YOUR FOCUS&nbsp;</span>', "block": f'<span style="background:{RED}">&nbsp;NEAR WHAT YOU BLOCK&nbsp;</span>',
                "ask": "GEMMA HASN'T DECIDED YET"}.get(mark, "outside your goal" if (self.culture.focus or self.culture.block) else "no goal set")
        neighbours = self.culture.graph.neighbours(name)[:8]
        videos = db.execute("""select v.title, exists(select 1 from shown s where s.video_id = v.id) + exists(select 1 from watched w where w.video_id = v.id),
                                      (select o.hidden from outcomes o where o.video_id = v.id order by o.at desc limit 1)
                               from video_topics vt join topics t on t.id = vt.topic_id join videos v on v.id = vt.video_id
                               where t.name = ? and v.title != '' order by v.first_recorded desc limit 8""", (name,)).fetchall()
        count = db.execute("select count(*) from video_topics vt join topics t on t.id = vt.topic_id where t.name = ?", (name,)).fetchone()[0]
        self.details.setText(
            f'<b style="font-size:15px">{e(name)}</b><br>{count} videos · {goal}' + (f"<br><i>Gemma: {e(why)}</i>" if why else "") +
            "<br><br><b>NEIGHBOURS</b><br>" + (" · ".join(f'<a href="{e(u)}" style="color:{INK}">{e(u)}</a> {share:.0%}' for u, share in neighbours) or "none yet") +
            "<br><br><b>VIDEOS</b><br>" + "<br>".join(f"{'▶' if s == 2 else '▣' if s else ('▢' if h is None else '▨')} {e(t[:44])}" for t, s, h in videos) +
            "<br><span style='font-size:10px'>▶ WATCHED · ▣ SHOWN · ▨ HIDDEN · ▢ NOT ON SCREEN</span>")

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
