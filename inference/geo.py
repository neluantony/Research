"""Country-name handling for scoring: normalisation, aliases, regions.

The 8 macro-regions are the project's own region cells, not the UN scheme —
Mexico counts as Latin America and Turkey as MENA, same as in the seed.
Countries outside the 8 cells (Central Asia, the Caucasus) map to None and
can never produce a region match. Pure functions only; changing this
mapping means bumping the scoring version.
"""
from __future__ import annotations

import re
import unicodedata

REGIONS = (
    "North America", "Latin America & Caribbean", "Europe",
    "MENA & North Africa", "Sub-Saharan Africa", "South Asia",
    "East & Southeast Asia", "Oceania",
)


def normalize_name(s: str | None) -> str:
    """Casefold, strip diacritics, collapse punctuation/whitespace."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s.casefold())
    return s.strip()


# alias (normalized) -> canonical country (normalized)
_ALIASES = {
    "usa": "united states", "us": "united states", "america": "united states",
    "united states of america": "united states",
    "u s a": "united states", "u s": "united states",   # punctuation-normalized forms
    "u k": "united kingdom",
    "uk": "united kingdom", "great britain": "united kingdom",
    "england": "united kingdom", "scotland": "united kingdom",
    "wales": "united kingdom", "northern ireland": "united kingdom",
    "uae": "united arab emirates", "emirates": "united arab emirates",
    "korea": "south korea", "republic of korea": "south korea",
    "czechia": "czech republic",
    "cote d ivoire": "ivory coast",
    "burma": "myanmar",
    "drc": "democratic republic of the congo",
    "dr congo": "democratic republic of the congo",
    "democratic republic of congo": "democratic republic of the congo",
    "congo kinshasa": "democratic republic of the congo",
    "congo": "republic of the congo",
    "congo brazzaville": "republic of the congo",
    "holland": "netherlands",
    "russian federation": "russia",
    "turkiye": "turkey",
    "swaziland": "eswatini",
    "macedonia": "north macedonia",
    "east timor": "timor leste",
    "palestinian territories": "palestine",
    "hong kong sar": "hong kong",
    "viet nam": "vietnam",
}

_REGION_COUNTRIES = {
    "North America": [
        "united states", "canada",
    ],
    "Latin America & Caribbean": [
        "mexico", "guatemala", "belize", "honduras", "el salvador", "nicaragua",
        "costa rica", "panama", "cuba", "jamaica", "haiti", "dominican republic",
        "puerto rico", "trinidad and tobago", "colombia", "venezuela", "ecuador",
        "peru", "brazil", "bolivia", "paraguay", "chile", "argentina", "uruguay",
        "guyana", "suriname",
    ],
    "Europe": [
        "united kingdom", "ireland", "france", "spain", "portugal", "germany",
        "netherlands", "belgium", "luxembourg", "switzerland", "austria", "italy",
        "malta", "greece", "cyprus", "denmark", "norway", "sweden", "finland",
        "iceland", "estonia", "latvia", "lithuania", "poland", "czech republic",
        "slovakia", "hungary", "slovenia", "croatia", "bosnia and herzegovina",
        "serbia", "montenegro", "north macedonia", "albania", "kosovo", "romania",
        "bulgaria", "moldova", "ukraine", "belarus", "russia",
    ],
    "MENA & North Africa": [
        "turkey", "syria", "lebanon", "israel", "palestine", "jordan", "iraq",
        "iran", "saudi arabia", "yemen", "oman", "united arab emirates", "qatar",
        "bahrain", "kuwait", "egypt", "libya", "tunisia", "algeria", "morocco",
        "western sahara", "sudan",
    ],
    "Sub-Saharan Africa": [
        "mauritania", "mali", "niger", "chad", "senegal", "gambia",
        "guinea bissau", "guinea", "sierra leone", "liberia", "ivory coast",
        "ghana", "togo", "benin", "burkina faso", "nigeria", "cameroon",
        "central african republic", "south sudan", "ethiopia", "eritrea",
        "djibouti", "somalia", "kenya", "uganda", "rwanda", "burundi", "tanzania",
        "democratic republic of the congo", "republic of the congo", "gabon",
        "equatorial guinea", "angola", "zambia", "malawi", "mozambique",
        "zimbabwe", "botswana", "namibia", "south africa", "lesotho", "eswatini",
        "madagascar", "mauritius", "cape verde",
    ],
    "South Asia": [
        "india", "pakistan", "bangladesh", "sri lanka", "nepal", "bhutan",
        "maldives", "afghanistan",
    ],
    "East & Southeast Asia": [
        "china", "japan", "south korea", "north korea", "taiwan", "hong kong",
        "macau", "mongolia", "vietnam", "laos", "cambodia", "thailand", "myanmar",
        "malaysia", "singapore", "indonesia", "philippines", "brunei",
        "timor leste",
    ],
    "Oceania": [
        "australia", "new zealand", "papua new guinea", "fiji", "samoa", "tonga",
        "vanuatu", "solomon islands",
    ],
}

# canonical country (normalized) -> region
REGION_BY_COUNTRY = {c: region for region, countries in _REGION_COUNTRIES.items()
                     for c in countries}


def canonical_country(s: str | None) -> str:
    """Normalize a country name and resolve known aliases."""
    n = normalize_name(s)
    return _ALIASES.get(n, n)


def region_for_country(s: str | None) -> str | None:
    """The project macro-region for a country name, or None if unmapped."""
    return REGION_BY_COUNTRY.get(canonical_country(s))


def countries_match(pred: str | None, true: str | None) -> bool:
    a, b = canonical_country(pred), canonical_country(true)
    return bool(a) and a == b
