import time
from conftest import make_rat, make_node


class TestSelectPrimaryTarget:
    def test_no_rats_returns_none(self, controller):
        assert controller._select_primary_target() is None

    def test_zone1_only_returns_none(self, controller):
        controller.model.rats = {'A': make_rat('A', zone=1)}
        assert controller._select_primary_target() is None

    def test_zone2_rat_selected(self, controller):
        controller.model.rats = {'A': make_rat('A', zone=2, range_value=50.0)}
        assert controller._select_primary_target() == 'A'

    def test_closest_zone2_preferred(self, controller):
        controller.model.rats = {
            'A': make_rat('A', zone=2, range_value=80.0),
            'B': make_rat('B', zone=2, range_value=40.0),
        }
        assert controller._select_primary_target() == 'B'

    def test_zone3_preferred_over_zone2(self, controller):
        controller.model.rats = {
            'A': make_rat('A', zone=2, range_value=10.0),
            'B': make_rat('B', zone=3, range_value=90.0),
        }
        assert controller._select_primary_target() == 'B'

    def test_closest_zone3_preferred(self, controller):
        controller.model.rats = {
            'A': make_rat('A', zone=3, range_value=60.0),
            'B': make_rat('B', zone=3, range_value=25.0),
        }
        assert controller._select_primary_target() == 'B'

    def test_sticky_current_zone3_target(self, controller):
        # 'B' is the current target and is in zone 3; 'A' is closer but not sticky.
        controller.model.rats = {
            'A': make_rat('A', zone=3, range_value=25.0),
            'B': make_rat('B', zone=3, range_value=60.0),
        }
        controller.model.primary_target_id = 'B'
        assert controller._select_primary_target() == 'B'

    def test_sticky_not_applied_when_current_leaves_zone3(self, controller):
        controller.model.rats = {
            'A': make_rat('A', zone=2, range_value=25.0),
            'B': make_rat('B', zone=3, range_value=60.0),
        }
        controller.model.primary_target_id = 'A'  # A dropped to zone 2
        assert controller._select_primary_target() == 'B'

    def test_returns_none_when_current_primary_no_longer_exists(self, controller):
        controller.model.rats = {}
        controller.model.primary_target_id = 'GONE'
        assert controller._select_primary_target() is None


class TestHandleRatAnalytics:
    def test_first_detection_logged_and_tracked(self, controller):
        rat = make_rat('RAT_001', zone=1)
        controller._handle_rat_analytics(rat, None)
        assert 'RAT_001' in controller._known_rats
        rows = controller.model.analytics_db._conn.execute(
            "SELECT event_type FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchall()
        assert any(r['event_type'] == 'detected' for r in rows)

    def test_second_message_same_zone_no_zone_change(self, controller):
        rat = make_rat('RAT_001', zone=1)
        controller._handle_rat_analytics(rat, None)
        controller._handle_rat_analytics(rat, None)
        rows = controller.model.analytics_db._conn.execute(
            "SELECT event_type FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchall()
        assert sum(1 for r in rows if r['event_type'] == 'zone_change') == 0

    def test_zone_advance_logged(self, controller):
        controller._handle_rat_analytics(make_rat('RAT_001', zone=1), None)
        controller._handle_rat_analytics(make_rat('RAT_001', zone=2), None)
        rows = controller.model.analytics_db._conn.execute(
            "SELECT event_type, zone FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchall()
        assert any(r['event_type'] == 'zone_change' and r['zone'] == 2 for r in rows)

    def test_zone_retreat_logged(self, controller):
        controller._handle_rat_analytics(make_rat('RAT_001', zone=2), None)
        controller._handle_rat_analytics(make_rat('RAT_001', zone=1), None)
        rows = controller.model.analytics_db._conn.execute(
            "SELECT event_type, zone FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchall()
        assert any(r['event_type'] == 'zone_change' and r['zone'] == 1 for r in rows)

    def test_auto_disengage_on_zone3_exit(self, controller):
        controller.model.engaged_rats.add('RAT_001')
        controller._handle_rat_analytics(make_rat('RAT_001', zone=3), None)
        controller._handle_rat_analytics(make_rat('RAT_001', zone=2), None)
        assert 'RAT_001' not in controller.model.engaged_rats
        rows = controller.model.analytics_db._conn.execute(
            "SELECT event_type FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchall()
        assert any(r['event_type'] == 'disengage_zone_exit' for r in rows)

    def test_no_disengage_if_not_engaged(self, controller):
        # RAT is not engaged; dropping from zone 3 should not log disengage_zone_exit.
        controller._handle_rat_analytics(make_rat('RAT_001', zone=3), None)
        controller._handle_rat_analytics(make_rat('RAT_001', zone=2), None)
        rows = controller.model.analytics_db._conn.execute(
            "SELECT event_type FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchall()
        assert not any(r['event_type'] == 'disengage_zone_exit' for r in rows)


class TestEvaluateNodeHealthAlerts:
    def test_first_message_establishes_baseline_no_alerts(self, controller):
        controller._evaluate_node_health_alerts(make_node(battery=80.0))
        assert controller.model.dnn_node_prev['battery_percent'] == 80.0
        controller.view.after.assert_not_called()

    def test_battery_low_crossing_fires_alert(self, controller):
        controller._evaluate_node_health_alerts(make_node(battery=50.0))  # baseline
        controller.view.after.reset_mock(side_effect=False)
        controller._evaluate_node_health_alerts(make_node(battery=15.0))  # below low (20%)
        controller.view.after.assert_called()

    def test_battery_critical_fires_exactly_one_alert(self, controller):
        # Jumping from healthy straight to critical should fire critical only, not critical + low.
        controller._evaluate_node_health_alerts(make_node(battery=50.0))
        controller.view.after.reset_mock(side_effect=False)
        controller._evaluate_node_health_alerts(make_node(battery=5.0))   # below critical (10%)
        assert controller.view.after.call_count == 1

    def test_no_alert_when_battery_already_below_threshold(self, controller):
        # Crossing happens only on the downward transition, not while already below.
        controller._evaluate_node_health_alerts(make_node(battery=15.0))  # baseline at low
        controller.view.after.reset_mock(side_effect=False)
        controller._evaluate_node_health_alerts(make_node(battery=12.0))  # still below low
        controller.view.after.assert_not_called()

    def test_temperature_high_crossing_fires_alert(self, controller):
        controller._evaluate_node_health_alerts(make_node(temp=50.0))
        controller.view.after.reset_mock(side_effect=False)
        controller._evaluate_node_health_alerts(make_node(temp=80.0))  # above 70°C
        controller.view.after.assert_called()

    def test_error_code_appearing_fires_alert(self, controller):
        controller._evaluate_node_health_alerts(make_node(error=0))
        controller.view.after.reset_mock(side_effect=False)
        controller._evaluate_node_health_alerts(make_node(error=5))
        controller.view.after.assert_called()

    def test_error_code_clearing_fires_alert(self, controller):
        controller._evaluate_node_health_alerts(make_node(error=5))
        controller.view.after.reset_mock(side_effect=False)
        controller._evaluate_node_health_alerts(make_node(error=0))
        controller.view.after.assert_called()

    def test_status_flag_change_fires_alert(self, controller):
        controller._evaluate_node_health_alerts(make_node(flag='OK'))
        controller.view.after.reset_mock(side_effect=False)
        controller._evaluate_node_health_alerts(make_node(flag='ERROR'))
        controller.view.after.assert_called()

    def test_no_alert_on_identical_state(self, controller):
        node = make_node(battery=80.0, temp=30.0, error=0, flag='OK')
        controller._evaluate_node_health_alerts(node)
        controller.view.after.reset_mock(side_effect=False)
        controller._evaluate_node_health_alerts(node)
        controller.view.after.assert_not_called()

    def test_snapshot_updated_after_each_call(self, controller):
        controller._evaluate_node_health_alerts(make_node(battery=80.0))
        controller._evaluate_node_health_alerts(make_node(battery=60.0))
        assert controller.model.dnn_node_prev['battery_percent'] == 60.0


class TestCheckStaleness:
    def test_fresh_rat_not_removed(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=1))
        controller._rat_last_seen['RAT_001'] = time.time()
        controller._check_staleness()
        assert 'RAT_001' in controller.model.rats

    def test_stale_rat_removed(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=1))
        controller._known_rats.add('RAT_001')
        controller._rat_last_seen['RAT_001'] = time.time() - 20.0
        controller._check_staleness()
        assert 'RAT_001' not in controller.model.rats

    def test_stale_rat_logged_as_lost(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=1))
        controller._rat_last_seen['RAT_001'] = time.time() - 20.0
        controller._check_staleness()
        rows = controller.model.analytics_db._conn.execute(
            "SELECT event_type FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchall()
        assert any(r['event_type'] == 'lost' for r in rows)

    def test_stale_rat_clears_primary_target(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=2))
        controller.model.primary_target_id = 'RAT_001'
        controller._rat_last_seen['RAT_001'] = time.time() - 20.0
        controller._check_staleness()
        # After staleness removal and re-selection with empty rats, primary is None.
        assert controller.model.primary_target_id is None

    def test_stale_rat_removed_from_engaged_set(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=3))
        controller.model.engaged_rats.add('RAT_001')
        controller._rat_last_seen['RAT_001'] = time.time() - 20.0
        controller._check_staleness()
        assert 'RAT_001' not in controller.model.engaged_rats

    def test_stale_rat_clears_pending_engagement(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=2))
        controller.model.pending_engage_rat_id = 'RAT_001'
        controller._rat_last_seen['RAT_001'] = time.time() - 20.0
        controller._check_staleness()
        assert controller.model.pending_engage_rat_id is None

    def test_dnn_offline_alert_when_health_silent(self, controller):
        # 15 seconds of silence; threshold is 10 seconds.
        controller._dnn_last_health_time = time.time() - 15.0
        controller._check_staleness()
        controller.view.alert_frame.add_alert.assert_called()

    def test_dnn_offline_alert_not_repeated(self, controller):
        controller._dnn_last_health_time = time.time() - 15.0
        controller._check_staleness()
        call_count_after_first = controller.view.alert_frame.add_alert.call_count
        controller._check_staleness()
        assert controller.view.alert_frame.add_alert.call_count == call_count_after_first


class TestEngageRat:
    def test_adds_rat_to_engaged_set(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=3))
        controller.engage_rat('RAT_001')
        assert 'RAT_001' in controller.model.engaged_rats

    def test_logs_engage_commanded_event(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=3))
        controller.engage_rat('RAT_001')
        rows = controller.model.analytics_db._conn.execute(
            "SELECT event_type FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchall()
        assert any(r['event_type'] == 'engage_commanded' for r in rows)


class TestCancelPendingEngagement:
    def test_clears_pending_engage_id(self, controller):
        controller.model.pending_engage_rat_id = 'RAT_001'
        controller.cancel_pending_engagement()
        assert controller.model.pending_engage_rat_id is None

    def test_noop_when_already_none(self, controller):
        controller.model.pending_engage_rat_id = None
        controller.cancel_pending_engagement()  # must not raise
        assert controller.model.pending_engage_rat_id is None


class TestStopEngagement:
    def test_removes_primary_from_engaged_set(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=3))
        controller.model.primary_target_id = 'RAT_001'
        controller.model.engaged_rats.add('RAT_001')
        controller.stop_engagement()
        assert 'RAT_001' not in controller.model.engaged_rats

    def test_logs_engage_cancelled_when_was_engaged(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=3))
        controller.model.primary_target_id = 'RAT_001'
        controller.model.engaged_rats.add('RAT_001')
        controller.stop_engagement()
        rows = controller.model.analytics_db._conn.execute(
            "SELECT event_type FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchall()
        assert any(r['event_type'] == 'engage_cancelled' for r in rows)

    def test_no_log_when_not_engaged(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=3))
        controller.model.primary_target_id = 'RAT_001'
        # Not in engaged_rats
        controller.stop_engagement()
        rows = controller.model.analytics_db._conn.execute(
            "SELECT event_type FROM rat_events WHERE rat_id = 'RAT_001'"
        ).fetchall()
        assert not any(r['event_type'] == 'engage_cancelled' for r in rows)

    def test_clears_pending_engagement(self, controller):
        controller.model.update_rat(make_rat('RAT_001', zone=1))
        controller.model.primary_target_id = 'RAT_001'
        controller.model.pending_engage_rat_id = 'RAT_001'
        controller.stop_engagement()
        assert controller.model.pending_engage_rat_id is None

    def test_noop_when_no_primary(self, controller):
        controller.model.primary_target_id = None
        controller.stop_engagement()  # must not raise
