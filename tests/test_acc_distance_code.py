from pathlib import Path

from ars510.support import parse_acc_target_arel, parse_acc_target_position, parse_acc_target_range_code, parse_acc_target_vrel


def test_all_raw_codes_and_coarse_alias():
    for code in range(8192):
        payload = ((code << 39) | (1002 << 28) | 0x123).to_bytes(8, "big")
        assert parse_acc_target_range_code(payload) == code
        assert parse_acc_target_position(payload)[0] == (code >> 8)*5.26+9.6
        assert payload[1] & 15 == code >> 9


def test_diagnostic_parser_rejects_short_frames():
    for length in range(8):
        assert parse_acc_target_range_code(bytes(length)) is None


def test_raw_code_does_not_apply_coarse_origin():
    assert parse_acc_target_range_code(bytes(8)) == 0
    assert parse_acc_target_range_code((1000 << 39).to_bytes(8, "big")) == 1000


def test_dbc_distance_code_is_metric_with_zero_offset():
    dbc = (Path(__file__).resolve().parents[1] / "dbc/ars510_radar_bus.dbc").read_text()
    assert 'SG_ A237_ACC_TARGET_DISTANCE_CODE : 11|13@0+ (0.025,0) [0|204.775] "m"' in dbc
    assert 'SG_ A235_ACC_TARGET_VREL : 31|11@0+ (0.125,-128)' in dbc


def test_acc_target_arel_byte2_zero_at_idle_payload():
    idle = bytes.fromhex("000164800B2400FF")
    assert parse_acc_target_arel(idle) == 0.0
    assert parse_acc_target_vrel(idle) == 0.0
    for code in range(256):
        payload = bytearray(idle)
        payload[2] = code
        assert parse_acc_target_arel(bytes(payload)) == (code - 100) * 0.1
    assert parse_acc_target_arel(bytes(7)) is None


def test_dbc_arel_matches_parser():
    dbc = (Path(__file__).resolve().parents[1] / "dbc/ars510_radar_bus.dbc").read_text()
    assert 'SG_ A235_ACC_TARGET_AREL : 16|8@1+ (0.1,-10) [-10|15.5] "m/s^2"' in dbc
