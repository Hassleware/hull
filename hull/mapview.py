"""The culture map: your culture graph drawn as a map. A dot per topic, as big as the number of videos you've seen on
it; a line between topics that share videos. Where a topic sits comes from its meaning (its embedding, flattened to
two dimensions) pulled together with its neighbours (a force layout), so related culture clusters on its own.
Colour says what your goal does with it: blue near your focus, red near what you block, dashed where Gemma decides."""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView

PAPER, INK, FAINT, BLUE, RED = "#f2ede1", "#111111", "#d9d2c1", "#5BB8F0", "#E5484D"
MOST = 300  # topics drawn: the most-seen ones


def flatten(vecs):
    """embeddings → 2-D by their two main directions (PCA), scaled to about ±1"""
    if len(vecs) < 3:
        return np.zeros((len(vecs), 2))
    x = vecs - vecs.mean(0)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    p = x @ vt[:2].T
    return p / (np.abs(p).max(0) + 1e-9)


def layout(start, edges, iters=120):
    """force layout (Fruchterman-Reingold): every pair pushes apart, linked topics pull together by how many videos
    they share. start: (n, 2) positions; edges: [(i, j, weight)]. ponytail: O(n²) per step, fine to a few hundred dots"""
    pos, n = start.astype(float).copy(), len(start)
    if n < 2:
        return pos
    k = 1.5 / math.sqrt(n)
    ij = np.array([(i, j) for i, j, _ in edges], int).reshape(-1, 2)
    w = np.array([w for *_, w in edges], float)
    t = 0.12
    for _ in range(iters):
        d = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(d, axis=2) + 1e-6
        move = ((k * k / dist ** 2)[..., None] * d).sum(1)
        if len(ij):
            e = pos[ij[:, 0]] - pos[ij[:, 1]]
            el = np.linalg.norm(e, axis=1, keepdims=True) + 1e-6
            pull = e * (el / k) * np.log1p(w)[:, None]
            np.add.at(move, ij[:, 0], -pull)
            np.add.at(move, ij[:, 1], pull)
        move -= pos * 0.15  # gravity, so islands (topics with no shared videos yet) stay near
        step = np.linalg.norm(move, axis=1, keepdims=True) + 1e-9
        pos += move / step * np.minimum(step, t)
        t *= 0.97
    return pos


def read(graph, since=None):
    """the most-seen topics (seen first by `since`, Unix seconds, if given) and the links among them"""
    db = graph.db
    rows = db.execute("""select t.name, count(*) from video_topics vt join topics t on t.id = vt.topic_id
                         left join videos v on v.id = vt.video_id where ? is null or coalesce(v.first_recorded, 0) <= ?
                         group by t.id order by 2 desc limit ?""", (since, since, MOST)).fetchall()
    names = [r[0] for r in rows]
    at = {n: i for i, n in enumerate(names)}
    links = db.execute("""select ta.name, tb.name, count(*) from video_topics a join video_topics b on a.video_id = b.video_id and a.topic_id < b.topic_id
                          join topics ta on ta.id = a.topic_id join topics tb on tb.id = b.topic_id
                          left join videos v on v.id = a.video_id where ? is null or coalesce(v.first_recorded, 0) <= ?
                          group by a.topic_id, b.topic_id""", (since, since)).fetchall()
    edges = [(at[a], at[b], c) for a, b, c in links if a in at and b in at]
    return names, [r[1] for r in rows], edges


class CultureMap(QGraphicsView):
    picked = Signal(str)  # a topic was clicked

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)  # drag to move around, wheel to zoom
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(PAPER))
        self.setStyleSheet(f"border: 2px solid {INK};")
        self.positions = {}  # topic → (x, y), kept between redraws so the map doesn't jump
        self.key, self.fitted, self.selected = None, False, None

    def draw(self, culture, since=None):
        """(re)draw from the culture stage's graph; marks: topic → "focus" | "block" | "ask" | None"""
        names, counts, edges = read(culture.graph, since)
        marks = culture.marks(names)
        key = (tuple(names), tuple(counts), len(edges), tuple(sorted(marks.items())), self.selected)
        if key == self.key:
            return
        self.key = key
        scene = self.scene()
        scene.clear()
        if not names:
            t = scene.addSimpleText("No culture yet: Hull draws your map as Gemma tags the videos Rudder sees.")
            t.setFont(QFont("Cascadia Mono", 11))
            return
        # start each topic where it was, else beside its neighbours, else where its meaning puts it
        flat = flatten(np.array([culture.graph.vecs[culture.graph.index[n]] for n in names]))
        start = np.zeros((len(names), 2))
        for i, n in enumerate(names):
            if n in self.positions:
                start[i] = self.positions[n]
            else:
                near = [self.positions[names[j if i == k else k]] for k, j, _ in edges if i in (k, j) and names[j if i == k else k] in self.positions]
                start[i] = np.mean(near, 0) + np.random.default_rng(i).normal(0, 0.05, 2) if near else flat[i]
        pos = layout(start, edges, iters=40 if self.positions else 160)
        self.positions.update({n: tuple(p) for n, p in zip(names, pos)})

        scale, most = 900, max(counts)
        xy = pos * scale
        for i, j, w in edges:
            pen = QPen(QColor(17, 17, 17, min(200, 40 + 30 * w)), 1 + math.log1p(w) * 0.6)
            scene.addLine(*xy[i], *xy[j], pen)
        for i, (name, c) in enumerate(zip(names, counts)):
            r = 3 + 9 * math.sqrt(c / most)
            mark = marks.get(name)
            dot = Dot(name, QRectF(-r, -r, 2 * r, 2 * r), self.picked)
            dot.setPos(QPointF(*xy[i]))
            fill = {"focus": BLUE, "block": RED}.get(mark, PAPER)
            pen = QPen(QColor(INK), 3 if name == self.selected else 1.5)
            if mark == "ask":
                pen.setStyle(Qt.PenStyle.DashLine)
            dot.setPen(pen)
            dot.setBrush(QBrush(QColor(fill)))
            dot.setToolTip(f"{name}\n{c} videos" + (f"\n{mark}" if mark else ""))
            dot.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)  # pins: same size at any zoom
            dot.setZValue(1)
            scene.addItem(dot)
            if (i < 40 and c > 1) or i < 8 or name == self.selected:  # names on the most-seen; the rest on hover
                t = QGraphicsSimpleTextItem(name, dot)
                t.setFont(QFont("Cascadia Mono", 9, QFont.Weight.Bold if c > most / 3 else QFont.Weight.Normal))
                t.setPos(r + 3, -8)
        scene.setSceneRect(QRectF(*xy.min(0), *(xy.max(0) - xy.min(0))).adjusted(-60, -40, 160, 40))  # room for names
        if not self.fitted:
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.fitted = True

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)


class Dot(QGraphicsEllipseItem):
    def __init__(self, name, rect, picked):
        super().__init__(rect)
        self.name, self.picked = name, picked
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptHoverEvents(True)

    def mousePressEvent(self, e):
        self.picked.emit(self.name)
        e.accept()
