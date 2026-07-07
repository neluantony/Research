"""The rule that assigns a point to one of the 5 fabric strata.

Takes (innerness zone, land-use function, heritage flag) and returns the
stratum, first matching rule wins — a direct transcription of the
classification_rule in codebook.yaml. Computing the inputs (density,
land use) happens in density.py / osm.py / classify.py.
"""
from __future__ import annotations

STRATA = (
    "historic_iconic_core",
    "dense_residential",
    "commercial_business",
    "low_density_suburban_residential",
    "peripheral_edge",
)

ZONES = ("core", "mid", "edge")               # within-city innerness tertiles
FUNCTIONS = ("commercial", "residential", "industrial_other")

_INNER = ("core", "mid")                       # "core/mid" in the codebook rule


def classify_stratum(zone: str, function: str, heritage: bool) -> str:
    """Map (zone, function, heritage) to a fabric stratum (first match wins).

    zone: one of ZONES; function: one of FUNCTIONS; heritage: bool.
    Mirrors codebook classification_rule exactly.
    """
    if zone not in ZONES:
        raise ValueError(f"zone must be one of {ZONES}, got {zone!r}")
    if function not in FUNCTIONS:
        raise ValueError(f"function must be one of {FUNCTIONS}, got {function!r}")

    if heritage and zone in _INNER:
        return "historic_iconic_core"
    if function == "commercial":
        return "commercial_business"
    if function == "residential":
        return "dense_residential" if zone in _INNER else "low_density_suburban_residential"
    return "peripheral_edge"
