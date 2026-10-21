"""Bus-level constants for the Toyota / Continental ARS510 front radar.

Everything here was observed on the radar CAN bus (comma harness bus 1, `src == 1` in openpilot logs).
See docs/01_radar_bus.md and docs/02_object_list.md.
"""
from __future__ import annotations

RADAR_BUS = 1
CAR_BUS = 0

# Object list: one 742-byte record, ISO-TP-style segmented over 106 frames on 0x80.
ID80_ADDR = 0x80
ID80_FIRST_FRAME = (0x12, 0xE4)  # first frame: type 1, length 0x2E4 = 740 (+ the length byte itself)
ID80_RECORD_FRAMES = 106
ID80_RECORD_LEN = 742  # bytes 1..7 of each of the 106 frames
ID80_OBJECT_START = 17  # record bytes 0..16 are the record header
ID80_OBJECT_LEN = 36
ID80_OBJECT_COUNT = 20
ID80_CRC_START, ID80_CRC_END = 1, 737  # zlib CRC32 over record[1:737] ...
ID80_CRC_FIELD = (737, 741)  # ... stored little-endian in record[737:741]
# An unoccupied slot carries exactly these 36 bytes.
ID80_IDLE_SLOT = bytes.fromhex("FCE00000A0F07F00FFFDF71FFFA100F807000F0008000000000000000000000000000000")

# Shell / metadata record: 147 bytes over 21 frames on 0x85.
ID85_ADDR = 0x85
ID85_FIRST_FRAME = (0x10, 0x90)  # length 0x090 = 144
ID85_RECORD_FRAMES = 21
ID85_RECORD_LEN = 147

# Each record is an ISO-TP transfer from the radar to the camera: the camera answers every first frame (0x80: length 740,
# 0x85: 144) with one flow-control frame 30 00 00 00 00 00 00 00 (clear to send, block size 0, STmin 0) about 0.35 ms
# later, and the radar sends the consecutive frames only after it (docs/01). The names below are kept for compatibility.
ID80_MARKER_ADDR = 0x81
ID85_MARKER_ADDR = 0x86
RECORD_MARKER_PAYLOAD = bytes.fromhex("3000000000000000")

# Car bus: Toyota SPEED message, big-endian 16 bit at bytes 5-6, 0.01 km/h.
TOYOTA_SPEED_ADDR = 0xB4
TOYOTA_KINEMATICS_ADDR = 0x24  # YAW_RATE, left positive (Toyota YAW_RATE on the car bus)

# The OEM ACC target witness stream (radar bus, 50 Hz). 0x235 carries its closing speed, 0x237 its position. See
# ars510/support.py and docs/05.
ACC_TARGET_VREL_ADDR = 0x235
ACC_TARGET_POS_ADDR = 0x237
SUMMARY_ADDRS = (0x192, 0x194)  # the radar's selected-target range summaries (docs/05)
RADAR_FAULT_ADDR = 0x196  # event frame; byte 1 bit 0 = the radar's own fault / blocked flag (docs/05)
PCS_STATE_ADDR = 0x100  # 10 Hz; byte 0 bit 1 = the radar's PCS alarm (FCW) stage, FF FF on the first frame after power-up (docs/15)

# Radar cycle: one record every 60.28 ms (16.6 Hz): the record clocks advance 603 x 100 us (0x80 header) and
# 60,280 x 1 us (0x85 prefix) per record and keep log time on both cars; arrival intervals jitter around a 59.9 ms median.
RADAR_CYCLE_S = 0.06028
