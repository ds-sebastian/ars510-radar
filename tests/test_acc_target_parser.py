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
    for nanos, frames in strings:
      self.now = nanos
      for addr, dat, src in frames:
        if src == 1 and addr in self.msgs and len(dat) == 8:
          name, sigs, _ = self.msgs[addr]
          self.vl[name] = {s: _decode(dat, st, ln, be) * sc + off for s, st, ln, be, sc, off in sigs}
          self.seen[addr] = nanos

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


def test_publishes_the_decoded_acc_target_at_20_hz(mod):
  ri, last, reports, points = mod.RadarInterface(None), {}, 0, 0
  for row in csv.DictReader(gzip.open(SAMPLE, "rt")):
    t, bus, addr, dat = float(row["t_s"]), int(row["bus"]), int(row["address"], 0), bytes.fromhex(row["data_hex"])
    if bus == 1 and addr in (0x235, 0x237):
      last[addr] = dat
    out = ri.update([(int(t * 1e9), [(addr, dat, bus)])])
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
  assert ri.frame // 5 == reports and points > 0.99 * reports  # one report per 5 updates (card calls at 100 Hz)


def test_no_target_no_point_and_a_silent_radar_is_a_can_error(mod):
  ri = mod.RadarInterface(None)
  out = [ri.update([(int(i * 1e7), [(0x235, IDLE_235, 1), (0x237, IDLE_237, 1)])]) for i in range(1, 6)][-1]
  assert out.points == [] and not out.errors.canError
  out = [ri.update([(int(1e9 + i * 1e7), [(0x100, bytes(8), 0)])]) for i in range(1, 6)][-1]
  assert out.points == [] and out.errors.canError


def test_opendbc_patch_carries_the_same_files():
  patch = (REPO / "upstream" / "opendbc_ars510.patch").read_text()
  for name, src in (("opendbc/car/toyota/ars510_acc_target.py", "ars510_acc_target.py"),
                    ("opendbc/dbc/toyota_tss2_ars510.dbc", "toyota_tss2_ars510.dbc")):
    body = patch.split(f"+++ b/{name}\n", 1)[1].split("\ndiff --git", 1)[0]
    added = [line[1:] for line in body.splitlines() if line.startswith("+")]
    assert added == (REPO / "upstream" / src).read_text().splitlines(), name
  assert "dbc_dict('toyota_nodsu_pt_generated', ARS510_RADAR)" in patch
