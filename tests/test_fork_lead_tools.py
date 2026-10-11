"""The parts of tools/fork_lead that need no fork checkout: the braking-demand proxy and the source loader."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "fork_lead"))

import forksim  # noqa: E402


def lead_path(x0: float, v: float, a: float = 0.0) -> "np.ndarray":
    """A lead on the MPC's time grid: constant acceleration from (x0, v), speed floored at 0."""
    t = forksim.MPC_T
    vt = np.clip(v + a * t, 0.0, None)
    xt = x0 + np.cumsum(np.diff(t, prepend=0.0) * vt)
    return np.column_stack([xt, vt])


def test_pace_matched_lead_at_nominal_spacing_asks_for_nothing():
    assert forksim.nominal_demand(lead_path(50.0, 30.0), 30.0) == 0.0


def test_slower_lead_asks_for_more_the_slower_it_is():
    d = [forksim.nominal_demand(lead_path(50.0, 30.0 - dv), 30.0) for dv in (0.0, 1.0, 2.0, 4.0)]
    assert d == sorted(d) and d[0] == 0.0 and d[-1] > d[1] > 0.0


def test_braking_lead_asks_for_more_than_a_steady_slower_lead():
    assert forksim.nominal_demand(lead_path(50.0, 30.0, -2.0), 30.0) > forksim.nominal_demand(lead_path(50.0, 30.0), 30.0)


def test_nominal_demand_ignores_the_actual_gap():
    a = forksim.nominal_demand(lead_path(30.0, 27.0), 30.0)
    b = forksim.nominal_demand(lead_path(90.0, 27.0), 30.0)
    assert a == pytest.approx(b, abs=1e-6)


def test_demand_does_not_count_a_gap_that_is_already_too_small_but_not_getting_worse():
    assert forksim.brake_demand(lead_path(20.0, 30.0), 30.0) == 0.0
    assert forksim.brake_demand(lead_path(20.0, 25.0), 30.0) > 0.0


def test_exec_stripped_drops_imports_and_runs_the_rest(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("import definitely_not_installed\nfrom also_missing import x\nA = 2\n\ndef f(v):\n    return v * A\n")
    ns: dict = {}
    forksim.exec_stripped(src, ns)
    assert ns["f"](4) == 8


def test_exec_stripped_tolerant_skips_statements_that_fail(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("B = missing_name + 1\nC = 3\n")
    ns: dict = {}
    skipped = forksim.exec_stripped(src, ns, tolerant=True)
    assert ns["C"] == 3 and "B" not in ns and len(skipped) == 1


def test_fork_root_finds_sunnypilot_layout(tmp_path):
    (tmp_path / "openpilot" / "selfdrive" / "controls").mkdir(parents=True)
    (tmp_path / "openpilot" / "selfdrive" / "controls" / "radard.py").write_text("")
    assert forksim.fork_root(tmp_path) == tmp_path / "openpilot"
    with pytest.raises(SystemExit):
        forksim.fork_root(tmp_path / "nowhere")
