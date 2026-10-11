"""Raw pass-through of class, size, sigma and score codes in the native object decode."""
import pytest

from ars510.objects import UNCERTAINTY_PER_COUNT, decode_native_slot, encode_slot


def test_round_trip_of_every_passthrough_code():
    codes = dict(age_cycles=40, long_dist=640, object_class=3, length=120, width_minus_one=21, height_like_code=9,
                 range_uncertainty_code=14, lateral_uncertainty_code=2, vel_uncertainty_candidate=17,
                 lateral_speed_uncertainty_code=3, accel_uncertainty_code=77, lateral_accel_uncertainty_code=200,
                 orientation_uncertainty_code=63, secondary_score_pct=88)
    obj = decode_native_slot(4, encode_slot(**codes))
    assert (obj.object_class, obj.height_code, obj.range_unc_code, obj.lateral_unc_code) == (3, 9, 14, 2)
    assert (obj.vel_unc_code, obj.vlat_unc_code, obj.accel_unc_code, obj.lateral_accel_unc_code) == (17, 3, 77, 200)
    assert (obj.orientation_unc_code, obj.secondary_score_pct) == (63, 88)
    assert obj.length_m == pytest.approx(12.0) and obj.width_m == pytest.approx(2.2)


def test_fields_do_not_overlap_the_decoded_kinematics():
    base = decode_native_slot(0, encode_slot(age_cycles=50, long_dist=800, vel_uncertainty_candidate=10))
    wide = decode_native_slot(0, encode_slot(age_cycles=50, long_dist=800, vel_uncertainty_candidate=10, range_uncertainty_code=127,
                                             accel_uncertainty_code=255, secondary_score_pct=255, object_class=7))
    assert (wide.d_rel, wide.y_rel, wide.v_long_ground, wide.age, wide.vel_unc_code) == \
           (base.d_rel, base.y_rel, base.v_long_ground, base.age, base.vel_unc_code)


def test_documented_scales_are_labelled_per_count():
    assert UNCERTAINTY_PER_COUNT["vel_uncertainty_candidate"] == pytest.approx(0.043)
