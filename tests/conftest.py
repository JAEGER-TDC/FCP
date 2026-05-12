import configparser
import pytest
from unittest.mock import MagicMock, patch

from model.analytics_db import FCPAnalyticsDB
from model.fcp_model import FCPModel
from model.rat_model import Rat
from model.node_model import Node
from controller.fcp_controller import FCPController


def _make_config():
    cfg = configparser.ConfigParser()
    cfg['DNN.recv.connection'] = {'ip': '0.0.0.0', 'port': '5000'}
    cfg['DNN.send.connection'] = {'ip': '127.0.0.1', 'port': '5001'}
    cfg['DNE.serial'] = {'port': 'loop://', 'baudrate': '115200'}
    cfg['DNN.health.thresholds'] = {
        'battery_low': '20.0',
        'battery_critical': '10.0',
        'temperature_high': '70.0',
    }
    return cfg


def make_rat(rat_id: str, zone: int, range_value: float = 100.0) -> Rat:
    return Rat({
        'rat_id': rat_id,
        'zone': zone,
        'values': {'az_value': 0.0, 'el_value': 0.0, 'range_value': range_value},
        'rates':  {'az_rate': 0.0, 'el_rate': 0.0, 'range_rate': 0.0},
    })


def make_node(battery: float = 50.0, temp: float = 30.0,
              error: int = 0, flag: str = 'OK') -> Node:
    return Node({
        'health': {
            'battery_percent': battery,
            'temperature_c': temp,
            'error_code': error,
            'status_flag': flag,
        }
    })


def _make_view() -> MagicMock:
    view = MagicMock()

    def _after(delay, cb=None):
        # Execute only immediate callbacks so that scheduling calls (delay > 0)
        # don't recurse and don't fire prematurely in tests.
        if delay == 0 and callable(cb):
            cb()

    view.after.side_effect = _after
    return view


@pytest.fixture
def db(tmp_path):
    database = FCPAnalyticsDB(str(tmp_path / 'test.db'))
    database.start_mission()
    yield database
    database.close()


@pytest.fixture
def model(db):
    return FCPModel(analytics_db=db)


@pytest.fixture
def controller(model):
    view = _make_view()
    with (
        patch.object(FCPController, 'read_config', return_value=_make_config()),
        patch('controller.fcp_controller.CVEngineSimulator'),
        patch.object(FCPController, '_start_udp_listener'),
        patch.object(FCPController, '_start_dne_serial'),
    ):
        ctrl = FCPController(model, view)
    # Clear call history accumulated during __init__ so test assertions start clean.
    view.after.reset_mock(side_effect=False)
    return ctrl
