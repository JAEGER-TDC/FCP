import math
from PyQt6.QtWidgets import QSizePolicy
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont
from view.frames.base_frame import BaseFrame
from view import theme

# Nodes: (id, role label, fractional x-position)
_NODES = [
    ('DNE', 'Effector',     0.15),
    ('FCP', 'Command Post', 0.50),
    ('DNN', 'Detector',     0.85),
]
_LINKS = [('DNE', 'FCP'), ('FCP', 'DNN')]

_DOT_R               = 7
_RAT_DOT_R           = 10
_RAT_DOT_R_ACTIVE    = 11
_CROSSHAIR_LEN       = 8
_RING_GAPS           = (5, 10)
_FAN_START  = 45   # degrees from east (3-o'clock), counter-clockwise
_FAN_EXTENT = 90   # 90° arc — one quarter-circle per SOW §1.1
_BOX_H      = 130  # fixed box height, sized for 4 content lines at theme fonts
_HPAD       = 10   # horizontal padding so edge boxes don't clip


class MapFrame(BaseFrame):
    def create_widgets(self):
        # DNN health state
        self._dnn_status_flag: str | None = None
        self._dnn_battery: float = 0.0
        self._dnn_temp: float = 0.0
        self._dnn_error: int = 0

        # DNE health state
        self._dne_healthy: bool | None = None
        self._dne_laser_firing: bool = False

        # RAT zone counts {1: n, 2: n, 3: n}
        self._zone_counts: dict[int, int] = {}
        # RAT position snapshot {rat_id: Rat}
        self._rats: dict = {}

        # Engagement state — updated by update_engagement_state()
        self._primary_target_id: str | None = None
        self._engaged_rats: set = set()
        self._neutralized_rats: set[str] = set()

        # Fonts — created after QApplication exists (i.e., here in create_widgets)
        self._font_bold   = QFont(theme.FONT_FAMILY, theme.FONT_SIZE)
        self._font_bold.setBold(True)
        self._font_normal = QFont(theme.FONT_FAMILY, theme.FONT_SIZE)
        self._font_small  = QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 200)

    # ------------------------------------------------------------------
    # Qt paint hook — all drawing happens here; update() triggers a repaint
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        if w < 10 or h < 10:
            return

        painter.fillRect(self.rect(), QColor(theme.MAP_BG))

        fan_h  = int(h * 0.62)
        topo_y = fan_h
        topo_h = h - fan_h

        self._draw_zone_fan(painter, w, fan_h)
        self._draw_network_topology(painter, w, topo_y, topo_h)

    # ------------------------------------------------------------------
    # Public API (called by controller)
    # ------------------------------------------------------------------

    def update_dnn_node(self, node):
        self._dnn_status_flag = node.status_flag
        self._dnn_battery     = node.battery_percent
        self._dnn_temp        = node.temperature_c
        self._dnn_error       = node.error_code
        self.update()

    def update_dne_status(self, healthy: bool, laser_firing: bool):
        self._dne_healthy      = healthy
        self._dne_laser_firing = laser_firing
        self.update()

    def update_zone_counts(self, counts: dict[int, int], rats: dict | None = None):
        self._zone_counts = counts
        if rats is not None:
            self._rats = rats
        self.update()

    def update_engagement_state(self, primary_target_id: str | None, engaged_rats: set):
        self._primary_target_id = primary_target_id
        self._engaged_rats      = engaged_rats
        self.update()

    def update_neutralized_rats(self, neutralized: set[str]):
        self._neutralized_rats = neutralized
        self.update()

    # ------------------------------------------------------------------
    # Color helper
    # ------------------------------------------------------------------

    def _node_color(self, node_id: str) -> str:
        if node_id == 'FCP':
            return theme.STATUS_HEALTHY
        if node_id == 'DNN':
            if self._dnn_status_flag is None:
                return theme.STATUS_UNKNOWN
            if self._dnn_status_flag == 'OK':
                return theme.STATUS_HEALTHY
            if self._dnn_status_flag == 'WARNING':
                return theme.STATUS_WARNING
            return theme.STATUS_ERROR
        if node_id == 'DNE':
            if self._dne_healthy is None:
                return theme.STATUS_UNKNOWN
            return theme.STATUS_HEALTHY if self._dne_healthy else theme.STATUS_ERROR
        return theme.STATUS_UNKNOWN

    # ------------------------------------------------------------------
    # Text helper — draws text centered on (cx, cy)
    # ------------------------------------------------------------------

    def _draw_centered_text(self, painter: QPainter, cx: float, cy: float, text: str):
        fm = painter.fontMetrics()
        x  = cx - fm.horizontalAdvance(text) / 2
        # baseline that places the text's visual centre at cy
        y  = cy + (fm.ascent() - fm.descent()) / 2
        painter.drawText(QPointF(x, y), text)

    # ------------------------------------------------------------------
    # Zone fan
    # ------------------------------------------------------------------

    def _draw_zone_fan(self, painter: QPainter, w: int, fan_h: int):
        cx = w // 2
        cy = fan_h  # origin (home plate) at bottom edge of fan area

        # 90° fan spans 2·sin(45°) ≈ 1.414·r horizontally
        max_r = min(fan_h - 4, int((w - 20) / 1.414))

        r1 = max_r                   # outer  — zone 1, 85 m
        r2 = int(max_r * 60 / 85)   # middle — zone 2, 60 m
        r3 = int(max_r * 30 / 85)   # inner  — zone 3, 30 m

        for r, fill in [(r1, theme.MAP_ZONE1_FILL), (r2, theme.MAP_ZONE2_FILL), (r3, theme.MAP_ZONE3_FILL)]:
            painter.setBrush(QBrush(QColor(fill)))
            painter.setPen(QPen(QColor(theme.MAP_ZONE_BORDER), 2))
            rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            # Qt angles: 1/16-degree units, 0=east, positive=CCW — same convention as Tkinter.
            painter.drawPie(rect, _FAN_START * 16, _FAN_EXTENT * 16)

        # Zone ID centred in each band along the 90° radial (straight up)
        painter.setPen(QPen(QColor(theme.MAP_ZONE_BORDER)))
        painter.setFont(self._font_bold)
        for r_out, r_in, zone in [(r1, r2, 1), (r2, r3, 2), (r3, 0, 3)]:
            mid_r = (r_out + r_in) // 2
            self._draw_centered_text(painter, cx, cy - mid_r, str(zone))

        # RAT dots — color and decoration reflect engagement state
        for rat in self._rats.values():
            az  = rat.az_value
            rng = rat.range_value
            if not (0 < rng <= 85):
                continue
            angle_rad = math.radians(az)
            r_px = rng / 85.0 * max_r
            rx = cx + r_px * math.cos(angle_rad)
            ry = cy - r_px * math.sin(angle_rad)

            if rat.rat_id in self._neutralized_rats:
                painter.setBrush(QBrush(QColor(theme.RAT_NEUTRALIZED)))
                painter.setPen(QPen(QColor(theme.MAP_TEXT), 1))
                painter.drawEllipse(QPointF(rx, ry), _RAT_DOT_R, _RAT_DOT_R)
                d = int(_RAT_DOT_R * 0.65)
                painter.setPen(QPen(QColor(theme.MAP_TEXT), 2))
                painter.drawLine(QPointF(rx - d, ry - d), QPointF(rx + d, ry + d))
                painter.drawLine(QPointF(rx + d, ry - d), QPointF(rx - d, ry + d))
            elif rat.rat_id in self._engaged_rats:
                r = _RAT_DOT_R_ACTIVE
                painter.setBrush(QBrush(QColor(theme.RAT_ENGAGED)))
                painter.setPen(QPen(QColor(theme.MAP_TEXT), 2))
                painter.drawEllipse(QPointF(rx, ry), r, r)
                for gap in _RING_GAPS:
                    rr = r + gap
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(theme.RAT_ENGAGED), 1))
                    painter.drawEllipse(QPointF(rx, ry), rr, rr)
            elif rat.rat_id == self._primary_target_id:
                r = _RAT_DOT_R_ACTIVE
                painter.setBrush(QBrush(QColor(theme.RAT_TRACKING)))
                painter.setPen(QPen(QColor(theme.MAP_TEXT), 2))
                painter.drawEllipse(QPointF(rx, ry), r, r)
                cl = _CROSSHAIR_LEN
                painter.setPen(QPen(QColor(theme.MAP_TEXT), 1))
                painter.drawLine(QPointF(rx - cl, ry), QPointF(rx + cl, ry))
                painter.drawLine(QPointF(rx, ry - cl), QPointF(rx, ry + cl))
            else:
                painter.setBrush(QBrush(QColor(theme.RAT_DETECTED)))
                painter.setPen(QPen(QColor(theme.MAP_TEXT), 1))
                painter.drawEllipse(QPointF(rx, ry), _RAT_DOT_R, _RAT_DOT_R)

        # Legend — top-left corner of fan area
        legend_x, legend_y = _HPAD + 6, 10
        painter.setFont(self._font_small)
        fm = painter.fontMetrics()
        text_offset_y = (fm.ascent() - fm.descent()) / 2  # baseline shift to centre on dot
        for i, (color, label) in enumerate([
            (theme.RAT_DETECTED,    'Detected'),
            (theme.RAT_TRACKING,    'Tracking'),
            (theme.RAT_ENGAGED,     'Engaged'),
            (theme.RAT_NEUTRALIZED, 'Neutralized'),
        ]):
            ly = legend_y + i * 20
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(QPen(QColor(theme.MAP_TEXT), 1))
            painter.drawEllipse(QPointF(legend_x, ly), 5, 5)
            painter.setPen(QPen(QColor(theme.MAP_TEXT)))
            painter.drawText(QPointF(legend_x + 14, ly + text_offset_y), label)

    # ------------------------------------------------------------------
    # Network topology
    # ------------------------------------------------------------------

    def _draw_network_topology(self, painter: QPainter, w: int, topo_y: int, topo_h: int):
        # Work within the padded width so edge boxes clear the canvas border.
        ew = w - 2 * _HPAD
        # Nodes sit at 15/50/85% of ew, offset by _HPAD.
        box_w = min(int(ew * 0.30), int(ew * 0.35) - 8)
        box_h = min(_BOX_H, topo_h - 12)
        cy    = topo_y + topo_h // 2

        centers = {nid: _HPAD + int(ew * frac) for nid, _role, frac in _NODES}

        # Link lines (drawn behind node boxes)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for src, dst in _LINKS:
            src_x      = centers[src] + box_w // 2
            dst_x      = centers[dst] - box_w // 2
            link_color = self._node_color(dst if dst != 'FCP' else src)
            pen = QPen(QColor(link_color), 3)
            if link_color == theme.STATUS_UNKNOWN:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(src_x, cy), QPointF(dst_x, cy))

        # Node boxes
        for nid, role, _ in _NODES:
            cx    = centers[nid]
            color = self._node_color(nid)
            x0 = cx - box_w // 2
            y0 = cy - box_h // 2
            x1 = cx + box_w // 2
            y1 = cy + box_h // 2

            painter.setBrush(QBrush(QColor(theme.MAP_NODE_BG)))
            painter.setPen(QPen(QColor(color), 3))
            painter.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))

            # Header: title (bold) + role subtitle (small)
            painter.setPen(QPen(QColor(theme.MAP_TEXT)))
            painter.setFont(self._font_bold)
            self._draw_centered_text(painter, cx, y0 + 13, nid)

            painter.setPen(QPen(QColor(theme.MAP_NODE_SUBTITLE)))
            painter.setFont(self._font_small)
            self._draw_centered_text(painter, cx, y0 + 31, role)

            # Divider
            painter.setPen(QPen(QColor(theme.MAP_NODE_DIVIDER), 1))
            painter.drawLine(QPointF(x0 + 5, y0 + 43), QPointF(x1 - 5, y0 + 43))

            # Health details below divider
            self._draw_node_content(painter, nid, cx, y0 + 56, y1 - 16)

            # Health dot at bottom centre
            dot_y = y1 - 9
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx, dot_y), _DOT_R, _DOT_R)

    def _draw_node_content(self, painter: QPainter, nid: str, cx: float,
                            start_y: float, max_y: float):
        line_h = 20  # generous line spacing for 12–14 pt fonts

        if nid == 'FCP':
            painter.setFont(self._font_bold)
            painter.setPen(QPen(QColor(theme.STATUS_HEALTHY)))
            self._draw_centered_text(painter, cx, start_y, 'LOCAL')

        elif nid == 'DNN':
            if self._dnn_status_flag is None:
                painter.setFont(self._font_normal)
                painter.setPen(QPen(QColor(theme.MAP_NODE_INACTIVE)))
                self._draw_centered_text(painter, cx, start_y, 'No data')
            else:
                color = self._node_color('DNN')
                lines = [
                    (self._dnn_status_flag,             color,               self._font_bold),
                    (f'Bat: {self._dnn_battery:.0f}%',  theme.MAP_NODE_STAT, self._font_small),
                    (f'Temp: {self._dnn_temp:.0f}°C',   theme.MAP_NODE_STAT, self._font_small),
                    (f'Err: {self._dnn_error}',          theme.MAP_NODE_STAT, self._font_small),
                ]
                for i, (text, fill, font) in enumerate(lines):
                    y = start_y + i * line_h
                    if y < max_y:
                        painter.setFont(font)
                        painter.setPen(QPen(QColor(fill)))
                        self._draw_centered_text(painter, cx, y, text)

        elif nid == 'DNE':
            if self._dne_healthy is None:
                painter.setFont(self._font_normal)
                painter.setPen(QPen(QColor(theme.MAP_NODE_INACTIVE)))
                self._draw_centered_text(painter, cx, start_y, 'Disconnected')
            else:
                h_color = theme.STATUS_HEALTHY if self._dne_healthy else theme.STATUS_ERROR
                h_text  = 'HEALTHY' if self._dne_healthy else 'UNHEALTHY'
                l_color = theme.STATUS_ERROR if self._dne_laser_firing else theme.MAP_NODE_INACTIVE
                l_text  = 'FIRING' if self._dne_laser_firing else 'INACTIVE'
                lines = [
                    (h_text,             h_color, self._font_bold),
                    (f'Laser: {l_text}', l_color, self._font_small),
                ]
                for i, (text, fill, font) in enumerate(lines):
                    y = start_y + i * line_h
                    if y < max_y:
                        painter.setFont(font)
                        painter.setPen(QPen(QColor(fill)))
                        self._draw_centered_text(painter, cx, y, text)
