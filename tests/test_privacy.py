"""Synthetic identifiers are assembled so this source passes the privacy scan."""
import pytest

from tools import check_privacy


CASES = [
  ("openpilot route id", "12345678" + "--" + "abcdef0123"),
  ("openpilot route name (date form)", "2024-01-02" + "--" + "03-04-05"),
  ("dongle id", "01234567" + "89abcdef"),
  ("Toyota VIN", "JT" + "123456789012345"),
  ("GPS coordinate field", "latitude" + ": 12." + "3456"),
  ("local home path", "/" + "home" + "/sample"),
  ("device recording path", "/data" + "/media/0" + "/realdata"),
  ("private IP address", ".".join(("172", "16", "0", "1"))),
  ("openpilot route fragment", "route " + "1a2b3c4d" + "5e"),
]


def test_every_pattern_has_a_regression_case():
  assert {name for name, _ in CASES} == set(check_privacy.PATTERNS)


@pytest.mark.parametrize("name,value", CASES, ids=[name for name, _ in CASES])
def test_scan_reports_pattern_without_identifier(tmp_path, monkeypatch, name, value):
  monkeypatch.setattr(check_privacy, "REPO", tmp_path)
  path = tmp_path / "example.txt"
  path.write_text("clean line\n" + value + "\n")
  hits = check_privacy.scan([path])
  assert hits == [f"example.txt:2: {name}"]
  assert value not in hits[0]


@pytest.mark.parametrize("second_octet", range(16, 32))
def test_entire_private_172_range(tmp_path, second_octet):
  path = tmp_path / "example.txt"
  path.write_text(".".join(("172", str(second_octet), "255", "255")))
  assert len(check_privacy.scan([path])) == 1
  assert check_privacy.scan([path])[0].endswith(": private IP address")


@pytest.mark.parametrize("octets", [("10", "0", "0", "1"), ("192", "168", "255", "255")])
def test_other_private_ip_ranges(tmp_path, octets):
  path = tmp_path / "example.txt"
  path.write_text(".".join(octets))
  assert check_privacy.scan([path])[0].endswith(": private IP address")


@pytest.mark.parametrize("second_octet", [0, 15, 32, 255])
def test_public_172_addresses_are_clean(tmp_path, second_octet):
  path = tmp_path / "example.txt"
  path.write_text(".".join(("172", str(second_octet), "0", "1")))
  assert check_privacy.scan([path]) == []


@pytest.mark.parametrize("prefix", ["JT", "2T", "4T", "5T"])
def test_toyota_vin_prefixes(tmp_path, prefix):
  path = tmp_path / "example.txt"
  path.write_text(prefix + "123456789012345")
  assert check_privacy.scan([path])[0].endswith(": Toyota VIN")


@pytest.mark.parametrize("field", ["latitude", "longitude", "lat", "lon", "lng", "LATITUDE"])
def test_gps_fields_and_case(tmp_path, field):
  path = tmp_path / "example.txt"
  path.write_text('"' + field + '": -12.' + "3456")
  assert check_privacy.scan([path])[0].endswith(": GPS coordinate field")


@pytest.mark.parametrize("prefix", ["/" + "home/", "/" + "Users/", "C:" + "\\Users\\"])
def test_home_path_platforms(tmp_path, prefix):
  path = tmp_path / "example.txt"
  path.write_text(prefix + "sample")
  assert check_privacy.scan([path])[0].endswith(": local home path")


@pytest.mark.parametrize("value", ["a510" * 4, "12345678" * 2, "abcdefab" * 2, "0." + "01234567" + "89abcdef"])
def test_fake_dongle_and_nonidentifier_exceptions(tmp_path, value):
  path = tmp_path / "example.txt"
  path.write_text(value)
  assert check_privacy.scan([path]) == []


@pytest.mark.parametrize("name,value", CASES, ids=[name for name, _ in CASES])
def test_privacy_ok_suppresses_each_pattern(tmp_path, name, value):
  path = tmp_path / "example.txt"
  path.write_text(value + " # privacy-ok   \n")
  assert check_privacy.scan([path]) == []


def test_privacy_ok_only_suppresses_its_line(tmp_path):
  path = tmp_path / "example.txt"
  value = CASES[0][1]
  path.write_text(value + " # privacy-ok\n" + value + "\n")
  assert len(check_privacy.scan([path])) == 1
  assert ":2: openpilot route id" in check_privacy.scan([path])[0]


def test_privacy_ok_must_end_the_line(tmp_path):
  path = tmp_path / "example.txt"
  path.write_text(CASES[0][1] + " # privacy-ok followed by text\n")
  assert len(check_privacy.scan([path])) == 1


@pytest.mark.parametrize("suffix", sorted(check_privacy.BINARY))
def test_known_binary_extensions_are_skipped(tmp_path, suffix):
  path = tmp_path / ("example" + suffix.upper())
  path.write_text(CASES[0][1])
  assert check_privacy.scan([path]) == []


def test_clean_missing_directory_and_nonutf8_inputs(tmp_path):
  clean = tmp_path / "clean.txt"
  clean.write_text("Drive A, 42 m, 0.15 m/s per code\n")
  binary = tmp_path / "unknown.txt"
  binary.write_bytes(b"\xff\xfe")
  assert check_privacy.scan([clean, binary, tmp_path / "missing.txt", tmp_path]) == []


def test_cli_failure_diagnostic_does_not_print_identifier(tmp_path, monkeypatch, capsys):
  monkeypatch.setattr(check_privacy, "REPO", tmp_path)
  path = tmp_path / "example.txt"
  value = CASES[2][1]
  path.write_text(value + "\n")
  monkeypatch.setattr(check_privacy.sys, "argv", ["check_privacy.py", str(path)])
  assert check_privacy.main() == 1
  output = capsys.readouterr().out
  assert "example.txt:1: dongle id" in output
  assert "privacy check: 1 finding(s) in 1 file(s)" in output
  assert value not in output


def test_cli_clean_input_succeeds(tmp_path, monkeypatch, capsys):
  path = tmp_path / "clean.txt"
  path.write_text("Drive A\n")
  monkeypatch.setattr(check_privacy.sys, "argv", ["check_privacy.py", str(path)])
  assert check_privacy.main() == 0
  assert "privacy check: 0 finding(s) in 1 file(s)" in capsys.readouterr().out
