"""Raw weight metadata must preserve wire values and neighboring fields."""
from ars510.objects import decode_native_slot, encode_slot


def test_all_triplets_preserved_without_normalization():
    # Include impossible-looking sums: the decoder must preserve unknown modes.
    for a in range(16):
        for b in range(16):
            for c in range(16):
                raw=bytearray(encode_slot(age_cycles=60, long_dist=640, long_vel_over_ground=580))
                raw[18]=15 | (a << 4)
                raw[19]=b | (c << 4)
                obj=decode_native_slot(0,bytes(raw))
                assert obj.raw_weights148==(a,b,c)
                assert obj.age==60 and obj.d_rel==30 and obj.geometry_valid


def test_encoder_and_neighbor_independence():
    raw=bytearray(encode_slot(raw_weight148=10,raw_weight152=1,raw_weight156=3,age_cycles=126))
    assert raw[18]==0xA0 and raw[19]==0x31
    original=decode_native_slot(0,bytes(raw))
    raw[18]|=0xF
    raw[20]=0xFF
    changed=decode_native_slot(0,bytes(raw))
    assert original.raw_weights148==changed.raw_weights148==(10,1,3)
    assert original.v_long_ground==changed.v_long_ground
    assert original.d_rel==changed.d_rel and original.geometry_valid==changed.geometry_valid
