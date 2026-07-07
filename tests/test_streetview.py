"""Tests for the Street View metadata parsing (pure; no network, no API key).

Uses canned metadata-endpoint responses so the parsing + official/user filtering
is locked without spending quota or needing a key.
"""
from ingest.streetview import parse_metadata, is_official

_OK_OFFICIAL = {
    "status": "OK",
    "pano_id": "abc123",
    "location": {"lat": 31.9501, "lng": 35.9301},
    "date": "2022-05",
    "copyright": "© Google",
}
_OK_USER = {
    "status": "OK",
    "pano_id": "user987",
    "location": {"lat": 31.95, "lng": 35.93},
    "date": "2019-08",
    "copyright": "© Jane Doe",
}
_ZERO = {"status": "ZERO_RESULTS"}


def test_official_record_parsed():
    r = parse_metadata(_OK_OFFICIAL)
    assert r["status"] == "OK"
    assert r["pano_id"] == "abc123"
    assert r["lat"] == 31.9501 and r["lon"] == 35.9301
    assert r["date"] == "2022-05"
    assert r["official"] is True


def test_user_contribution_flagged_not_official():
    r = parse_metadata(_OK_USER)
    assert r["status"] == "OK"
    assert r["official"] is False   # caller will reject this as a snap


def test_zero_results():
    r = parse_metadata(_ZERO)
    assert r["status"] == "ZERO_RESULTS"
    assert r["pano_id"] is None
    assert r["official"] is False


def test_is_official():
    assert is_official("© Google") is True
    assert is_official("© Google, Inc.") is True
    assert is_official("© Some Person") is False
    assert is_official(None) is False
