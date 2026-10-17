from pathlib import Path

import pytest

from app.services import normalize

FIXTURES = Path(__file__).parent / "fixtures" / "data"


# ------------------------------- field helpers -------------------------------
def test_blank_to_none():
    assert normalize._blank_to_none("  ") is None
    assert normalize._blank_to_none("") is None
    assert normalize._blank_to_none(None) is None
    assert normalize._blank_to_none("  x  ") == "x"


def test_parse_timestamp_valid():
    assert normalize.parse_timestamp("2026-09-01 00:56:20") == "2026-09-01T00:56:20+00:00"


def test_parse_timestamp_bad_raises():
    with pytest.raises(normalize.RowError):
        normalize.parse_timestamp("not-a-timestamp")
    with pytest.raises(normalize.RowError):
        normalize.parse_timestamp("")


def test_parse_yn():
    assert normalize.parse_yn("Y", "registered_device") is True
    assert normalize.parse_yn("n", "registered_device") is False
    with pytest.raises(normalize.RowError):
        normalize.parse_yn("maybe", "registered_device")


def test_parse_numeric():
    assert normalize.parse_numeric("3633.85", "amount") == 3633.85
    assert normalize.parse_numeric("", "amount") is None
    with pytest.raises(normalize.RowError):
        normalize.parse_numeric("not-a-number", "amount")


def test_parse_int():
    assert normalize.parse_int("200", "status_code") == 200
    with pytest.raises(normalize.RowError):
        normalize.parse_int("abc", "status_code")


def test_parse_date():
    assert normalize.parse_date("2026-06-28") == "2026-06-28"
    assert normalize.parse_date("") is None
    with pytest.raises(normalize.RowError):
        normalize.parse_date("28-06-2026")


# ------------------------------- row normalizers -------------------------------
def test_normalize_auth_row_valid():
    row = {"event_id": "E000001", "timestamp": "2026-09-01 00:56:20", "user_id": "U0568",
           "ip_address": "103.21.230.29", "device_id": "D00739", "event_type": "login",
           "status": "success", "location": "Mumbai, IN", "mfa_status": "not_required"}
    parsed = normalize.normalize_auth_row(row)
    assert parsed.event["event_id"] == "E000001"
    assert parsed.event["event_kind"] == "login"
    assert parsed.event["source_type"] == "auth"
    assert parsed.event["ts"] == "2026-09-01T00:56:20+00:00"
    assert parsed.event["mfa_status"] == "not_required"
    assert parsed.raw == {"source_type": "auth", "source_event_id": "E000001", "payload": dict(row)}


def test_normalize_auth_row_blank_fields_become_none():
    row = {"event_id": "E000003", "timestamp": "2026-09-01 01:00:00", "user_id": "",
           "ip_address": "1.2.3.5", "device_id": "", "event_type": "logout",
           "status": "success", "location": "", "mfa_status": "n/a"}
    parsed = normalize.normalize_auth_row(row)
    assert parsed.event["user_id"] is None
    assert parsed.event["device_id"] is None
    assert parsed.event["location"] is None
    # mfa_status 'n/a' is content, not blank -- kept exactly
    assert parsed.event["mfa_status"] == "n/a"


def test_normalize_auth_row_blank_mfa_status_is_null():
    row = {"event_id": "E000004", "timestamp": "2026-09-01 01:05:00", "user_id": "U0999",
           "ip_address": "1.2.3.6", "device_id": "D00999", "event_type": "login",
           "status": "success", "location": "Delhi, IN", "mfa_status": ""}
    parsed = normalize.normalize_auth_row(row)
    assert parsed.event["mfa_status"] is None


def test_normalize_auth_row_bad_timestamp_raises():
    row = {"event_id": "E000002", "timestamp": "BADTIMESTAMP", "user_id": "U0001",
           "ip_address": "1.2.3.4", "device_id": "D00001", "event_type": "login",
           "status": "success", "location": "Pune", "mfa_status": "n/a"}
    with pytest.raises(normalize.RowError):
        normalize.normalize_auth_row(row)


def test_normalize_api_row_status_code_int_and_status_left_null():
    row = {"event_id": "A000001", "timestamp": "2026-09-01 00:45:54", "user_id": "U0407",
           "ip_address": "49.36.172.53", "endpoint": "/api/v1/transfer", "method": "POST",
           "status_code": "200"}
    parsed = normalize.normalize_api_row(row)
    assert parsed.event["status_code"] == 200
    assert isinstance(parsed.event["status_code"], int)
    assert parsed.event["status"] is None       # never invented
    assert parsed.event["http_method"] == "POST"


def test_normalize_api_row_bad_status_code_raises():
    row = {"event_id": "A000002", "timestamp": "2026-09-01 00:46:00", "user_id": "U0001",
           "ip_address": "1.2.3.4", "endpoint": "/api/v1/login", "method": "GET",
           "status_code": "abc"}
    with pytest.raises(normalize.RowError):
        normalize.normalize_api_row(row)


def test_normalize_transaction_row_amount_numeric():
    row = {"transaction_id": "T000001", "timestamp": "2026-09-01 00:45:54", "user_id": "U0407",
           "amount": "3633.85", "merchant": "BigBasket", "device_id": "D00525",
           "ip_address": "49.36.172.53", "location": "Mumbai, IN", "status": "success"}
    parsed = normalize.normalize_transaction_row(row)
    assert parsed.event["event_id"] == "T000001"
    assert parsed.event["event_kind"] == "transaction"
    assert parsed.event["amount"] == 3633.85


def test_normalize_user_device_row_yn_and_key():
    row = {"user_id": "U0001", "device_id": "D00001", "registered_device": "Y",
           "usual_location": "Hyderabad, IN", "usual_ip": "49.207.174.190",
           "secondary_ip": "49.207.152.109", "device_type": "android", "avg_txn_amount": "1100"}
    record = normalize.normalize_user_device_row(row)
    assert record["registered_device"] is True
    assert record["avg_txn_amount"] == 1100.0


def test_normalize_user_device_row_bad_yn_raises():
    row = {"user_id": "U0003", "device_id": "D00003", "registered_device": "X",
           "usual_location": "Pune, IN", "usual_ip": "1.2.3.6", "secondary_ip": "1.2.3.7",
           "device_type": "web", "avg_txn_amount": "300"}
    with pytest.raises(normalize.RowError):
        normalize.normalize_user_device_row(row)


def test_normalize_threat_indicator_row_bad_level_raises():
    row = {"ip_address": "1.2.3.4", "indicator_type": "IP", "threat_level": "Severe",
           "source": "Bad feed", "description": "Bad threat level", "last_seen": "2026-06-01"}
    with pytest.raises(normalize.RowError):
        normalize.normalize_threat_indicator_row(row)


# --------------------------------- CSV reading ---------------------------------
def test_read_csv_rows_handles_bom_and_crlf():
    rows = list(normalize.read_csv_rows(FIXTURES / "authentication_logs.csv"))
    assert len(rows) == 4
    line_no, first = rows[0]
    assert line_no == 2
    assert first["event_id"] == "E000001"       # BOM did not leak into the first field name/value


def test_count_data_rows():
    assert normalize.count_data_rows(FIXTURES / "authentication_logs.csv") == 4
    assert normalize.count_data_rows(FIXTURES / "threat_indicators.csv") == 3


# ------------------------------- rejected-row reporting -------------------------------
def test_rejected_row_reporting_via_fixture_file():
    rejected = []
    written = 0
    for line_no, row in normalize.read_csv_rows(FIXTURES / "authentication_logs.csv"):
        try:
            normalize.normalize_auth_row(row)
            written += 1
        except normalize.RowError as exc:
            rejected.append(normalize.RejectedRow(
                "authentication_logs.csv", line_no,
                normalize.row_id_for_report("authentication_logs.csv", row), str(exc)))
    assert written == 3
    assert len(rejected) == 1
    assert rejected[0].file == "authentication_logs.csv"
    assert rejected[0].line == 3                 # E000002 is the second data row -> line 3
    assert rejected[0].id == "E000002"
    assert "timestamp" in rejected[0].reason


# ------------------------------------ allowlist ------------------------------------
def test_allowed_files_is_exactly_the_five_expected():
    assert set(normalize.ALLOWED_FILES) == {
        "authentication_logs.csv", "api_logs.csv", "transactions.csv",
        "users_devices.csv", "threat_indicators.csv",
    }


@pytest.mark.parametrize("bad_name", [
    "ground_truth_events.csv",
    "ground_truth_scenarios.csv",
    "README.md",
    "../data/authentication_logs.csv",
    "authentication_logs.csv.bak",
])
def test_disallowed_filenames_rejected(bad_name):
    assert bad_name not in normalize.ALLOWED_FILES
