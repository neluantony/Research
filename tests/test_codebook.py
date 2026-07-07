"""Unit tests for the pure codebook parser (no DB, no network).

Run with:  python -m pytest tests/test_codebook.py
These assertions pin the parser against the real codebook.yaml so a future edit
that breaks the spec sync fails loudly.
"""
from ingest.codebook import load_codebook, parse_fabric_strata, parse_variables


def test_all_constructs_present():
    variables = parse_variables(load_codebook())
    constructs = {v.construct for v in variables}
    assert constructs == {"imageability", "cultural_visibility", "confound", "key"}


def test_variable_ids_unique():
    # parse_variables raises on duplicates; reaching here means they are unique.
    variables = parse_variables(load_codebook())
    ids = [v.variable_id for v in variables]
    assert len(ids) == len(set(ids))


def test_known_variables_classified():
    by_id = {v.variable_id: v for v in parse_variables(load_codebook())}
    # physical landmark lives in imageability; its fame twin in cultural visibility
    assert by_id["lmk_immediate"].construct == "imageability"
    assert by_id["lmk_fame"].construct == "cultural_visibility"
    # the QID key is classified as a key, not a predictor
    assert by_id["entity_qid"].construct == "key"


def test_temporal_flag():
    by_id = {v.variable_id: v for v in parse_variables(load_codebook())}
    # pageview proxies are snapshotted in the model training window
    assert by_id["prom_en_pageviews"].is_temporal is True
    assert by_id["prom_local_pageviews"].is_temporal is True
    # a structural imageability proxy is not temporal
    assert by_id["edge_water"].is_temporal is False


def test_spatial_scales_normalised_to_list():
    by_id = {v.variable_id: v for v in parse_variables(load_codebook())}
    # single scalar scale -> single-element list
    assert by_id["edge_water"].spatial_scales == ["point"]
    # dual-scale variable -> multi-element list
    assert set(by_id["node_intersection"].spatial_scales) == {"point", "neighbourhood"}


def test_five_fabric_strata():
    strata = parse_fabric_strata(load_codebook())
    assert len(strata) == 5
    assert "historic_iconic_core" in strata
