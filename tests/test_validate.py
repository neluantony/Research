"""Tests for the seed/codebook validator (no DB, no network).

The first test pins the *real* repo data as clean; the rest inject deliberate
faults to prove each check fires.
"""
from ingest import validate


def _good_row(**over):
    row = {
        "city_id": "paris", "city_name": "Paris", "country": "France",
        "region": "Europe", "population_tier": "mega",
        "prominence_tier": "iconic", "design_role": "anchor_iconic",
        "sv_coverage_status": "ok", "entity_qid": "", "notes": "",
    }
    row.update(over)
    return row


def test_real_seed_and_codebook_are_clean():
    assert validate.validate_all() == []


def test_bad_enum_value_flagged():
    errs = validate.validate_seed([_good_row(design_role="not_a_role")])
    assert any("design_role" in e for e in errs)


def test_duplicate_city_id_flagged():
    errs = validate.validate_seed([_good_row(), _good_row(city_name="Paris 2")])
    assert any("duplicate city_id" in e for e in errs)


def test_non_slug_city_id_flagged():
    errs = validate.validate_seed([_good_row(city_id="New York")])
    assert any("lowercase slug" in e for e in errs)


def test_malformed_qid_flagged():
    errs = validate.validate_seed([_good_row(entity_qid="12345")])
    assert any("not a valid Wikidata QID" in e for e in errs)


def test_well_formed_qid_accepted():
    errs = validate.validate_seed([_good_row(entity_qid="Q90")])
    assert errs == []


def test_missing_column_flagged():
    errs = validate.validate_seed([{"city_id": "paris"}])
    assert any("missing columns" in e for e in errs)
