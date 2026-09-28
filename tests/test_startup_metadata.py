"""The newly exposed raw subfields must not alias neighboring flags or controls."""
from ars510.objects import decode_native_slot, encode_slot, slot_bits


def test_raw_startup_subfields_roundtrip_all_wire_values():
    # Code31 is unobserved in the study, but remains a representable raw code.
    for low5 in range(32):
        for high in range(2):
            slot = encode_slot(age_cycles=60, raw8_low5=low5, raw13_bit=high, oncoming_flag=1, movement_code=5)
            obj = decode_native_slot(0, slot)
            assert obj.raw8_low5 == low5
            assert obj.raw13_bit == high
            assert slot_bits(slot, 8, 6) == low5 + 32 * high
            assert obj.oncoming_flag and obj.movement_code == 5


def test_raw_high_bit_toggle_preserves_low_code_and_kinematics():
    slot = encode_slot(age_cycles=12, raw8_low5=1, raw13_bit=0, long_dist=640, long_vel_over_ground=580)
    toggled = bytearray(slot)
    toggled[1] ^= 32
    first, second = decode_native_slot(0, slot), decode_native_slot(0, bytes(toggled))
    assert first.raw8_low5 == second.raw8_low5 == 1
    assert (first.raw13_bit, second.raw13_bit) == (0, 1)
    assert first.d_rel == second.d_rel and first.v_long_ground == second.v_long_ground
    assert first.geometry_valid == second.geometry_valid
