import sqlite3
import os
from datetime import datetime, timezone


_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'analytics.db')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time   TEXT
);

CREATE TABLE IF NOT EXISTS rat_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER NOT NULL REFERENCES missions(id),
    rat_id     TEXT    NOT NULL,
    event_type TEXT    NOT NULL,
    event_time TEXT    NOT NULL,
    zone       INTEGER,
    az         REAL,
    el         REAL,
    range_m    REAL
);

CREATE TABLE IF NOT EXISTS sensor_mode_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id  INTEGER NOT NULL REFERENCES missions(id),
    sensor_type TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    event_time  TEXT    NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_utc_iso(ts: str | None) -> str:
    """Normalise a timestamp string to a UTC-aware ISO string.

    The DNN simulator sends naive timestamps (datetime.now().isoformat() with
    no timezone). _now_iso() returns UTC-aware ones. Mixing the two in
    arithmetic raises TypeError, so we standardise at write time.

    Naive timestamps are interpreted as local system time and converted to UTC
    via astimezone(). Using replace(tzinfo=utc) would mislabel them as UTC
    without converting, producing wrong values on non-UTC machines.
    """
    if ts is None:
        return _now_iso()
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.astimezone(timezone.utc)   # local → UTC (not just a label)
        return dt.isoformat()
    except (ValueError, TypeError):
        return _now_iso()


class FCPAnalyticsDB:
    """
    Thin SQLite wrapper for F2T2EA performance analytics.

    All timestamps are stored as ISO-8601 UTC strings so they survive
    application restarts and can be parsed back with datetime.fromisoformat().

    Usage
    -----
    db = FCPAnalyticsDB()
    db.start_mission()
    ...
    db.log_sensor_event('lidar', 'enabled')
    db.log_rat_event('RAT_001', 'detected', zone=1, az=12.3, el=5.0, range_m=800.0)
    ...
    db.end_mission()
    """

    def __init__(self, db_path: str = _DB_PATH):
        self._db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")   # safe for concurrent reads
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

        # Safe migration: add confidence column if upgrading an existing DB
        try:
            self._conn.execute("ALTER TABLE rat_events ADD COLUMN confidence REAL")
            self._conn.commit()
        except Exception:
            pass  # column already exists

        self._mission_id: int | None = None

    # ------------------------------------------------------------------
    # Mission lifecycle
    # ------------------------------------------------------------------

    def start_mission(self) -> int:
        """Open a new mission row and cache its id. Returns mission id."""
        cur = self._conn.execute(
            "INSERT INTO missions (start_time) VALUES (?)", (_now_iso(),)
        )
        self._conn.commit()
        self._mission_id = cur.lastrowid
        return self._mission_id

    def end_mission(self):
        """Stamp the current mission's end_time."""
        if self._mission_id is None:
            return
        self._conn.execute(
            "UPDATE missions SET end_time = ? WHERE id = ?",
            (_now_iso(), self._mission_id),
        )
        self._conn.commit()

    @property
    def mission_id(self) -> int | None:
        return self._mission_id

    # ------------------------------------------------------------------
    # Event logging
    # ------------------------------------------------------------------

    def log_rat_event(
        self,
        rat_id: str,
        event_type: str,
        zone: int | None = None,
        az: float | None = None,
        el: float | None = None,
        range_m: float | None = None,
        timestamp: str | None = None,
        confidence: float | None = None,
    ):
        """
        Log a RAT lifecycle event.

        event_type values: 'detected' | 'zone_change' | 'engage_commanded' | 'lost'
                           'neutralized' | 'cv_lock'
        confidence: CV model confidence score (stored for cv_lock events)
        """
        if self._mission_id is None:
            return
        self._conn.execute(
            """INSERT INTO rat_events
               (mission_id, rat_id, event_type, event_time, zone, az, el, range_m, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self._mission_id,
                rat_id,
                event_type,
                _to_utc_iso(timestamp),
                zone,
                az,
                el,
                range_m,
                confidence,
            ),
        )
        self._conn.commit()

    def log_sensor_event(self, sensor_type: str, event_type: str, timestamp: str | None = None):
        """
        Log a sensor mode change.

        sensor_type: 'lidar' | 'rf' | 'acoustic'
        event_type:  'enabled' | 'disabled'
        """
        if self._mission_id is None:
            return
        self._conn.execute(
            """INSERT INTO sensor_mode_events
               (mission_id, sensor_type, event_type, event_time)
               VALUES (?, ?, ?, ?)""",
            (self._mission_id, sensor_type, event_type, _to_utc_iso(timestamp)),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_sensor_durations(self, mission_id: int | None = None) -> dict:
        """
        Compute total enabled-duration (seconds) per sensor for a mission.

        Pairs consecutive 'enabled'/'disabled' events in chronological order.
        An 'enabled' with no following 'disabled' is treated as still-active
        and measured against now.

        Returns:
            {
              'lidar':    {'times_enabled': N, 'total_seconds': F, 'pct_mission': F},
              'rf':       {...},
              'acoustic': {...},
            }
        """
        mid = mission_id or self._mission_id
        result = {}

        mission_start, mission_end = self._mission_bounds(mid)
        mission_duration = 0.0

        if mission_end is not None:
            mission_duration = (mission_end - mission_start).total_seconds()
        else:
            mission_duration = (datetime.now(timezone.utc) - mission_start).total_seconds()

        for sensor in ('lidar', 'rf', 'acoustic'):
            rows = self._conn.execute(
                """SELECT event_type, event_time FROM sensor_mode_events
                   WHERE mission_id = ? AND sensor_type = ?
                   ORDER BY event_time ASC""",
                (mid, sensor),
            ).fetchall()

            total_s = 0.0
            times_enabled = 0
            pending_enable: datetime | None = None

            for row in rows:
                t = datetime.fromisoformat(row['event_time'])
                if row['event_type'] == 'enabled':
                    if pending_enable is None:   # ignore double-enables
                        pending_enable = t
                        times_enabled += 1
                elif row['event_type'] == 'disabled':
                    if pending_enable is not None:
                        total_s += (t - pending_enable).total_seconds()
                        pending_enable = None

            # still active at mission end
            if pending_enable is not None:
                cap = mission_end if mission_end else datetime.now(timezone.utc)
                total_s += (cap - pending_enable).total_seconds()

            pct = (total_s / mission_duration * 100.0) if mission_duration > 0 else 0.0
            result[sensor] = {
                'times_enabled': times_enabled,
                'total_seconds': total_s,
                'pct_mission': pct,
            }

        return result

    def get_time_to_engage(self, mission_id: int | None = None) -> list[dict]:
        """
        Return per-RAT timing rows for a mission.

        Each row:
            rat_id, detected_at, zone3_at, engage_at, neutralized_at,
            detect_to_zone3_s, detect_to_engage_s, engage_to_neutralize_s
        Missing timestamps are returned as None; elapsed values as None too.
        Excludes pseudo-RAT 'CV_SYSTEM' used for internal CV lock logging.
        """
        mid = mission_id or self._mission_id
        rows = self._conn.execute(
            """SELECT rat_id, event_type, MIN(event_time) AS first_time
               FROM rat_events
               WHERE mission_id = ? AND rat_id != 'CV_SYSTEM'
               GROUP BY rat_id, event_type
               ORDER BY rat_id, first_time""",
            (mid,),
        ).fetchall()

        # Aggregate by rat_id
        by_rat: dict[str, dict] = {}
        for row in rows:
            rid = row['rat_id']
            if rid not in by_rat:
                by_rat[rid] = {}
            by_rat[rid][row['event_type']] = row['first_time']

        result = []
        for rat_id, events in by_rat.items():
            detected_str    = events.get('detected')
            zone3_str       = self._first_zone3_time(mid, rat_id)
            engage_str      = events.get('engage_commanded')
            neutralized_str = events.get('neutralized')

            detected_dt    = datetime.fromisoformat(detected_str)    if detected_str    else None
            zone3_dt       = datetime.fromisoformat(zone3_str)        if zone3_str       else None
            engage_dt      = datetime.fromisoformat(engage_str)       if engage_str      else None
            neutralized_dt = datetime.fromisoformat(neutralized_str)  if neutralized_str else None

            detect_to_zone3       = (zone3_dt       - detected_dt).total_seconds() if (detected_dt  and zone3_dt)       else None
            detect_to_engage      = (engage_dt      - detected_dt).total_seconds() if (detected_dt  and engage_dt)      else None
            engage_to_neutralize  = (neutralized_dt - engage_dt).total_seconds()   if (engage_dt    and neutralized_dt) else None

            result.append({
                'rat_id':                 rat_id,
                'detected_at':            detected_str,
                'zone3_at':               zone3_str,
                'engage_at':              engage_str,
                'neutralized_at':         neutralized_str,
                'detect_to_zone3_s':      detect_to_zone3,
                'detect_to_engage_s':     detect_to_engage,
                'engage_to_neutralize_s': engage_to_neutralize,
            })

        result.sort(key=lambda r: r['detected_at'] or '')
        return result

    def get_engagement_results(self, mission_id: int | None = None) -> list[dict]:
        """
        Return per-RAT engagement outcome counts for a mission.

        Each row: rat_id, engage_count, neutralized_count, success_pct
        """
        mid = mission_id or self._mission_id
        rows = self._conn.execute(
            """SELECT rat_id,
                      SUM(CASE WHEN event_type = 'engage_commanded' THEN 1 ELSE 0 END) AS engage_count,
                      SUM(CASE WHEN event_type = 'neutralized'      THEN 1 ELSE 0 END) AS neutralized_count
               FROM rat_events
               WHERE mission_id = ?
                 AND rat_id != 'CV_SYSTEM'
                 AND event_type IN ('engage_commanded', 'neutralized')
               GROUP BY rat_id
               ORDER BY rat_id""",
            (mid,),
        ).fetchall()
        result = []
        for row in rows:
            eng  = row['engage_count']     or 0
            neut = row['neutralized_count'] or 0
            pct  = (neut / eng * 100.0) if eng > 0 else 0.0
            result.append({
                'rat_id':           row['rat_id'],
                'engage_count':     eng,
                'neutralized_count': neut,
                'success_pct':      pct,
            })
        return result

    def get_id_accuracy(self, mission_id: int | None = None) -> dict:
        """
        Return average CV confidence score from LOCKED-state samples.

        Returns: {'avg_confidence': float | None, 'sample_count': int}
        """
        mid = mission_id or self._mission_id
        row = self._conn.execute(
            """SELECT AVG(confidence) AS avg_conf, COUNT(*) AS n
               FROM rat_events
               WHERE mission_id = ? AND event_type = 'cv_lock' AND confidence IS NOT NULL""",
            (mid,),
        ).fetchone()
        avg  = float(row['avg_conf']) if row and row['avg_conf'] is not None else None
        n    = int(row['n'])          if row else 0
        return {'avg_confidence': avg, 'sample_count': n}

    def get_losses_per_target(self, mission_id: int | None = None) -> list[dict]:
        """
        Return number of tracking-loss events per RAT for a mission.

        Each row: rat_id, loss_count
        """
        mid = mission_id or self._mission_id
        rows = self._conn.execute(
            """SELECT rat_id, COUNT(*) AS loss_count
               FROM rat_events
               WHERE mission_id = ? AND event_type = 'lost' AND rat_id != 'CV_SYSTEM'
               GROUP BY rat_id
               ORDER BY loss_count DESC""",
            (mid,),
        ).fetchall()
        return [{'rat_id': row['rat_id'], 'loss_count': row['loss_count']} for row in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _mission_bounds(self, mission_id: int | None):
        """Return (start_datetime, end_datetime | None) for a mission."""
        if mission_id is None:
            return None, None
        row = self._conn.execute(
            "SELECT start_time, end_time FROM missions WHERE id = ?", (mission_id,)
        ).fetchone()
        if not row:
            return None, None
        start = datetime.fromisoformat(row['start_time']) if row['start_time'] else None
        end   = datetime.fromisoformat(row['end_time'])   if row['end_time']   else None
        return start, end

    def _first_zone3_time(self, mission_id: int, rat_id: str) -> str | None:
        """Return ISO timestamp of first time a RAT was in zone 3.

        Covers both zone_change events (RAT transitioned into zone 3) and
        detected events where the RAT was first seen already in zone 3.
        """
        row = self._conn.execute(
            """SELECT MIN(event_time) AS t FROM rat_events
               WHERE mission_id = ? AND rat_id = ? AND zone = 3
                 AND event_type IN ('zone_change', 'detected')""",
            (mission_id, rat_id),
        ).fetchone()
        return row['t'] if row else None

    def close(self):
        self._conn.close()
