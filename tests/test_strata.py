"""Tests for the fabric-strata decision rule (pure; no DB, no network).

Pins each branch of codebook classification_rule so a change to the rule is
deliberate and visible.
"""
import pytest

from ingest.strata import classify_stratum, STRATA


def test_heritage_in_core_is_historic():
    assert classify_stratum("core", "residential", heritage=True) == "historic_iconic_core"
    assert classify_stratum("mid", "commercial", heritage=True) == "historic_iconic_core"


def test_heritage_at_edge_is_not_historic():
    # heritage only counts in core/mid; at the edge the function rule applies
    assert classify_stratum("edge", "residential", heritage=True) == "low_density_suburban_residential"


def test_commercial_beats_residential_density():
    assert classify_stratum("core", "commercial", heritage=False) == "commercial_business"
    assert classify_stratum("edge", "commercial", heritage=False) == "commercial_business"


def test_residential_splits_by_zone():
    assert classify_stratum("core", "residential", heritage=False) == "dense_residential"
    assert classify_stratum("mid", "residential", heritage=False) == "dense_residential"
    assert classify_stratum("edge", "residential", heritage=False) == "low_density_suburban_residential"


def test_industrial_or_other_is_peripheral():
    assert classify_stratum("edge", "industrial_other", heritage=False) == "peripheral_edge"
    assert classify_stratum("core", "industrial_other", heritage=False) == "peripheral_edge"


def test_every_branch_returns_a_valid_stratum():
    for zone in ("core", "mid", "edge"):
        for function in ("commercial", "residential", "industrial_other"):
            for heritage in (True, False):
                assert classify_stratum(zone, function, heritage) in STRATA


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        classify_stratum("downtown", "residential", heritage=False)
    with pytest.raises(ValueError):
        classify_stratum("core", "farmland", heritage=False)
