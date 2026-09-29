"""Replay input preparation, independent of openpilot and its process runner."""
from copy import deepcopy
from types import SimpleNamespace
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "replay_ars510", Path(__file__).resolve().parents[1] / "tools/openpilot_replay/process_replay_ars510.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


class Event:
    def __init__(self, source, firmware, longitudinal):
        self.carParams = SimpleNamespace(fingerprintSource=source, carFw=firmware,
                                        openpilotLongitudinalControl=longitudinal,
                                        carFingerprint="test_car", flags=4096)

    def which(self):
        return "carParams"

    def as_builder(self):
        return deepcopy(self)

    def as_reader(self):
        return self


@pytest.mark.parametrize("source", ["fixed", "can", "fw"])
@pytest.mark.parametrize("has_fw", [False, True])
@pytest.mark.parametrize("longitudinal", [False, True])
def test_logged_firmware_is_reused_without_mutating_original(source, has_fw, longitudinal):
    original = Event(source, [b"test_fw"] if has_fw else [], longitudinal)
    unrelated = SimpleNamespace(which=lambda: "can")
    msgs = [unrelated, original]
    replay.prepare_car_params_for_replay(msgs)
    cp = msgs[1].carParams
    assert cp.fingerprintSource == ("fw" if has_fw else source)
    assert not cp.openpilotLongitudinalControl
    assert cp.carFw == original.carParams.carFw
    assert cp.flags == 4096 and cp.carFingerprint == "test_car"
    assert original.carParams.fingerprintSource == source
    assert original.carParams.openpilotLongitudinalControl == longitudinal
    assert msgs[0] is unrelated
