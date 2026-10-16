"""ACC target check byte (0x235 / 0x237 / 0x239): CRC-8 0x1D over the serialized signals, stored as a linear table."""
import csv
import gzip
from pathlib import Path

from ars510.support import acc_check, parse_0x366, parse_acc_target

SAMPLES = sorted((Path(__file__).resolve().parents[1] / "data" / "sample").glob("*.csv.gz"))


def _acc_frames():
  for path in SAMPLES:
    for row in csv.DictReader(gzip.open(path, "rt")):
      address = int(row["address"], 16)
      if row["bus"] == "1" and address in (0x235, 0x237, 0x239):
        yield address, bytes.fromhex(row["data_hex"])


def test_every_bundled_acc_frame_passes():
  results = [acc_check(a, d) for a, d in _acc_frames()]
  assert len(results) > 1000
  assert all(r in ("ok", "wrapped") for r in results)


def test_a_flipped_bit_fails():
  for address, data in list(_acc_frames())[:300]:
    for byte in range(8):
      bad = bytearray(data); bad[byte] ^= 0x10
      assert acc_check(address, bytes(bad)) == "bad"


def test_wrapped_lateral_fields():
  # LAT_SPEED (0x235) / LAT_DIST (0x237) one bit wider inside the radar: the check byte carries the hidden bit
  assert acc_check(0x235, bytes.fromhex("9DF56E81CBE8001B")) == "wrapped"
  assert acc_check(0x237, bytes.fromhex("AD026580F2E8C550")) == "wrapped"
  assert acc_check(0x235, bytes.fromhex("EA056C81CBDFAA1B")) == "ok"


def test_other_addresses_are_not_checked():
  assert acc_check(0x23B, bytes(3)) is None and acc_check(0x235, bytes(7)) is None


def test_0x366_target_id_and_pcs_alarm():
  t = parse_0x366(bytes.fromhex("50043492300200"))  # recorded during the U3 PCS alarm
  assert t is not None and t.pcs_alarm and t.target_id == 6
  t = parse_0x366(bytes.fromhex("5000341B301200"))  # same target, no alarm
  assert t is not None and not t.pcs_alarm and t.target_id == 6


def test_target_id_is_six_bits_and_its_top_bit_has_its_own_column():
  # a C-HR 2021 radar (8821FF410300) frame with track number 32: byte 7 bit 5 set alone, which the RAV4 radars never sent
  # (bits 7-5 of byte 7 were 000 with a target and 111 idle), so only the three columns' sum was known before
  chr_frame = bytes.fromhex("116569820b347d20")
  assert acc_check(0x235, chr_frame) == "ok"
  assert parse_acc_target(chr_frame, bytes.fromhex("AD026580F2E8C550")).target_id == 32
