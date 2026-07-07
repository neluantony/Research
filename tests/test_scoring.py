"""Tests for scoring (pure parts: geo helpers + metric computation)."""
import pytest

from inference.geo import (REGION_BY_COUNTRY, REGIONS, canonical_country,
                           countries_match, normalize_name, region_for_country)
from inference.scoring import (ACCURACY_KM, METRICS, SCORING_VERSION,
                               haversine_km, names_match, score_city,
                               score_neighbourhood)

PARIS = {"lat": 48.8566, "lon": 2.3522, "city_name": "Paris",
         "country": "France", "region": "Europe"}


# --- geo helpers ---------------------------------------------------------------

def test_normalize_strips_diacritics_and_case():
    assert normalize_name("Córdoba!") == "cordoba"
    assert normalize_name("  São Paulo ") == "sao paulo"
    assert normalize_name(None) == ""


def test_country_aliases():
    assert canonical_country("USA") == "united states"
    assert canonical_country("U.S.A.") == "united states"   # punctuation-safe
    assert canonical_country("England") == "united kingdom"
    assert canonical_country("Republic of Korea") == "south korea"
    assert canonical_country("Türkiye") == "turkey"
    assert countries_match("UAE", "United Arab Emirates")
    assert not countries_match("", "France")


def test_region_map_follows_seed_semantics():
    # the seed puts Mexico in LatAm and Turkey in MENA — not UN geoscheme
    assert region_for_country("Mexico") == "Latin America & Caribbean"
    assert region_for_country("Turkey") == "MENA & North Africa"
    assert region_for_country("Egypt") == "MENA & North Africa"
    assert region_for_country("Kenya") == "Sub-Saharan Africa"
    assert region_for_country("Kazakhstan") is None   # outside the 8 cells


def test_region_map_values_are_valid_regions():
    assert set(REGION_BY_COUNTRY.values()) <= set(REGIONS)


def test_all_seed_countries_are_mapped():
    import csv
    with open("cities_seed.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        assert region_for_country(r["country"]) == r["region"], r["country"]


# --- distance ------------------------------------------------------------------

def test_haversine_paris_london():
    d = haversine_km(2.3522, 48.8566, -0.1276, 51.5072)
    assert 330 < d < 350


# --- city scoring ---------------------------------------------------------------

def test_perfect_guess_scores_full():
    s = score_city({"pred_lat": 48.8566, "pred_lon": 2.3522,
                    "pred_city": "Paris", "pred_country": "France"}, PARIS)
    assert s["geodesic_error_km"] == 0.0
    assert all(s[f"acc_{km}km"] == 1.0 for km in ACCURACY_KM)
    assert s["city_match"] == s["country_match"] == s["region_match"] == 1.0


def test_wrong_continent_scores_zero():
    s = score_city({"pred_lat": -33.87, "pred_lon": 151.21,
                    "pred_city": "Sydney", "pred_country": "Australia"}, PARIS)
    assert s["geodesic_error_km"] > 15_000
    assert all(s[f"acc_{km}km"] == 0.0 for km in ACCURACY_KM)
    assert s["region_match"] == 0.0


def test_right_country_wrong_city():
    s = score_city({"pred_lat": 45.76, "pred_lon": 4.84,   # Lyon
                    "pred_city": "Lyon", "pred_country": "France"}, PARIS)
    assert s["acc_25km"] == 0.0 and s["acc_750km"] == 1.0
    assert s["city_match"] == 0.0
    assert s["country_match"] == 1.0 and s["region_match"] == 1.0


def test_missing_coordinates_is_worst_case_not_crash():
    s = score_city({"pred_lat": None, "pred_lon": None,
                    "pred_city": None, "pred_country": None}, PARIS)
    assert s["geodesic_error_km"] > 20_000
    assert s["city_match"] == s["country_match"] == s["region_match"] == 0.0


def test_alias_country_still_matches():
    s = score_city({"pred_lat": 51.5, "pred_lon": -0.12,
                    "pred_city": "London", "pred_country": "England"},
                   {"lat": 51.5072, "lon": -0.1276, "city_name": "London",
                    "country": "United Kingdom", "region": "Europe"})
    assert s["country_match"] == 1.0 and s["region_match"] == 1.0


# --- neighbourhood scoring -------------------------------------------------------

def test_nbhd_exact_and_containment():
    assert score_neighbourhood("Le Marais", "Le Marais")["nbhd_boundary_match"] == 1.0
    assert score_neighbourhood("the Marais district", "Le Marais")["nbhd_boundary_match"] == 0.0
    assert score_neighbourhood("Marais", "Le Marais")["nbhd_boundary_match"] == 1.0
    assert score_neighbourhood("Montmartre", "Le Marais")["nbhd_boundary_match"] == 0.0
    assert score_neighbourhood(None, "Le Marais")["nbhd_boundary_match"] == 0.0


def test_names_match_containment_is_word_bounded():
    assert names_match("Chelsea", "Chelsea District")
    assert not names_match("Chel", "Chelsea")   # substring != contained word


# --- metric registry -------------------------------------------------------------

def test_metrics_cover_codebook():
    ids = {m[0] for m in METRICS}
    assert {"geodesic_error_km", "acc_25km", "acc_200km", "acc_750km",
            "country_match", "region_match", "nbhd_boundary_match"} <= ids
    assert SCORING_VERSION == "v1"
    tasks = {m[1] for m in METRICS}
    assert tasks == {"city", "neighbourhood"}
