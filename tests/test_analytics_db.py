import time
import pytest
from model.analytics_db import FCPAnalyticsDB


@pytest.fixture
def fresh_db(tmp_path):
    """Unstarted DB — for testing the no-mission guard and mission lifecycle."""
    database = FCPAnalyticsDB(str(tmp_path / 'fresh.db'))
    yield database
    database.close()


class TestMissionLifecycle:
    def test_start_mission_returns_positive_id(self, fresh_db):
        mid = fresh_db.start_mission()
        assert isinstance(mid, int) and mid > 0
        assert fresh_db.mission_id == mid

    def test_end_mission_stamps_end_time(self, fresh_db):
        fresh_db.start_mission()
        fresh_db.end_mission()
        row = fresh_db._conn.execute(
            "SELECT end_time FROM missions WHERE id = ?", (fresh_db.mission_id,)
        ).fetchone()
        assert row['end_time'] is not None

    def test_end_mission_without_start_is_noop(self, fresh_db):
        fresh_db.end_mission()  # must not raise

    def test_log_before_mission_is_noop(self, fresh_db):
        fresh_db.log_rat_event('RAT_001', 'detected', zone=1)
        fresh_db.log_sensor_event('lidar', 'enabled')
        assert fresh_db._conn.execute("SELECT COUNT(*) FROM rat_events").fetchone()[0] == 0
        assert fresh_db._conn.execute("SELECT COUNT(*) FROM sensor_mode_events").fetchone()[0] == 0


class TestRatEventLogging:
    def test_log_detected_event(self, db):
        db.log_rat_event('RAT_001', 'detected', zone=1, az=10.0, el=5.0, range_m=80.0)
        row = db._conn.execute(
            "SELECT * FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchone()
        assert row['event_type'] == 'detected'
        assert row['zone'] == 1

    def test_log_cv_lock_stores_confidence(self, db):
        db.log_rat_event('CV_SYSTEM', 'cv_lock', confidence=0.92)
        row = db._conn.execute(
            "SELECT confidence FROM rat_events WHERE event_type = 'cv_lock'"
        ).fetchone()
        assert abs(row['confidence'] - 0.92) < 1e-6

    def test_naive_timestamp_is_accepted(self, db):
        from datetime import datetime
        naive_ts = datetime.now().isoformat()  # no timezone
        db.log_rat_event('RAT_001', 'detected', zone=1, timestamp=naive_ts)
        rows = db._conn.execute("SELECT * FROM rat_events").fetchall()
        assert len(rows) == 1


class TestGetTimeToEngage:
    def test_full_timing_chain(self, db):
        db.log_rat_event('RAT_001', 'detected', zone=1)
        time.sleep(0.01)
        db.log_rat_event('RAT_001', 'zone_change', zone=3)
        time.sleep(0.01)
        db.log_rat_event('RAT_001', 'engage_commanded')
        time.sleep(0.01)
        db.log_rat_event('RAT_001', 'neutralized')

        rows = db.get_time_to_engage()
        assert len(rows) == 1
        row = rows[0]
        assert row['rat_id'] == 'RAT_001'
        assert row['detect_to_engage_s'] >= 0
        assert row['engage_to_neutralize_s'] >= 0

    def test_partial_timing_returns_none_for_missing(self, db):
        db.log_rat_event('RAT_002', 'detected', zone=1)
        rows = db.get_time_to_engage()
        row = next(r for r in rows if r['rat_id'] == 'RAT_002')
        assert row['engage_at'] is None
        assert row['detect_to_engage_s'] is None

    def test_excludes_cv_system(self, db):
        db.log_rat_event('CV_SYSTEM', 'cv_lock', confidence=0.9)
        rows = db.get_time_to_engage()
        assert all(r['rat_id'] != 'CV_SYSTEM' for r in rows)

    def test_zone3_detected_directly_counts_as_zone3_at(self, db):
        db.log_rat_event('RAT_003', 'detected', zone=3)
        rows = db.get_time_to_engage()
        row = next(r for r in rows if r['rat_id'] == 'RAT_003')
        assert row['zone3_at'] is not None


class TestGetSensorDurations:
    def test_enabled_disabled_pair(self, db):
        db.log_sensor_event('lidar', 'enabled')
        time.sleep(0.05)
        db.log_sensor_event('lidar', 'disabled')
        result = db.get_sensor_durations()
        assert result['lidar']['times_enabled'] == 1
        assert result['lidar']['total_seconds'] >= 0.04

    def test_unclosed_enabled_counts_to_now(self, db):
        db.log_sensor_event('rf', 'enabled')
        result = db.get_sensor_durations()
        assert result['rf']['times_enabled'] == 1
        assert result['rf']['total_seconds'] > 0

    def test_double_enable_ignored(self, db):
        db.log_sensor_event('acoustic', 'enabled')
        db.log_sensor_event('acoustic', 'enabled')  # duplicate
        db.log_sensor_event('acoustic', 'disabled')
        result = db.get_sensor_durations()
        assert result['acoustic']['times_enabled'] == 1

    def test_pct_mission_is_within_bounds(self, db):
        db.log_sensor_event('lidar', 'enabled')
        result = db.get_sensor_durations()
        assert 0.0 <= result['lidar']['pct_mission'] <= 100.0


class TestGetEngagementResults:
    def test_engage_and_neutralize_gives_100_pct(self, db):
        db.log_rat_event('RAT_001', 'engage_commanded')
        db.log_rat_event('RAT_001', 'neutralized')
        rows = db.get_engagement_results()
        row = next(r for r in rows if r['rat_id'] == 'RAT_001')
        assert row['engage_count'] == 1
        assert row['neutralized_count'] == 1
        assert row['success_pct'] == 100.0

    def test_engage_without_neutralize_gives_0_pct(self, db):
        db.log_rat_event('RAT_002', 'engage_commanded')
        rows = db.get_engagement_results()
        row = next(r for r in rows if r['rat_id'] == 'RAT_002')
        assert row['neutralized_count'] == 0
        assert row['success_pct'] == 0.0

    def test_excludes_cv_system(self, db):
        db.log_rat_event('CV_SYSTEM', 'cv_lock', confidence=0.9)
        rows = db.get_engagement_results()
        assert all(r['rat_id'] != 'CV_SYSTEM' for r in rows)


class TestGetIdAccuracy:
    def test_no_cv_locks_returns_none_avg(self, db):
        result = db.get_id_accuracy()
        assert result['avg_confidence'] is None
        assert result['sample_count'] == 0

    def test_single_lock(self, db):
        db.log_rat_event('CV_SYSTEM', 'cv_lock', confidence=0.75)
        result = db.get_id_accuracy()
        assert result['sample_count'] == 1
        assert abs(result['avg_confidence'] - 0.75) < 1e-6

    def test_averages_multiple_locks(self, db):
        db.log_rat_event('CV_SYSTEM', 'cv_lock', confidence=0.8)
        db.log_rat_event('CV_SYSTEM', 'cv_lock', confidence=0.9)
        result = db.get_id_accuracy()
        assert result['sample_count'] == 2
        assert abs(result['avg_confidence'] - 0.85) < 1e-6


class TestGetLossesPerTarget:
    def test_counts_lost_events(self, db):
        db.log_rat_event('RAT_001', 'lost')
        db.log_rat_event('RAT_001', 'lost')
        db.log_rat_event('RAT_002', 'lost')
        by_id = {r['rat_id']: r['loss_count'] for r in db.get_losses_per_target()}
        assert by_id['RAT_001'] == 2
        assert by_id['RAT_002'] == 1

    def test_excludes_cv_system(self, db):
        db.log_rat_event('CV_SYSTEM', 'lost')
        rows = db.get_losses_per_target()
        assert all(r['rat_id'] != 'CV_SYSTEM' for r in rows)

    def test_no_losses_returns_empty(self, db):
        assert db.get_losses_per_target() == []
