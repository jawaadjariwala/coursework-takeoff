"""The drawing surface: plan underlay, walls at true thickness, junctions.

Scene coordinates are plan-image pixels, because that is what the underlay is
measured in and it keeps the pixmap at its natural size. The model stores feet.
``px_per_ft`` is the only thing that converts between them, and it lives in
one place so a calibration mistake cannot leak into the geometry.

Walls are stroked at their real thickness rather than drawn as hairlines. That
is deliberate: once a wall has width you can see the overlap at a junction,
which is the whole point of the tool.
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from ..geometry.junctions import Solution
from ..model.types import Point, Project
from ..quantities.catalog import CATALOG
from . import theme

DEFAULT_PX_PER_FT = 12.0


class Mode(Enum):
    SELECT = auto()
    CALIBRATE = auto()
    DRAW_WALL = auto()


class PlanView(QGraphicsView):
    """Pan, zoom and the pointer work for every editing mode."""

    wall_clicked = Signal(int)
    junction_clicked = Signal(object)
    wall_finished = Signal(list)
    calibration_done = Signal(float, QPointF, QPointF)
    status = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setBackgroundBrush(QBrush(theme.PAPER))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)

        self.project: Project | None = None
        self.solution: Solution | None = None
        self.mode = Mode.SELECT
        self.selected_wall: int | None = None

        self._pixmap: QPixmap | None = None
        self._draft: list[Point] = []
        self._cursor_scene: QPointF | None = None
        self._calib: list[QPointF] = []
        self._panning = False
        self._pan_from = QPointF()

    # ---------------------------------------------------------------- units

    @property
    def px_per_ft(self) -> float:
        if self.project and self.project.px_per_ft:
            return self.project.px_per_ft
        return DEFAULT_PX_PER_FT

    def to_scene(self, p: Point) -> QPointF:
        """Plan feet to scene pixels.

        Plan y grows upward and screen y grows downward, so y is negated here.
        Flipping the whole view with ``scale(1, -1)`` would do the same job in
        one line, but it also mirrors the plan underlay, which then renders
        upside down. Negating at the one conversion boundary keeps the pixmap
        the right way up.
        """
        return QPointF(p[0] * self.px_per_ft, -p[1] * self.px_per_ft)

    def to_feet(self, p: QPointF) -> Point:
        return (p.x() / self.px_per_ft, -p.y() / self.px_per_ft)

    # ---------------------------------------------------------------- state

    def set_project(self, project: Project, solution: Solution | None = None) -> None:
        self.project = project
        self.solution = solution
        if project.plan_path:
            pix = QPixmap(project.plan_path)
            self._pixmap = pix if not pix.isNull() else None
        self.viewport().update()

    def set_solution(self, solution: Solution | None) -> None:
        self.solution = solution
        self.viewport().update()

    def set_mode(self, mode: Mode) -> None:
        self.mode = mode
        self._draft.clear()
        self._calib.clear()
        cursors = {
            Mode.SELECT: Qt.CursorShape.ArrowCursor,
            Mode.CALIBRATE: Qt.CursorShape.CrossCursor,
            Mode.DRAW_WALL: Qt.CursorShape.CrossCursor,
        }
        self.setCursor(cursors[mode])
        self.viewport().update()

    def content_rect(self) -> QRectF:
        if self._pixmap:
            return QRectF(0, 0, self._pixmap.width(), self._pixmap.height())
        if self.project and self.project.walls:
            pts = [
                self.to_scene(v) for w in self.project.walls for v in w.vertices
            ]
            pad = 8.0 * self.px_per_ft
            xs = [p.x() for p in pts]
            ys = [p.y() for p in pts]
            return QRectF(
                min(xs) - pad,
                min(ys) - pad,
                max(xs) - min(xs) + 2 * pad,
                max(ys) - min(ys) + 2 * pad,
            )
        return QRectF(0, 0, 800, 600)

    def fit(self) -> None:
        rect = self.content_rect()
        self._scene.setSceneRect(rect.adjusted(-rect.width(), -rect.height(),
                                               rect.width(), rect.height()))
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    # --------------------------------------------------------------- paint

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, theme.PAPER)
        if self._pixmap:
            painter.drawPixmap(QRectF(0, 0, self._pixmap.width(),
                                      self._pixmap.height()), self._pixmap,
                               QRectF(self._pixmap.rect()))
            return
        self._draw_grid(painter, rect)

    def _draw_grid(self, painter: QPainter, rect: QRectF) -> None:
        step = self.px_per_ft * 5.0
        if step <= 2:
            return
        major = step * 4
        layers = ((QPen(theme.GRID, 0), step), (QPen(theme.GRID_MAJOR, 0), major))
        for pen, spacing in layers:
            painter.setPen(pen)
            x = rect.left() - (rect.left() % spacing)
            while x < rect.right():
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                x += spacing
            y = rect.top() - (rect.top() % spacing)
            while y < rect.bottom():
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
                y += spacing

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if not self.project:
            return
        self._draw_walls(painter)
        self._draw_openings(painter)
        self._draw_junctions(painter)
        self._draw_draft(painter)
        self._draw_calibration(painter)

    def _wall_path(self, vertices: list[Point]) -> QPainterPath:
        path = QPainterPath(self.to_scene(vertices[0]))
        for v in vertices[1:]:
            path.lineTo(self.to_scene(v))
        return path

    def _draw_walls(self, painter: QPainter) -> None:
        assert self.project
        for wall in self.project.walls:
            asm = CATALOG.get(wall.assembly_key)
            width_px = (asm.thickness_ft if asm else 0.6) * self.px_per_ft
            color = theme.ASSEMBLY_COLORS.get(wall.assembly_key, theme.ASSEMBLY_FALLBACK)

            body = QColor(color)
            body.setAlpha(170)
            pen = QPen(body, width_px)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(pen)
            painter.drawPath(self._wall_path(wall.vertices))

            edge = QPen(color, 0)
            painter.setPen(edge)
            painter.drawPath(self._wall_path(wall.vertices))

            if wall.id == self.selected_wall:
                halo = QPen(theme.SELECTED, width_px + 4 / self._zoom())
                halo.setCapStyle(Qt.PenCapStyle.FlatCap)
                halo.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                painter.setPen(halo)
                painter.setOpacity(0.35)
                painter.drawPath(self._wall_path(wall.vertices))
                painter.setOpacity(1.0)

    def _draw_openings(self, painter: QPainter) -> None:
        assert self.project
        painter.setBrush(QBrush(theme.OPENING))
        painter.setPen(QPen(theme.OPENING_EDGE, 0))
        for opening in self.project.openings:
            try:
                wall = self.project.wall(opening.wall_id)
            except KeyError:
                continue
            placed = _station_point(wall.vertices, opening.station_ft)
            if placed is None:
                continue
            (cx, cy), (ux, uy) = placed
            asm = CATALOG.get(wall.assembly_key)
            half_t = (asm.thickness_ft if asm else 0.6) / 2.0
            half_w = opening.width_ft / 2.0
            corners = [
                (cx - ux * half_w + uy * half_t, cy - uy * half_w - ux * half_t),
                (cx + ux * half_w + uy * half_t, cy + uy * half_w - ux * half_t),
                (cx + ux * half_w - uy * half_t, cy + uy * half_w + ux * half_t),
                (cx - ux * half_w - uy * half_t, cy - uy * half_w + ux * half_t),
            ]
            painter.drawPolygon(QPolygonF([self.to_scene(c) for c in corners]))

    def _draw_junctions(self, painter: QPainter) -> None:
        if not self.solution:
            return
        r = 5.0 / self._zoom()
        for j in self.solution.junctions:
            color = theme.JUNCTION_COLORS.get(j.kind.value, theme.MUTED)
            painter.setPen(QPen(color, 2.0 / self._zoom()))
            fill = QColor(color)
            fill.setAlpha(60 if not j.adjustments else 190)
            painter.setBrush(QBrush(fill))
            painter.drawEllipse(self.to_scene(j.point), r, r)

    def _draw_draft(self, painter: QPainter) -> None:
        if self.mode is not Mode.DRAW_WALL or not self._draft:
            return
        pen = QPen(theme.PREVIEW, 2.0 / self._zoom())
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pts = [self.to_scene(p) for p in self._draft]
        if self._cursor_scene is not None:
            pts.append(self._cursor_scene)
        for a, b in zip(pts, pts[1:], strict=False):
            painter.drawLine(a, b)
        painter.setBrush(QBrush(theme.PREVIEW))
        for p in pts[:-1] if self._cursor_scene else pts:
            painter.drawEllipse(p, 3.0 / self._zoom(), 3.0 / self._zoom())

    def _draw_calibration(self, painter: QPainter) -> None:
        if self.mode is not Mode.CALIBRATE or not self._calib:
            return
        pen = QPen(theme.CALIBRATION, 2.0 / self._zoom())
        painter.setPen(pen)
        pts = list(self._calib)
        if self._cursor_scene is not None and len(pts) == 1:
            pts.append(self._cursor_scene)
        if len(pts) == 2:
            painter.drawLine(pts[0], pts[1])
        painter.setBrush(QBrush(theme.CALIBRATION))
        for p in self._calib:
            painter.drawEllipse(p, 4.0 / self._zoom(), 4.0 / self._zoom())

    def _zoom(self) -> float:
        return max(abs(self.transform().m11()), 1e-6)

    # ----------------------------------------------------------- interaction

    def wheelEvent(self, event) -> None:
        factor = 1.0015 ** event.angleDelta().y()
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        pos = self.mapToScene(event.position().toPoint())

        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._panning = True
            self._pan_from = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        if self.mode is Mode.CALIBRATE:
            self._calib.append(pos)
            if len(self._calib) == 2:
                a, b = self._calib
                px = ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5
                self.calibration_done.emit(px, a, b)
                self._calib.clear()
            self.viewport().update()
            return

        if self.mode is Mode.DRAW_WALL:
            self._draft.append(self.to_feet(pos))
            self.viewport().update()
            return

        self._select_at(pos)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.position() - self._pan_from
            self._pan_from = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            return
        self._cursor_scene = self.mapToScene(event.position().toPoint())
        x, y = self.to_feet(self._cursor_scene)
        self.status.emit(f"{x:,.2f}, {y:,.2f} ft")
        if self.mode in (Mode.DRAW_WALL, Mode.CALIBRATE):
            self.viewport().update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.set_mode(self.mode)
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.mode is Mode.DRAW_WALL and len(self._draft) >= 2:
            self.wall_finished.emit(list(self._draft))
            self._draft.clear()
            self.viewport().update()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._draft.clear()
            self._calib.clear()
            self.viewport().update()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.mode is Mode.DRAW_WALL and len(self._draft) >= 2:
                self.wall_finished.emit(list(self._draft))
                self._draft.clear()
                self.viewport().update()
                return
        super().keyPressEvent(event)

    def _select_at(self, pos: QPointF) -> None:
        if not self.project:
            return
        target = self.to_feet(pos)

        # Junctions are picked first. They sit on top of walls and they are
        # the thing a user clicks when they want to know why a number moved.
        if self.solution:
            reach = 8.0 / self._zoom() / self.px_per_ft
            hit = min(
                (j for j in self.solution.junctions
                 if _point_distance(target, j.point) < reach),
                key=lambda j: _point_distance(target, j.point),
                default=None,
            )
            if hit is not None:
                self.junction_clicked.emit(hit)
                return
        best, best_d = None, 1e18
        for wall in self.project.walls:
            asm = CATALOG.get(wall.assembly_key)
            half_t = (asm.thickness_ft if asm else 0.6) / 2
            reach = half_t + 6.0 / self._zoom() / self.px_per_ft
            for a, b in wall.segments:
                d = _point_segment_distance(target, a, b)
                if d < reach and d < best_d:
                    best, best_d = wall.id, d
        self.selected_wall = best
        self.viewport().update()
        if best is not None:
            self.wall_clicked.emit(best)


def _point_distance(a: Point, b: Point) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _point_segment_distance(p: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    raw = 0.0 if denom == 0 else ((px - ax) * dx + (py - ay) * dy) / denom
    t = max(0.0, min(1.0, raw))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def _station_point(
    vertices: list[Point], station: float
) -> tuple[Point, Point] | None:
    """Point and unit direction at a distance along a polyline."""
    remaining = station
    for (ax, ay), (bx, by) in zip(vertices, vertices[1:], strict=False):
        seg = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        if seg == 0:
            continue
        if remaining <= seg:
            t = remaining / seg
            return (ax + t * (bx - ax), ay + t * (by - ay)), (
                (bx - ax) / seg,
                (by - ay) / seg,
            )
        remaining -= seg
    return None
