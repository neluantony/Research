"""Small read-only helpers for the public Wikidata API (stdlib urllib).

Only used while building the dataset — the models under test never see
any of this.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

API = "https://www.wikidata.org/w/api.php"
USER_AGENT = (
    "UrbanImageabilityVLM/0.1 (Middlesex University London research; "
    "neluanthony@gmail.com)"
)


def api_get(params: dict) -> dict:
    params = {**params, "format": "json"}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_coordinates(qids: list[str]) -> dict[str, tuple[float, float]]:
    """Map each QID to its (lon, lat) from the P625 'coordinate location' claim.

    Returns (lon, lat) — the order PostGIS ST_MakePoint expects. QIDs without a
    coordinate are simply absent from the result (never invented).
    """
    out: dict[str, tuple[float, float]] = {}
    for i in range(0, len(qids), 50):  # 50-id API limit
        chunk = qids[i:i + 50]
        data = api_get({
            "action": "wbgetentities", "ids": "|".join(chunk),
            "props": "claims", "languages": "en",
        })
        for qid, ent in data.get("entities", {}).items():
            for c in ent.get("claims", {}).get("P625", []):
                try:
                    v = c["mainsnak"]["datavalue"]["value"]
                    out[qid] = (float(v["longitude"]), float(v["latitude"]))
                    break
                except (KeyError, TypeError, ValueError):
                    continue
    return out
