from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGroupBox, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QWidget, QHeaderView, QAbstractItemView,
    QTabWidget, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
import csv
import os
from datetime import datetime

from view.frames.base_frame import BaseFrame


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return '---'
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return '---'
    return f"{seconds:.1f} s"


def _fmt_ts(iso_str: str | None) -> str:
    if not iso_str:
        return '---'
    try:
        dt = datetime.fromisoformat(iso_str).astimezone()
        return dt.strftime('%H:%M:%S.') + f"{dt.microsecond // 1000:03d}"
    except Exception:
        return iso_str


_TABLE_ROW_H  = 26
_TABLE_HDR_H  = 28
_LABEL_FONT   = QFont()
_LABEL_FONT.setPointSize(10)


def _make_table(headers: list[str], max_rows: int) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.horizontalHeader().setFont(_LABEL_FONT)
    hdr = table.horizontalHeader()
    hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setMinimumHeight(_TABLE_HDR_H + max_rows * _TABLE_ROW_H)
    table.setMaximumHeight(_TABLE_HDR_H + max_rows * _TABLE_ROW_H + 4)
    return table


def _scroll_page(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(inner)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return sa


def _stat_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(_LABEL_FONT)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


class AnalyticsFrame(BaseFrame):
    _REFRESH_MS = 1_000

    def __init__(self, parent=None, db=None):
        self._db = db
        super().__init__(parent)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_db(self, db):
        self._db = db

    def refresh(self):
        if self._db is None:
            return
        self._populate_sensor_table()
        self._populate_t2e_table()
        self._populate_f2t2ea_table()
        self._populate_id_accuracy()
        self._populate_engage_results_table()
        self._populate_losses_table()

    # ------------------------------------------------------------------
    # Widget construction (called by BaseFrame.__init__)
    # ------------------------------------------------------------------

    def create_widgets(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(4, 4, 4, 4)
        outer_layout.setSpacing(4)

        title = QLabel('Performance Analytics')
        title.setFont(QFont('', 11, QFont.Weight.Bold))
        outer_layout.addWidget(title)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        outer_layout.addWidget(tabs, 1)

        # ── Tab 1: Targeting ──────────────────────────────────────────
        t1_inner = QWidget()
        t1_vbox  = QVBoxLayout(t1_inner)
        t1_vbox.setContentsMargins(6, 6, 6, 6)
        t1_vbox.setSpacing(8)

        sensor_group = QGroupBox('Sensor Mode Usage')
        s_vbox = QVBoxLayout(sensor_group)
        self._sensor_table = _make_table(
            ['Sensor', 'Times Enabled', 'Total Duration', '% Mission Time'],
            max_rows=3,
        )
        s_vbox.addWidget(self._sensor_table)
        t1_vbox.addWidget(sensor_group)

        t2e_group = QGroupBox('Time to Detect / Engage  (per target)')
        t2_vbox = QVBoxLayout(t2e_group)
        self._t2e_table = _make_table(
            ['Target', 'First Detected', 'Zone 3', 'Engage Cmd', 'Detect→Z3', 'Detect→Engage'],
            max_rows=5,
        )
        t2_vbox.addWidget(self._t2e_table)
        t1_vbox.addWidget(t2e_group)

        f_group = QGroupBox('F2T2EA Event Rates & Durations')
        f_vbox = QVBoxLayout(f_group)
        self._f2t2ea_table = _make_table(
            ['Target', 'Detect→Z3', 'Z3→Engage', 'Engage→Neut', 'Total F2T2EA'],
            max_rows=5,
        )
        f_vbox.addWidget(self._f2t2ea_table)
        t1_vbox.addWidget(f_group)

        t1_vbox.addStretch(1)
        tabs.addTab(_scroll_page(t1_inner), 'Targeting')

        # ── Tab 2: Results ────────────────────────────────────────────
        t2_inner = QWidget()
        t2_vbox2 = QVBoxLayout(t2_inner)
        t2_vbox2.setContentsMargins(6, 6, 6, 6)
        t2_vbox2.setSpacing(8)

        d_group = QGroupBox('Identification Accuracy')
        d_vbox  = QVBoxLayout(d_group)
        d_vbox.setSpacing(6)
        self._id_conf_label  = _stat_label('Avg CV Confidence (LOCKED):  ---')
        self._id_count_label = _stat_label('Lock samples this mission:    ---')
        d_vbox.addWidget(self._id_conf_label)
        d_vbox.addWidget(self._id_count_label)
        t2_vbox2.addWidget(d_group)

        e_group = QGroupBox('Engagement Success Rate')
        e_vbox  = QVBoxLayout(e_group)
        self._engage_table = _make_table(
            ['Target', 'Engagements', 'Hits', 'Success Rate'],
            max_rows=5,
        )
        e_vbox.addWidget(self._engage_table)
        t2_vbox2.addWidget(e_group)

        l_group = QGroupBox('Losses per Target')
        l_vbox  = QVBoxLayout(l_group)
        self._losses_table = _make_table(
            ['Target', 'Track Losses'],
            max_rows=5,
        )
        l_vbox.addWidget(self._losses_table)
        t2_vbox2.addWidget(l_group)

        t2_vbox2.addStretch(1)
        tabs.addTab(_scroll_page(t2_inner), 'Results')

        # ── Buttons (always visible below tabs) ───────────────────────
        btn_widget  = QWidget()
        btn_layout  = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(0, 2, 0, 0)
        refresh_btn = QPushButton('Refresh')
        refresh_btn.clicked.connect(self.refresh)
        export_btn  = QPushButton('Export CSV')
        export_btn.clicked.connect(self._export_csv)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addWidget(export_btn)
        btn_layout.addStretch()
        outer_layout.addWidget(btn_widget)

        self._schedule_refresh()

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    @staticmethod
    def _insert_row(table: QTableWidget, values: list[str]):
        row = table.rowCount()
        table.insertRow(row)
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, col, item)

    def _populate_sensor_table(self):
        self._sensor_table.setRowCount(0)
        if self._db is None:
            return
        durations = self._db.get_sensor_durations()
        for key, label in (('lidar', 'LiDAR'), ('rf', 'RF'), ('acoustic', 'Acoustic')):
            d = durations.get(key, {})
            self._insert_row(self._sensor_table, [
                label,
                str(d.get('times_enabled', 0)),
                _fmt_duration(d.get('total_seconds')),
                f"{d.get('pct_mission', 0.0):.1f}%",
            ])

    def _populate_t2e_table(self):
        self._t2e_table.setRowCount(0)
        if self._db is None:
            return
        for r in self._db.get_time_to_engage():
            self._insert_row(self._t2e_table, [
                r['rat_id'],
                _fmt_ts(r['detected_at']),
                _fmt_ts(r['zone3_at']),
                _fmt_ts(r['engage_at']),
                _fmt_elapsed(r['detect_to_zone3_s']),
                _fmt_elapsed(r['detect_to_engage_s']),
            ])

    def _populate_f2t2ea_table(self):
        self._f2t2ea_table.setRowCount(0)
        if self._db is None:
            return
        for r in self._db.get_time_to_engage():
            d2z = r.get('detect_to_zone3_s')
            d2e = r.get('detect_to_engage_s')
            e2n = r.get('engage_to_neutralize_s')
            z3_to_engage = (d2e - d2z) if (d2z is not None and d2e is not None) else None
            total        = (d2e + e2n) if (d2e is not None and e2n is not None) else None
            self._insert_row(self._f2t2ea_table, [
                r['rat_id'],
                _fmt_elapsed(d2z),
                _fmt_elapsed(z3_to_engage),
                _fmt_elapsed(e2n),
                _fmt_elapsed(total),
            ])

    def _populate_id_accuracy(self):
        if self._db is None:
            return
        acc = self._db.get_id_accuracy()
        avg = acc['avg_confidence']
        n   = acc['sample_count']
        self._id_conf_label.setText(
            f"Avg CV Confidence (LOCKED):  {f'{avg:.3f}' if avg is not None else '---'}")
        self._id_count_label.setText(f'Lock samples this mission:    {n}')

    def _populate_engage_results_table(self):
        self._engage_table.setRowCount(0)
        if self._db is None:
            return
        for r in self._db.get_engagement_results():
            self._insert_row(self._engage_table, [
                r['rat_id'],
                str(r['engage_count']),
                str(r['neutralized_count']),
                f"{r['success_pct']:.1f}%",
            ])

    def _populate_losses_table(self):
        self._losses_table.setRowCount(0)
        if self._db is None:
            return
        for r in self._db.get_losses_per_target():
            self._insert_row(self._losses_table, [
                r['rat_id'],
                str(r['loss_count']),
            ])

    # ------------------------------------------------------------------
    # Auto-refresh
    # ------------------------------------------------------------------

    def _schedule_refresh(self):
        QTimer.singleShot(self._REFRESH_MS, self._auto_refresh)

    def _auto_refresh(self):
        self.refresh()
        self._schedule_refresh()

    # ------------------------------------------------------------------
    # CSV export (logic unchanged)
    # ------------------------------------------------------------------

    def _export_csv(self):
        if self._db is None:
            return

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        export_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data')
        os.makedirs(export_dir, exist_ok=True)
        path = os.path.abspath(
            os.path.join(export_dir, f'analytics_export_{ts}.csv')
        )

        durations   = self._db.get_sensor_durations()
        t2e_rows    = self._db.get_time_to_engage()
        engage_rows = self._db.get_engagement_results()
        losses_rows = self._db.get_losses_per_target()
        id_acc      = self._db.get_id_accuracy()

        def _fs(v):
            return f"{v:.1f}" if v is not None else '---'

        with open(path, 'w', newline='') as f:
            w = csv.writer(f)

            w.writerow(['Section A — Sensor Mode Usage'])
            w.writerow(['Sensor', 'Times Enabled', 'Total Duration (s)', '% Mission Time'])
            for key, label in (('lidar', 'LiDAR'), ('rf', 'RF'), ('acoustic', 'Acoustic')):
                d = durations.get(key, {})
                w.writerow([
                    label,
                    d.get('times_enabled', 0),
                    f"{d.get('total_seconds', 0.0):.1f}",
                    f"{d.get('pct_mission', 0.0):.1f}",
                ])

            w.writerow([])
            w.writerow(['Section B — Time to Detect / Engage'])
            w.writerow([
                'Target', 'First Detected', 'Reached Zone 3', 'Engage Cmd', 'Neutralized',
                'Detect→Z3 (s)', 'Detect→Engage (s)', 'Engage→Neut (s)',
            ])
            for r in t2e_rows:
                w.writerow([
                    r['rat_id'],
                    _fmt_ts(r['detected_at']),
                    _fmt_ts(r['zone3_at']),
                    _fmt_ts(r['engage_at']),
                    _fmt_ts(r.get('neutralized_at')),
                    _fs(r['detect_to_zone3_s']),
                    _fs(r['detect_to_engage_s']),
                    _fs(r.get('engage_to_neutralize_s')),
                ])

            w.writerow([])
            w.writerow(['Section C — F2T2EA Event Rates & Durations'])
            w.writerow(['Target', 'Detect→Z3 (s)', 'Z3→Engage (s)', 'Engage→Neut (s)', 'Total F2T2EA (s)'])
            for r in t2e_rows:
                d2z = r.get('detect_to_zone3_s')
                d2e = r.get('detect_to_engage_s')
                e2n = r.get('engage_to_neutralize_s')
                z3_to_engage = (d2e - d2z) if (d2z is not None and d2e is not None) else None
                total        = (d2e + e2n) if (d2e is not None and e2n is not None) else None
                w.writerow([r['rat_id'], _fs(d2z), _fs(z3_to_engage), _fs(e2n), _fs(total)])

            w.writerow([])
            w.writerow(['Section D — Identification Accuracy'])
            avg = id_acc['avg_confidence']
            w.writerow(['Avg CV Confidence (LOCKED)', f"{avg:.3f}" if avg is not None else '---'])
            w.writerow(['Lock samples this mission', id_acc['sample_count']])

            w.writerow([])
            w.writerow(['Section E — Engagement Success Rate'])
            w.writerow(['Target', 'Engagements', 'Hits', 'Success Rate (%)'])
            for r in engage_rows:
                w.writerow([
                    r['rat_id'], r['engage_count'], r['neutralized_count'],
                    f"{r['success_pct']:.1f}",
                ])

            w.writerow([])
            w.writerow(['Section F — Losses per Target'])
            w.writerow(['Target', 'Track Losses'])
            for r in losses_rows:
                w.writerow([r['rat_id'], r['loss_count']])

        print(f"Analytics exported to {path}")
