"""0x100 byte 0 bit 1, the radar's PCS alarm; the power-up FF FF frame is not an alarm (docs/15)."""
from pathlib import Path

from ars510.support import pcs_alarm

PATCH = Path(__file__).resolve().parents[1] / "upstream" / "opendbc_ars510_pcs.patch"


def test_pcs_alarm():
    assert pcs_alarm(bytes([0x02, 0, 0, 0, 0, 0, 0]))
    assert not pcs_alarm(bytes(7))
    assert not pcs_alarm(bytes([0xFF, 0xFF, 0, 0, 0, 0, 0]))  # first frame after power-up
    assert not pcs_alarm(b"")


def test_upstream_patch_reads_the_same_bits():
    # carstate checks PCS_ALARM (byte 0 bit 1) and POWER_UP == 0 (byte 1), the same rule as pcs_alarm()
    patch = PATCH.read_text()
    assert ' SG_ PCS_ALARM : 1|1@0+ (1,0) [0|1] "" XXX' in patch and '+ SG_ POWER_UP : 15|8@0+ (1,0) [0|255] "" XXX' in patch
    assert 'pcs["PCS_ALARM"] and pcs["POWER_UP"] == 0' in patch and '[("PCS_STATE", float(\'nan\'))]' in patch
