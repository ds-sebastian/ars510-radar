"""Run a fork's own radard and MPC lead-handling code on recorded ticks, without openpilot's runtime.

The fork's source is executed unmodified: its import statements are dropped and the few things it imports (messaging,
params, the solver) are replaced by stand-ins, so nothing here is a re-implementation of the fork's logic. What is
exercised:

  - radard: `Track`, `match_vision_to_track`, `get_lead`, `RadarD.update` (lead selection, per-track Kalman filter)
  - long_mpc: `LongitudinalMpc.process_lead` and the helpers it calls (the lead trajectory the MPC is given)

Runs radard and process_lead only; the MPC solver, the rest of the planner and the controls are replaced by the "demand"
proxy below: the constant
deceleration that keeps the lead-based safety distance, applied to the lead trajectory the fork hands to its MPC. It
ranks forks and radar profiles against each other; it is not the planner's output.

A fork checkout is the directory that holds `selfdrive/` and `common/` (for sunnypilot, its `openpilot/` subdirectory;
`fork_root()` finds it).
"""
from __future__ import annotations

import ast
import importlib.util
import math
import typing
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np

DT_MDL = 0.05
FORKS = ("sunnypilot", "frogpilot", "starpilot")


def fork_root(path: str | Path) -> Path:
    """The directory with selfdrive/ and common/ inside a fork checkout."""
    p = Path(path)
    for cand in (p, p / "openpilot"):
        if (cand / "selfdrive" / "controls" / "radard.py").exists():
            return cand
    raise SystemExit(f"no selfdrive/controls/radard.py under {p}")


class DO(SimpleNamespace):
    """Attribute bag that turns dicts into DO on assignment (stand-in for capnp struct builders)."""

    def __setattr__(self, k, v):
        super().__setattr__(k, DO(**v) if isinstance(v, dict) else v)

    def get(self, k, default=None):
        return getattr(self, k, default)


def _load_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def exec_stripped(path: Path, ns: dict, tolerant: bool = False) -> list:
    """Execute a module's top-level statements except imports. tolerant: skip statements that raise (paths, solver)."""
    tree = ast.parse(path.read_text())
    skipped = []
    ns.setdefault("__name__", "forkmod")
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        code = compile(ast.Module([node], []), str(path), "exec")
        if not tolerant:
            exec(code, ns)
            continue
        try:
            exec(code, ns)
        except Exception as e:  # noqa: BLE001
            skipped.append((getattr(node, "name", None) or ast.dump(node)[:50], repr(e)[:70]))
    return skipped


LANE_CHANGE_STATE = SimpleNamespace(off="off", preLaneChange="preLaneChange", laneChangeStarting="laneChangeStarting",
                                    laneChangeFinishing="laneChangeFinishing")
LANE_CHANGE_DIRECTION = SimpleNamespace(none="none", left="left", right="right")


def _radard_namespace(root: Path, fork: str, toggles) -> dict:
    fo = _load_file(root / "common" / "filter_simple.py", f"fo_{fork}")
    kf = _load_file(root / "common" / "simple_kalman.py", f"kf_{fork}")
    return dict(
        math=math, np=np, deque=deque, Any=typing.Any, SimpleNamespace=SimpleNamespace, importlib=importlib,
        capnp=SimpleNamespace(_DynamicStructReader=object, _DynamicStructBuilder=object),
        messaging=SimpleNamespace(SubMaster=object, PubMaster=object), car=SimpleNamespace(RadarData=object),
        structs=SimpleNamespace(CarParams=object, CarParamsSP=object),
        custom=SimpleNamespace(FrogPilotRadarState=SimpleNamespace(new_message=lambda: DO()),
                               StarPilotRadarState=SimpleNamespace(new_message=lambda: DO())),
        log=SimpleNamespace(RadarState=SimpleNamespace(new_message=lambda: DO())),
        FirstOrderFilter=fo.FirstOrderFilter, KF1D=kf.KF1D, interp=np.interp, DT_MDL=DT_MDL, DT_CTRL=0.01,
        Priority=SimpleNamespace(CTRL_LOW=0), config_realtime_process=lambda *a, **k: None, Params=object,
        cloudlog=SimpleNamespace(info=print, warning=print), LaneChangeState=LANE_CHANGE_STATE,
        LaneChangeDirection=LANE_CHANGE_DIRECTION, THRESHOLD=0.63,
        get_frogpilot_toggles=lambda *a, **k: toggles, get_starpilot_toggles=lambda *a, **k: toggles,
        SERVICE_LIST={"liveTracks": SimpleNamespace(frequency=20)}, BOSCH_A_FREQ_HZ=15.0, HONDA_BOSCH_A=set(),
        HyundaiFlags=SimpleNamespace(CANFD_CAMERA_SCC=1, CAMERA_SCC=2), HyundaiFlagsSP=SimpleNamespace(ENHANCED_SCC=1),
        Ratekeeper=object)


class _SubMaster:
    def __init__(self):
        self.d = {}
        self.seen = {"modelV2": True}
        self.recv_frame = {"carState": 0, "modelV2": 0, "liveTracks": 0}
        self.logMonoTime = {"modelV2": 0, "carState": 0}

    def __getitem__(self, k):
        return self.d[k]

    def all_checks(self, *a, **k):
        return True


def _model_lead(l: dict) -> DO:
    return DO(prob=l["prob"], x=l["x"], y=l["y"], v=l["v"], a=l["a"], xStd=l["xStd"], yStd=l["yStd"], vStd=l["vStd"],
              aStd=l["aStd"])


def _model(tk: dict) -> DO:
    return DO(leadsV3=[_model_lead(l) for l in tk["leads"]], laneLines=[DO(x=x, y=y) for x, y in tk["lanes"]],
              position=DO(x=[0.0, tk["pos_x_last"]]), velocity=DO(x=[tk["model_v_ego"]]),
              meta=DO(laneChangeState=tk["lc_state"], laneChangeDirection=tk["lc_dir"]))


def _norm(lead) -> dict:
    d = dict(vars(lead))
    d["status"] = bool(d.get("status", d.get("present", False)))
    d["radar"] = bool(d.get("radar", False))
    return d


class RadarFork:
    """The fork's RadarD, stepped once per model tick. `tick` is one entry of a ticks.pkl (see prepare_route.py)."""

    # StarPilot and FrogPilot default to 0.35 (a user setting, 0.25-0.5); openpilot and sunnypilot hard-code 0.5
    DEFAULT_LEAD_PROB = {"sunnypilot": 0.5, "frogpilot": 0.35, "starpilot": 0.35}

    def __init__(self, fork: str, path: str | Path, lead_prob: float | None = None):
        self.fork = fork
        self.toggles = SimpleNamespace(lead_detection_probability=lead_prob or self.DEFAULT_LEAD_PROB[fork],
                                       human_lane_changes=False, adjacent_lead_tracking=False)
        root = fork_root(path)
        self.ns = _radard_namespace(root, fork, self.toggles)
        exec_stripped(root / "selfdrive" / "controls" / "radard.py", self.ns, tolerant=True)
        radar_d = self.ns["RadarD"]
        if fork == "sunnypilot":
            self.rd = radar_d(SimpleNamespace(brand="toyota", flags=0), SimpleNamespace(flags=0), 0.0)
        elif fork == "frogpilot":
            self.rd = radar_d(DT_MDL, 0)
        else:
            self.rd = radar_d(radar_ts=DT_MDL, delay=0.0)
        self.frame = 0

    def step(self, tick: dict, points: list) -> tuple[dict, dict]:
        """points: [(trackId, dRel, yRel, vRel), ...]. Returns (leadOne, leadTwo) as dicts with status / radar."""
        sm = _SubMaster()
        self.frame += 1
        t_ns = int(tick["t"] * 1e9)
        sm.recv_frame["carState"] = self.frame
        sm.logMonoTime = {"modelV2": t_ns, "carState": t_ns}
        car = tick["car"]
        sm.d["carState"] = DO(vEgo=car["vEgo"], standstill=car["standstill"], aEgo=car["aEgo"])
        sm.d["modelV2"] = _model(tick)
        sm.d["frogpilotPlan"] = DO(increasedStoppedDistance=0.0, togglesUpdated=False)
        sm.d["starpilotPlan"] = DO(increasedStoppedDistance=0.0, togglesUpdated=False)
        rr = DO(points=[DO(trackId=i, dRel=d, yRel=y, vRel=v, measured=True) for i, d, y, v in points], errors=[])
        self.rd.update(sm, rr)
        st = self.rd.radar_state
        none = {"status": False, "radar": False}
        return (_norm(st.leadOne) if hasattr(st, "leadOne") else none,
                _norm(st.leadTwo) if hasattr(st, "leadTwo") else none)


# ----------------------------------------------------------------------------------------------------------------
# MPC lead handling
# ----------------------------------------------------------------------------------------------------------------
def _index_function(idx, max_val=192, max_idx=32):
    return max_val * ((idx / max_idx) ** 2)


class _ModelConstants:
    LEAD_T_IDXS = [0., 2., 4., 6., 8., 10.]


def _mpc_namespace(root: Path, fork: str) -> dict:
    fo = _load_file(root / "common" / "filter_simple.py", f"fo2_{fork}")
    ns = dict(
        np=np, os=__import__("os"), time=__import__("time"), math=math, index_function=_index_function,
        ModelConstants=_ModelConstants, DT_MDL=DT_MDL, FirstOrderFilter=fo.FirstOrderFilter,
        CV=SimpleNamespace(MS_TO_MPH=2.2369362920544, MPH_TO_MS=0.44704, MS_TO_KPH=3.6, KPH_TO_MS=1 / 3.6),
        ACCEL_MIN=-3.5, ACCEL_MAX=2.0, cloudlog=SimpleNamespace(info=print, warning=print), SX=None, vertcat=None,
        AcadosModel=object, AcadosOcp=object, AcadosOcpSolver=object, _LEAD_ACCEL_TAU=1.5,
        log=SimpleNamespace(LongitudinalPersonality=SimpleNamespace(relaxed=2, standard=1, aggressive=0)))
    if fork == "starpilot":
        lb: dict = {"np": np, "math": math}
        exec_stripped(root / "selfdrive" / "controls" / "lib" / "lead_behavior.py", lb, tolerant=True)
        ns.update({k: v for k, v in lb.items() if k.startswith(("get_", "is_", "should_", "_")) and callable(v)})
    return ns


class MpcLead:
    """The fork's own `process_lead` on a bare LongitudinalMpc, as the planner calls it once per tick."""

    def __init__(self, fork: str, path: str | Path, human_following: bool = False):
        self.fork = fork
        root = fork_root(path)
        self.ns = _mpc_namespace(root, fork)
        exec_stripped(root / "selfdrive" / "controls" / "lib" / "longitudinal_mpc_lib" / "long_mpc.py", self.ns,
                      tolerant=True)
        cls = self.ns["LongitudinalMpc"]
        self.m = cls.__new__(cls)
        self.m.dt = DT_MDL
        self.model_path_used = False
        if fork == "starpilot":
            self._init_starpilot()
        self.toggles = SimpleNamespace(human_following=human_following, model_version="v9",
                                       lead_detection_probability=0.35)

    def _init_starpilot(self):
        """The attributes StarPilot's __init__ sets after creating the solver (which is not needed here)."""
        fo = self.ns["FirstOrderFilter"]
        m = self.m
        m.current_filter_time = self.ns["LEAD_FILTER_TIME_LOW"]
        m.lead_a_filter = fo(0.0, m.current_filter_time, DT_MDL)       # start at 0, as the fork does
        m.lead_v_filter = fo(0.0, m.current_filter_time, DT_MDL)
        m.filter_time_factor = m.prev_filter_time_factor = 1.0
        m.slew_per_sec = 1.0
        m.mode = "acc"
        m.solver = SimpleNamespace(cost_set=lambda *a, **k: None)
        m.duplicate_lead_x_filters = [fo(0.0, 0.0, DT_MDL, initialized=False) for _ in range(2)]
        m.duplicate_lead_a_filters = [fo(0.0, 0.0, DT_MDL, initialized=False) for _ in range(2)]
        m.duplicate_lead_v_filters = [fo(0.0, 0.0, DT_MDL, initialized=False) for _ in range(2)]
        orig = self.ns["build_model_lead_trajectory"]

        def tracked(*a, **k):
            r = orig(*a, **k)
            self.model_path_used = r is not None
            return r
        self.ns["build_model_lead_trajectory"] = tracked

    def seed_filters(self, v_lead: float, a_lead: float = 0.0):
        """StarPilot only: put its lead filters in a warm state instead of the boot state (0)."""
        if self.fork == "starpilot":
            self.m.lead_v_filter.x, self.m.lead_a_filter.x = v_lead, a_lead

    def lead_xv(self, v_ego: float, a_ego: float, lead: dict, model_lead: dict, index: int = 0) -> np.ndarray:
        """The (N+1, 2) lead trajectory [x, v] the fork gives its MPC for this lead."""
        self.m.x0 = np.array([0.0, v_ego, a_ego])
        if self.fork == "starpilot":
            self.model_path_used = False
            self.m.set_weights(v_ego=v_ego, lead_dist=lead.get("dRel", 50.0))   # the planner does this every tick
        L = DO(**lead)
        L.present = lead["status"]
        if self.fork == "sunnypilot":
            return np.asarray(self.m.process_lead(L))
        if self.fork == "frogpilot":
            return np.asarray(self.m.process_lead(_model_lead(model_lead), L, self.toggles, False))
        return np.asarray(self.m.process_lead(L, True, 1.45, lead_index=index, model_lead=_model_lead(model_lead)))

    @property
    def filters(self) -> tuple[float, float]:
        """StarPilot only: (filtered lead speed, filtered lead acceleration)."""
        return self.m.lead_v_filter.x, self.m.lead_a_filter.x


# ----------------------------------------------------------------------------------------------------------------
# braking-demand proxy
# ----------------------------------------------------------------------------------------------------------------
T_GRID = np.linspace(0, 10, 201)
MPC_T = np.array([_index_function(i, max_val=10.0, max_idx=12) for i in range(13)])


def brake_demand(lead_xv: np.ndarray, v_ego: float, t_follow: float = 1.45, comfort: float = 2.5,
                 stop_d: float = 6.0) -> float:
    """Smallest constant ego deceleration (m/s^2, 0..8) that keeps the lead's safety distance over 10 s.

    Safe distance is the MPC's own: stop_d + t_follow * v + v^2 / (2 * comfort), against the lead's position plus its
    stopping distance. If the ego starts closer than that, the demand is what stops it getting worse.
    """
    xl = np.interp(T_GRID, MPC_T, lead_xv[:, 0])
    vl = np.interp(T_GRID, MPC_T, lead_xv[:, 1])
    obstacle = xl + vl ** 2 / (2 * comfort)
    dt = T_GRID[1] - T_GRID[0]
    floor = min(obstacle[0] - (stop_d + t_follow * v_ego + v_ego ** 2 / (2 * comfort)), 0.0) - 1e-6

    def holds(a: float) -> bool:
        x, v, worst = 0.0, v_ego, 1e9
        for k in range(len(T_GRID)):
            worst = min(worst, obstacle[k] - x - (stop_d + t_follow * v + v ** 2 / (2 * comfort)))
            v_new = max(v - a * dt, 0.0)
            x += 0.5 * (v + v_new) * dt
            v = v_new
        return worst >= floor

    if holds(0.0):
        return 0.0
    lo, hi = 0.0, 8.0
    if not holds(hi):
        return hi
    for _ in range(18):
        mid = 0.5 * (lo + hi)
        lo, hi = (lo, mid) if holds(mid) else (mid, hi)
    return hi


def nominal_demand(lead_xv: np.ndarray, v_ego: float, t_follow: float = 1.45, comfort: float = 2.5,
                   stop_d: float = 6.0) -> float:
    """brake_demand with the lead shifted so the ego starts exactly at the desired spacing.

    Isolates what the lead's predicted speed and acceleration ask for, independent of the actual gap (a driver who
    follows closer than the planner's gap would otherwise show braking demand all the time)."""
    xv = np.array(lead_xv, dtype=float)
    safe0 = stop_d + t_follow * v_ego + v_ego ** 2 / (2 * comfort)
    xv[:, 0] += safe0 - (xv[0, 0] + xv[0, 1] ** 2 / (2 * comfort))
    return brake_demand(xv, v_ego, t_follow, comfort, stop_d)
