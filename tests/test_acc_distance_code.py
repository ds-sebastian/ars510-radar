from pathlib import Path

from ars510.support import parse_acc_target_position, parse_acc_target_range_code


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


def test_dbc_keeps_unknown_absolute_origin_as_raw_code():
    dbc = (Path(__file__).resolve().parents[1] / "dbc/ars510_radar_bus.dbc").read_text()
    assert 'SG_ A237_ACC_TARGET_DISTANCE_CODE : 11|13@0+ (1,0) [0|8191] "code"' in dbc
