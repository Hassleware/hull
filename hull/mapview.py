"""The internet culture map: your internet culture graph drawn as a map. A dot per topic, as big as the number of
videos you've seen on it; a line between topics that share videos. Where a topic sits comes from its meaning (its
embedding, flattened to two dimensions) pulled together with its neighbours and its community (a force layout).
Colour says what your goal does with it: blue near your focus, red near what you block, dashed where Gemma decides.

It reads at every zoom (apply_detail, on every zoom, pan and resize):
  - Communities (topics more linked to each other than to the rest) get a shaded shape around them. While a community
    is small on screen it shows one name, its most-seen topic, and its inside lines go faint; zoomed in, its topics'
    names come out.
  - A name is drawn only where it has room: names are placed most-seen first, and one that would touch a name
    already placed waits until zooming spreads them apart. Every dot is always drawn, and hovering shows its name.
  - Lines keep their width on screen. Between two communities that are both small on screen, all the lines become
    one, thicker the more videos they share; once either opens, its own lines come back.
"""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem, QGraphicsPathItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView)

PAPER, INK, FAINT, BLUE, RED = "#f2ede1", "#111111", "#d9d2c1", "#5BB8F0", "#E5484D"
SHADE = "#e6dfcd"  # inside a community's shape
MOST = 300  # topics drawn: the most-seen ones
OPEN_PX = 260  # a community opens (its topics' names come out) once it's this big on screen
GAP = 4  # px kept between names


def flatten(vecs):
    """embeddings → 2-D by their two main directions (PCA), scaled to about ±1"""
    if len(vecs) < 3:
        return np.zeros((len(vecs), 2))
    x = vecs - vecs.mean(0)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    p = x @ vt[:2].T
    return p / (np.abs(p).max(0) + 1e-9)


def communities(n, edges, counts=None, resolution=1.0):
    """the map's themes: groups of topics more linked to each other than to the rest (Louvain: move each topic to the
    group that raises modularity most, then treat each group as one topic and repeat, so small groups merge into
    themes like music, gaming, food). counts is unused, kept for callers."""
    part = list(range(n))  # topic → its group
    nodes, links = n, {}
    for i, j, w in edges:
        if i != j:
            links[(i, j)] = links.get((i, j), 0) + w
    while True:
        nb = [dict() for _ in range(nodes)]
        loops = [0.0] * nodes
        for (i, j), w in links.items():
            if i == j:
                loops[i] += w
            else:
                nb[i][j] = nb[i].get(j, 0) + w
                nb[j][i] = nb[j].get(i, 0) + w
        k = [sum(d.values()) + 2 * loops[i] for i, d in enumerate(nb)]
        m2 = sum(k)
        if not m2:
            break
        comm, tot = list(range(nodes)), k[:]
        moved = True
        while moved:
            moved = False
            for i in sorted(range(nodes), key=lambda i: -k[i]):
                c0 = comm[i]
                tot[c0] -= k[i]
                into = {}
                for j, w in nb[i].items():
                    into[comm[j]] = into.get(comm[j], 0) + w
                best, gain = c0, into.get(c0, 0) - resolution * tot[c0] * k[i] / m2
                for c, w in into.items():
                    g = w - resolution * tot[c] * k[i] / m2
                    if g > gain + 1e-12:
                        best, gain = c, g
                comm[i] = best
                tot[best] += k[i]
                moved |= best != c0
        ids = {c: x for x, c in enumerate(dict.fromkeys(comm))}
        if len(ids) == nodes:
            break  # nothing merged: done
        part = [ids[comm[p]] for p in part]
        merged = {}
        for (i, j), w in links.items():
            a, b = sorted((ids[comm[i]], ids[comm[j]]))
            merged[(a, b)] = merged.get((a, b), 0) + w
        nodes, links = len(ids), merged
    ids = {c: x for x, c in enumerate(dict.fromkeys(part))}
    return [ids[c] for c in part]


def layout(start, edges, iters=120, group=None):
    """force layout (Fruchterman-Reingold): every pair pushes apart, linked topics pull together by how many videos
    they share, and each community draws in to its middle. start: (n, 2); edges: [(i, j, weight)]; group: community
    per topic. ponytail: O(n²) per step, fine to a few hundred dots"""
    pos, n = start.astype(float).copy(), len(start)
    if n < 2:
        return pos
    k = 1.5 / math.sqrt(n)
    ij = np.array([(i, j) for i, j, _ in edges], int).reshape(-1, 2)
    w = np.array([w for *_, w in edges], float)
    g = np.array(group if group is not None else range(n))
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
        sums = np.zeros((g.max() + 1, 2))
        np.add.at(sums, g, pos)
        middle = sums / np.bincount(g)[:, None]
        move -= (pos - middle[g]) * 0.6  # communities stay compact, so their shapes don't sprawl over each other
        move -= pos * 0.15  # gravity, so islands (topics with no shared videos yet) stay near
        step = np.linalg.norm(move, axis=1, keepdims=True) + 1e-9
        pos += move / step * np.minimum(step, t)
        t *= 0.97
    return pos


def hull_of(points):
    """convex hull (monotone chain), counter-clockwise"""
    pts = sorted(map(tuple, points))
    if len(pts) < 3:
        return pts
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


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


def cosmetic(color, width, alpha=255):
    c = QColor(color)
    c.setAlpha(alpha)
    pen = QPen(c, width)
    pen.setCosmetic(True)  # the same width on screen at any zoom
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


class InternetCultureMap(QGraphicsView):
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
        self.parts = None  # what apply_detail shows and hides

    def draw(self, internet_culture, since=None):
        """(re)draw from the internet culture stage's graph; marks: topic → "focus" | "block" | "ask" | None"""
        names, counts, edges = read(internet_culture.graph, since)
        marks = internet_culture.marks(names)
        key = (tuple(names), tuple(counts), len(edges), tuple(sorted(marks.items())), self.selected)
        if key == self.key:
            return
        self.key = key
        scene = self.scene()
        scene.clear()
        self.parts = None
        if not names:
            t = scene.addSimpleText("No internet culture yet: Hull draws your map as Gemma tags the videos Rudder sees.")
            t.setFont(QFont("Cascadia Mono", 11))
            return
        group = communities(len(names), edges, counts)
        # start each topic where it was, else beside its neighbours, else where its meaning puts it
        flat = flatten(np.array([internet_culture.graph.vecs[internet_culture.graph.index[n]] for n in names]))
        start = np.zeros((len(names), 2))
        for i, n in enumerate(names):
            if n in self.positions:
                start[i] = self.positions[n]
            else:
                near = [self.positions[names[j if i == k else k]] for k, j, _ in edges if i in (k, j) and names[j if i == k else k] in self.positions]
                start[i] = np.mean(near, 0) + np.random.default_rng(i).normal(0, 0.05, 2) if near else flat[i]
        pos = layout(start, edges, iters=40 if self.positions else 160, group=group)
        self.positions.update({n: tuple(p) for n, p in zip(names, pos)})

        xy, most = pos * 900, max(counts)
        members = {}
        for i, c in enumerate(group):
            members.setdefault(c, []).append(i)
        big = {c for c, ms in members.items() if len(ms) >= 4}  # communities that get a shape and a name

        # community shapes: the hull, filled, with a wide round outline in the same shade (padding that stays the
        # same on screen)
        for c in big:
            pts = hull_of(xy[members[c]])
            path = QPainterPath()
            path.addPolygon(QPolygonF([QPointF(*p) for p in pts]))
            path.closeSubpath()
            shape = QGraphicsPathItem(path)
            shape.setBrush(QBrush(QColor(SHADE)))
            shape.setPen(cosmetic(SHADE, 34))
            shape.setZValue(-3)
            scene.addItem(shape)

        # lines: each one, and one per pair of communities for when they're small on screen
        inside, across, between = {}, [], {}
        for i, j, w in edges:
            line = QGraphicsLineItem(*xy[i], *xy[j])
            line.setZValue(-1)
            scene.addItem(line)
            line.weight = w
            if group[i] == group[j]:
                inside.setdefault(group[i], []).append(line)
            else:
                across.append((line, group[i], group[j]))
                key2 = tuple(sorted((group[i], group[j])))
                between[key2] = between.get(key2, 0) + w
        middles = {c: xy[ms].mean(0) for c, ms in members.items()}
        bundles = []
        for (a, b), w in between.items():
            line = QGraphicsLineItem(*middles[a], *middles[b])
            line.setPen(cosmetic(INK, 1.5 + 1.5 * math.log1p(w), 150))
            line.setZValue(-2)
            scene.addItem(line)
            bundles.append((line, a, b))

        # dots, always drawn, and a name for each (shown by apply_detail where it fits)
        names_of, font = {}, QFont("Cascadia Mono", 9)
        for i, (name, c) in enumerate(zip(names, counts)):
            r = 3 + 9 * math.sqrt(c / most)
            mark = marks.get(name)
            dot = Dot(name, QRectF(-r, -r, 2 * r, 2 * r), self.picked)
            dot.setPos(QPointF(*xy[i]))
            pen = QPen(QColor(INK), 3 if name == self.selected else 1.5)
            if mark == "ask":
                pen.setStyle(Qt.PenStyle.DashLine)
            dot.setPen(pen)
            dot.setBrush(QBrush(QColor({"focus": BLUE, "block": RED}.get(mark, PAPER))))
            dot.setToolTip(f"{name}\n{c} videos" + (f"\n{mark}" if mark else ""))
            dot.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)  # pins: same size at any zoom
            dot.setZValue(1)
            scene.addItem(dot)
            t = QGraphicsSimpleTextItem(name, dot)
            t.setFont(QFont("Cascadia Mono", 9, QFont.Weight.Bold if c > most / 3 or name == self.selected else QFont.Weight.Normal))
            t.setPos(r + 3, -8)
            t.setVisible(False)
            names_of[i] = (t, r)

        # community names, centred on each shape
        titles, bold = {}, QFont("Cascadia Mono", 10, QFont.Weight.Bold)
        for c in big:
            top = max(members[c], key=lambda i: counts[i])
            box = QFontMetricsF(bold).boundingRect(f"{names[top].upper()} · {len(members[c])}")
            t = QGraphicsRectItem(box.adjusted(-5, -3, 5, 3))  # a paper plate, so the name reads over its dots
            t.setBrush(QBrush(QColor(242, 237, 225, 225)))
            t.setPen(QPen(Qt.PenStyle.NoPen))
            label = QGraphicsSimpleTextItem(f"{names[top].upper()} · {len(members[c])}", t)
            label.setFont(bold)
            label.setPos(box.x(), box.y())
            t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            t.setPos(QPointF(*middles[c]))
            t.setZValue(2)
            t.setVisible(False)
            scene.addItem(t)
            titles[c] = (t, box.translated(-box.x(), -box.y()))

        span = {c: float(np.ptp(xy[ms], axis=0).max()) if len(ms) > 1 else 0.0 for c, ms in members.items()}
        lows = {c: xy[ms].min(0) for c, ms in members.items()}
        highs = {c: xy[ms].max(0) for c, ms in members.items()}
        self.parts = dict(names=names, counts=counts, group=group, xy=xy, middles=middles, lows=lows, highs=highs, big=big, span=span, inside=inside, across=across,
                          bundles=bundles, names_of=names_of, titles=titles, font=QFontMetricsF(font))
        scene.setSceneRect(QRectF(*xy.min(0), *(xy.max(0) - xy.min(0))).adjusted(-80, -60, 200, 60))  # room for names
        if not self.fitted:
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.fitted = True
        self.apply_detail()

    def apply_detail(self):
        """show what reads at this zoom: open or closed communities, their names or their topics' names, single lines
        or bundles, and only names that have room"""
        p = self.parts
        if not p:
            return
        zoom = self.transform().m11()
        closed = {c for c in p["big"] if p["span"][c] * zoom < OPEN_PX}
        for c, lines in p["inside"].items():
            for line in lines:
                line.setPen(cosmetic(INK, 1 if c in closed else 1 + 0.5 * math.log1p(line.weight), 45 if c in closed else min(190, 70 + 30 * line.weight)))
        for line, a, b in p["across"]:
            line.setVisible(a not in closed or b not in closed)  # an open community shows its own lines
            line.setPen(cosmetic(INK, 1 + 0.5 * math.log1p(line.weight), min(170, 50 + 30 * line.weight)))
        for line, a, b in p["bundles"]:
            line.setVisible(a in closed and b in closed)  # between two closed communities: one line

        # names, most important first; each must keep GAP px from every name already placed
        size = {c: p["group"].count(c) for c in closed}
        want = [(1e9 + size[c], "title", c) for c in closed]  # bigger themes name themselves first
        want += [(p["counts"][i] + (1e8 if p["names"][i] == self.selected else 0), "name", i)
                 for i in range(len(p["names"])) if p["group"][i] not in closed]
        placed, view = [], self.viewport().rect()
        for t, _ in p["names_of"].values():
            t.setVisible(False)
        for t, _ in p["titles"].values():
            t.setVisible(False)
        for _, kind, k in sorted(want, reverse=True):
            if kind == "title":
                t, box = p["titles"][k]
                lo, hi = self.mapFromScene(QPointF(*p["lows"][k])), self.mapFromScene(QPointF(*p["highs"][k]))
                mid, w, h = self.mapFromScene(QPointF(*p["middles"][k])), box.width(), box.height()
                # on its middle, else just above its shape, else just below; nudged inside the view
                spots = [QRectF(mid.x() - w / 2, y, w, h) for y in (mid.y() - h / 2, lo.y() - h - 8, hi.y() + 8)]
                spots = [s.translated(min(0, view.right() - s.right()) - min(0, s.left() - view.left()),
                                      min(0, view.bottom() - s.bottom()) - min(0, s.top() - view.top())) for s in spots]
                rect = next((s for s in spots if not any(s.adjusted(-GAP, -GAP, GAP, GAP).intersects(o) for o in placed)), None)
                if rect is None:
                    continue
                t.setPos(self.mapToScene(int(rect.x()), int(rect.y())))
            else:
                t, r = p["names_of"][k]
                at = self.mapFromScene(QPointF(*p["xy"][k]))
                w = p["font"].horizontalAdvance(p["names"][k])
                rect = QRectF(at.x() + r + 3, at.y() - 8, w, 14)
                if not QRectF(view).contains(rect):  # cut off at the edge: wait until it's on screen
                    continue
                if any(rect.adjusted(-GAP, -GAP, GAP, GAP).intersects(o) for o in placed):
                    continue
            placed.append(rect)
            t.setVisible(True)

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)
        self.apply_detail()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.apply_detail()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.apply_detail()


class Dot(QGraphicsEllipseItem):
    def __init__(self, name, rect, picked):
        super().__init__(rect)
        self.name, self.picked = name, picked
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptHoverEvents(True)

    def mousePressEvent(self, e):
        self.picked.emit(self.name)
        e.accept()
