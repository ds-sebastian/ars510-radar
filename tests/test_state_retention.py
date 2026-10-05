"""Retire unreachable maps without losing native lifecycle or inherited output identities."""
from dataclasses import replace
import zlib

from ars510.constants import ID80_IDLE_SLOT
from ars510.interface import Ars510NativeRadarInterface, BASE_CONFIG, GUARD_ID_STRIDE
from ars510.objects import encode_slot


def _slot(age=126, *, velocity=644, distance=50, lateral=0):
  return encode_slot(age_cycles=min(age, 126), long_vel_over_ground=velocity,
                     long_dist=160 + 16 * distance, lat_dist_left=2048 + 64 * lateral,
                     vel_uncertainty_candidate=1)


class Sequence:
  def __init__(self, config=BASE_CONFIG):
    self.radar = Ars510NativeRadarInterface(config)
    self.t = 0.0

  def step(self, slots, *, churn=False):
    if churn:
      # This distant object resets its native allocation each cycle, creating real map pressure.
      slots = {**slots, 15: _slot(60, distance=150, lateral=20)}
    record = bytearray(742)
    record[0] = 0xE4
    for i in range(20):
      record[17 + 36 * i:17 + 36 * (i + 1)] = slots.get(i, ID80_IDLE_SLOT)
    record[737:741] = zlib.crc32(record[1:737]).to_bytes(4, "little")
    self.radar.set_ego_speed(20.0, self.t)
    points = self.radar._payload(self.t, bytes(record))["radarData"]["points"]
    self.t += 0.06
    return points


def test_retired_ancestor_map_does_not_erase_inherited_output_identity():
  seq = Sequence(replace(BASE_CONFIG, min_publish_age=6))
  first_id = None
  for run in range(26):
    slot = 3 if run % 2 == 0 else 7
    if run:
      seq.t += 0.66
    for age in range(2, 50):
      points = seq.step({slot: _slot(age)}, churn=True)
      lead = next((p for p in points if p["slot"] == slot), None)
      if lead is not None:
        first_id = lead["trackId"] if first_id is None else first_id
        assert lead["trackId"] == first_id
  assert first_id not in seq.radar._last
  assert first_id not in seq.radar._out_id
  # The latest mapping owns the flattened output value; it does not need the ancestor's key.
  assert seq.radar._out_id[lead["native_id"]] == first_id


def test_long_guard_preserves_live_mapping_and_generation_after_position_expires():
  seq = Sequence()
  for _ in range(10):
    points = seq.step({3: _slot()})
  inherited_id = points[0]["trackId"]
  seq.t += 0.6
  for age in range(2, 127):
    points = seq.step({7: _slot(age)}, churn=True)
  native_id = next(p["native_id"] for p in points if p["slot"] == 7)
  assert seq.radar._out_id[native_id] == inherited_id
  for velocity in (1023, 1023, 644):
    seq.step({7: _slot(velocity=velocity)}, churn=True)
  assert seq.radar._guard_gen[native_id] == 1
  for _ in range(1200):
    seq.step({7: _slot(velocity=1023)}, churn=True)
  assert native_id not in seq.radar._last
  assert seq.radar._out_id[native_id] == inherited_id
  assert seq.radar._guard_gen[native_id] == 1
  recovered = next(p for p in seq.step({7: _slot()}, churn=True) if p["slot"] == 7)
  assert recovered["trackId"] == inherited_id + 2 * GUARD_ID_STRIDE


def test_configured_long_relink_horizon_is_preserved():
  seq = Sequence(replace(BASE_CONFIG, relink_max_gap_s=90.0))
  for _ in range(500):
    seq.step({3: _slot(60)})
  seq.radar._prune(149.0)
  assert 1 in seq.radar._last and 1 in seq.radar._out_id
  seq.radar._prune(161.0)
  assert 1 not in seq.radar._last and 1 not in seq.radar._out_id
