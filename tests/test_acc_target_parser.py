"""upstream/ars510_acc_target.py (the ACC target alone, docs/17) must publish exactly the decoded ACC target.

opendbc's CANParser is replaced by a small decoder that reads the signals from upstream/toyota_tss2_ars510.dbc, so these
tests also check the DBC against ars510.support. upstream/opendbc_ars510.patch must carry the same files.
"""
from __future__ import annotations

import csv
import gzip
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

from ars510.support import parse_acc_target
from test_upstream_candidate import _fake_opendbc

REPO = Path(__file__).resolve().parents[1]
DBC_FILE = REPO / "upstream" / "toyota_tss2_ars510.dbc"
SAMPLE = REPO / "data" / "sample" / "highway_acc_anchor_24s.csv.gz"
IDLE_235, IDLE_237 = bytes.fromhex("0061648000000000"), bytes.fromhex("00000000003E8000")  # no target: status 1, bit 10 clear


def _dbc_messages(path: Path) -> dict[str, tuple[int, list]]:
  """name -> (address, [(signal, start, length, big_endian, scale, offset)]) from BO_ / SG_ lines."""
  msgs, cur = {}, None
  for line in path.read_text().splitlines():
    if m := re.match(r"BO_ (\d+) (\w+):", line):
      cur = msgs[m[2]] = (int(m[1]), [])
    elif cur and (m := re.match(r"\s*SG_ (\w+) : (\d+)\|(\d+)@([01])\+ \(([-\d.e]+),([-\d.e]+)\)", line)):
      cur[1].append((m[1], int(m[2]), int(m[3]), m[4] == "0", float(m[5]), float(m[6])))
  return msgs


def _decode(dat: bytes, start: int, length: int, big_endian: bool) -> int:
  if big_endian:  # DBC Motorola start bit = MSB; msb_first counts from bit 7 of byte 0
    msb_first = 8 * (start // 8) + 7 - start % 8
    return (int.from_bytes(dat, "big") >> (64 - msb_first - length)) & ((1 << length) - 1)
  return (int.from_bytes(dat, "little") >> start) & ((1 << length) - 1)


class FakeCANParser:
  """opendbc.can.CANParser for one bus: vl[name][signal], can_valid while every message is younger than 10 periods."""
  def __init__(self, dbc_name, messages, bus):
    assert dbc_name == DBC_FILE.stem and bus == 1
    dbc = _dbc_messages(DBC_FILE)
    self.msgs = {dbc[name][0]: (name, dbc[name][1], 1e9 / freq * 10) for name, freq in messages}
    self.vl = {name: {s[0]: 0.0 for s in dbc[name][1]} for name, _ in messages}
    self.seen, self.now = {}, 0

  def update(self, strings):
    updated = set()
    for nanos, frames in strings:
      self.now = nanos
      for addr, dat, src in frames:
        if src == 1 and addr in self.msgs and len(dat) == 8:
          name, sigs, _ = self.msgs[addr]
          self.vl[name] = {s: _decode(dat, st, ln, be) * sc + off for s, st, ln, be, sc, off in sigs}
          self.seen[addr] = nanos
          updated.add(addr)
    return updated

  @property
  def can_valid(self):
    return all(a in self.seen and self.now - self.seen[a] <= tmo for a, (_, _, tmo) in self.msgs.items())


@pytest.fixture(scope="module")
def mod():
  names = ("opendbc", "opendbc.can", "opendbc.car", "opendbc.car.structs", "opendbc.car.interfaces")
  saved = {k: sys.modules.get(k) for k in names}
  fake = _fake_opendbc()
  fake["opendbc.car.structs"] = fake["opendbc.car"].structs
  fake["opendbc.can"] = types.SimpleNamespace(CANParser=FakeCANParser)
  sys.modules.update(fake)
  try:
    spec = importlib.util.spec_from_file_location("ars510_acc_target", REPO / "upstream" / "ars510_acc_target.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    yield m
  finally:
    for k, v in saved.items():
      if v is None:
        sys.modules.pop(k, None)
      else:
        sys.modules[k] = v


def clock(us: int) -> bytes:
  """0x239 with the radar's cycle clock (ACC_TARGET_3 TIMESTAMP, Motorola start bit 26, 32 bits)."""
  return (us << 3).to_bytes(8, "big")


def test_publishes_the_decoded_acc_target_once_per_radar_cycle(mod):
  # the bundled sample has no 0x239: its clock is added here, advancing every third 0x237 (60 ms), as on the car
  ri, last, reports, points, n237 = mod.RadarInterface(None), {}, 0, 0, 0
  for row in csv.DictReader(gzip.open(SAMPLE, "rt")):
    t, bus, addr, dat = float(row["t_s"]), int(row["bus"]), int(row["address"], 0), bytes.fromhex(row["data_hex"])
    frames = [(addr, dat, bus)]
    if bus == 1 and addr in (0x235, 0x237):
      last[addr] = dat
    if bus == 1 and addr == 0x237:
      frames.append((0x239, clock(60000 * (1 + n237 // 3)), 1))
      n237 += 1
    out = ri.update([(int(t * 1e9), frames)])
    if out is None:
      continue
    reports += 1
    want = parse_acc_target(last[0x235], last[0x237]) if len(last) == 2 else None
    assert (want is None) == (not out.points)
    if want is not None:
      (p,) = out.points
      points += 1
      assert p.trackId == want.target_id
      assert (p.dRel, p.yRel, p.vRel) == pytest.approx((want.d_rel, want.y_rel, want.v_rel), abs=1e-9)
  assert reports == -(-n237 // 3) and points > 0.99 * reports  # one report per radar cycle


def test_no_target_reports_keep_coming_and_a_silent_radar_publishes_nothing(mod):
  ri = mod.RadarInterface(None)
  outs = [ri.update([(int(i * 2e7), [(0x235, IDLE_235, 1), (0x237, IDLE_237, 1), (0x239, clock(60000 * (1 + i // 3)), 1)])])
          for i in range(30)]
  outs = [o for o in outs if o is not None]
  assert len(outs) == 10 and all(o.points == [] and not o.errors.canError for o in outs)  # no target: empty reports, no error
  assert all(ri.update([(int(1e9 + i * 1e7), [(0x100, bytes(8), 0)])]) is None for i in range(100))


def test_opendbc_patch_carries_the_dbc_and_the_same_logic():
  patch = (REPO / "upstream" / "opendbc_ars510.patch").read_text()
  body = patch.split("+++ b/opendbc/dbc/toyota_tss2_ars510.dbc\n", 1)[1].split("\ndiff --git", 1)[0]
  assert [line[1:] for line in body.splitlines() if line.startswith("+")] == (REPO / "upstream" / "toyota_tss2_ars510.dbc").read_text().splitlines()
  assert "dbc_dict('toyota_nodsu_pt_generated', 'toyota_tss2_ars510')" in patch
  for line in ("messages.append(('ACC_TARGET_3', 50))", "cycle = self.rcp.vl['ACC_TARGET_3']['TIMESTAMP']",
               'if self.rcp.can_valid and target["STATE"] == 5 and position["PRESENT"]:'):
    assert line in patch, line
  src = (REPO / "upstream" / "ars510_acc_target.py").read_text()
  assert '("ACC_TARGET_3", 50)' in src and 'self.rcp.vl["ACC_TARGET_3"]["TIMESTAMP"]' in src
