from model.rat_model import Rat
from model.node_model import Node
from conftest import make_rat


class TestRat:
    def test_parses_positional_message(self):
        data = {
            'rat_id': 'RAT_001',
            'zone': 2,
            'values': {'az_value': 10.5, 'el_value': 3.2, 'range_value': 75.0},
            'rates':  {'az_rate': 0.1,   'el_rate': 0.0,  'range_rate': -0.5},
        }
        rat = Rat(data)
        assert rat.rat_id == 'RAT_001'
        assert rat.zone == 2
        assert rat.az_value == 10.5
        assert rat.el_value == 3.2
        assert rat.range_value == 75.0
        assert rat.az_rate == 0.1
        assert rat.range_rate == -0.5

    def test_defaults_on_empty_dict(self):
        rat = Rat({})
        assert rat.rat_id == ''
        assert rat.zone == 0
        assert rat.az_value == 0.0
        assert rat.range_value == 0.0

    def test_zone_defaults_to_int_not_str(self):
        rat = Rat({})
        assert type(rat.zone) is int

    def test_missing_nested_dicts_default_to_zero(self):
        rat = Rat({'rat_id': 'X', 'zone': 1})
        assert rat.az_value == 0.0
        assert rat.az_rate == 0.0


class TestNode:
    def test_parses_health_message(self):
        data = {
            'health': {
                'battery_percent': 85.5,
                'temperature_c': 42.1,
                'error_code': 0,
                'status_flag': 'OK',
            }
        }
        node = Node(data)
        assert node.battery_percent == 85.5
        assert node.temperature_c == 42.1
        assert node.error_code == 0
        assert node.status_flag == 'OK'

    def test_defaults_on_empty_dict(self):
        node = Node({})
        assert node.battery_percent == 0.0
        assert node.temperature_c == 0.0
        assert node.error_code == 0
        assert node.status_flag == ''


class TestFCPModel:
    def test_sensor_enabled_by_default(self, model):
        assert model.lidar_enabled is True
        assert model.rf_enabled is True
        assert model.acoustic_enabled is True

    def test_set_lidar_enabled(self, model):
        model.set_lidar_enabled(False)
        assert model.lidar_enabled is False
        model.set_lidar_enabled(True)
        assert model.lidar_enabled is True

    def test_set_rf_enabled(self, model):
        model.set_rf_enabled(False)
        assert model.rf_enabled is False

    def test_set_acoustic_enabled(self, model):
        model.set_acoustic_enabled(False)
        assert model.acoustic_enabled is False

    def test_update_rat_adds_to_dict(self, model):
        rat = make_rat('A', zone=1)
        model.update_rat(rat)
        assert 'A' in model.rats
        assert model.rats['A'] is rat

    def test_update_rat_overwrites_existing(self, model):
        r1 = make_rat('A', zone=1)
        r2 = make_rat('A', zone=2)
        model.update_rat(r1)
        model.update_rat(r2)
        assert model.rats['A'].zone == 2

    def test_remove_rat_deletes_from_dict(self, model):
        model.update_rat(make_rat('A', zone=1))
        model.remove_rat('A')
        assert 'A' not in model.rats

    def test_remove_nonexistent_rat_is_noop(self, model):
        model.remove_rat('NONEXISTENT')  # must not raise
