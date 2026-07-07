"""Find each city's Wikidata QID.

Searches Wikidata for every city without a QID, keeps candidates whose
country matches the seed, and proposes one only when a single candidate is
left. All proposals go to qid_proposals.csv for review; the DB is only
written with --write, and only for confident matches. Ambiguous cases are
left for a human — a QID is never guessed.
"""
from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

import psycopg

from .paths import CITIES_SEED, REPO_ROOT
from .load_seed import _read_seed

API = "https://www.wikidata.org/w/api.php"

# A candidate counts as a settlement if any of its 'instance of' labels
# contains one of these words. This keeps 'megacity', 'commune of France',
# 'municipality of Brazil' etc. while dropping universities, airlines and
# states. Simpler and more reliable than the SPARQL endpoint, which kept
# rate-limiting us.
SETTLEMENT_KEYWORDS = (
    "city", "town", "municipality", "capital", "settlement", "metropolis",
    "borough", "commune", "village", "ward", "urban", "conurbation", "prefecture",
)
# Wikidata asks for a descriptive User-Agent identifying the project + contact.
USER_AGENT = (
    "UrbanImageabilityVLM/0.1 (Middlesex University London research; "
    "neluanthony@gmail.com)"
)
REQUEST_PAUSE_S = 0.3  # polite throttle between API calls

# Seed country string -> Wikidata English country label, where they differ.
COUNTRY_ALIASES = {
    "United States": {"United States", "United States of America"},
    "United Kingdom": {"United Kingdom", "United Kingdom of Great Britain and Northern Ireland"},
    "South Korea": {"South Korea", "Republic of Korea"},
}


@dataclass
class Proposal:
    city_id: str
    city_name: str
    country: str
    proposed_qid: str | None
    candidate_label: str | None
    candidate_description: str | None
    confident: bool
    note: str


def _api_get(params: dict) -> dict:
    params = {**params, "format": "json"}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _search(name: str, limit: int = 10) -> list[dict]:
    data = _api_get({
        "action": "wbsearchentities", "search": name,
        "language": "en", "type": "item", "limit": limit,
    })
    return data.get("search", [])


def _labels(qids: list[str]) -> dict[str, str]:
    """English labels for a batch of QIDs (chunked to the 50-id API limit)."""
    out: dict[str, str] = {}
    for i in range(0, len(qids), 50):
        chunk = qids[i:i + 50]
        data = _api_get({
            "action": "wbgetentities", "ids": "|".join(chunk),
            "props": "labels", "languages": "en",
        })
        for q, ent in data.get("entities", {}).items():
            out[q] = ent.get("labels", {}).get("en", {}).get("value", "")
    return out


def _is_settlement(type_labels: list[str]) -> bool:
    return any(any(k in t.lower() for k in SETTLEMENT_KEYWORDS) for t in type_labels)


def _candidate_facts(qids: list[str]) -> dict[str, dict]:
    """Per candidate: P17 country label, P31 type labels, sitelink count, is_settlement.

    Sitelink count (number of Wikimedia editions linking the item) ranks
    same-name entities — the real city far outweighs a university, gazette or the
    surrounding state. ``is_settlement`` (from the 'instance of' type labels) is
    what proves a candidate is a place at all.
    """
    if not qids:
        return {}
    data = _api_get({
        "action": "wbgetentities", "ids": "|".join(qids),
        "props": "claims|sitelinks", "languages": "en",
    })
    facts: dict[str, dict] = {}
    need: set[str] = set()  # QIDs whose labels we must resolve (countries + types)
    for qid, ent in data.get("entities", {}).items():
        claims = ent.get("claims", {})
        cq = None
        for c in claims.get("P17", []):
            try:
                cq = c["mainsnak"]["datavalue"]["value"]["id"]
                break
            except (KeyError, TypeError):
                continue
        type_qids: list[str] = []
        for c in claims.get("P31", []):
            try:
                type_qids.append(c["mainsnak"]["datavalue"]["value"]["id"])
            except (KeyError, TypeError):
                continue
        facts[qid] = {
            "country_qid": cq, "type_qids": type_qids,
            "sitelinks": len(ent.get("sitelinks", {}) or {}),
        }
        if cq:
            need.add(cq)
        need.update(type_qids)

    labels = _labels(sorted(need))
    for f in facts.values():
        f["country"] = labels.get(f["country_qid"], "")
        f["is_settlement"] = _is_settlement([labels.get(t, "") for t in f["type_qids"]])
    return facts


def _country_matches(seed_country: str, wd_country: str) -> bool:
    if not wd_country:
        return False
    allowed = COUNTRY_ALIASES.get(seed_country, {seed_country})
    return wd_country in allowed


# A proposal is auto-writable only if the chosen settlement has a clear sitelink
# lead over the runner-up settlement and a non-trivial absolute count.
SITELINK_LEAD = 1.3       # top must beat the runner-up by this factor
SITELINK_FLOOR = 20       # ...and have at least this many sitelinks
DOMINANT_OUTLIER = 1.5    # a non-settlement this far above the pick -> defer
COUNTRY_OVERRIDE = 2.0    # a no-country settlement must beat the in-country one
                          # by this much to override it (London 2.8x yes; Ankara/Accra 1.2x no)


def resolve_city(row: dict[str, str]) -> Proposal:
    name, country, city_id = row["city_name"], row["country"], row["city_id"]
    candidates = _search(name, limit=15)
    time.sleep(REQUEST_PAUSE_S)
    if not candidates:
        return Proposal(city_id, name, country, None, None, None, False,
                        "no search results")

    facts = _candidate_facts([c["id"] for c in candidates])
    time.sleep(REQUEST_PAUSE_S)

    def sl(c: dict) -> int:
        return facts.get(c["id"], {}).get("sitelinks", 0)

    def country_ok(c: dict) -> bool:
        return _country_matches(country, facts.get(c["id"], {}).get("country", ""))

    def is_settlement(c: dict) -> bool:
        return facts.get(c["id"], {}).get("is_settlement", False)

    settlement_cands = sorted((c for c in candidates if is_settlement(c)),
                              key=sl, reverse=True)
    global_top = max(candidates, key=sl)

    if not settlement_cands:
        # Nothing place-like in the results — defer entirely to the reviewer.
        return Proposal(city_id, name, country, global_top["id"],
                        global_top.get("label"), global_top.get("description"),
                        False, f"no settlement-typed candidate (top sitelinks {sl(global_top)})")

    # Prefer the most-linked settlement IN the seed country. A no-country
    # settlement (London/Berlin/Singapore lack a P17) overrides it only when it
    # dominates by a wide margin — so London (250) beats Derry (89), but a foreign
    # fuzzy-match like Ankara (238) does NOT displace the real Accra (197).
    top_any = settlement_cands[0]
    in_country = [c for c in settlement_cands if country_ok(c)]
    override = (bool(in_country) and not country_ok(top_any)
                and sl(top_any) >= COUNTRY_OVERRIDE * sl(in_country[0]))
    if in_country and not override:
        chosen, pool = in_country[0], in_country
    else:
        chosen, pool = top_any, settlement_cands

    # If a non-settlement homonym hugely outweighs the pick (e.g. Singapore the
    # city-state, or a famous film), surface that prominent item for the reviewer.
    if not is_settlement(global_top) and sl(global_top) >= DOMINANT_OUTLIER * sl(chosen):
        return Proposal(city_id, name, country, global_top["id"],
                        global_top.get("label"), global_top.get("description"), False,
                        f"most-linked candidate '{global_top.get('label')}' "
                        f"({sl(global_top)}) is not typed as a settlement; "
                        f"settlement runner-up '{chosen.get('label')}' ({sl(chosen)}) — review")

    next_sl = sl(pool[1]) if len(pool) > 1 else 0
    clear = len(pool) == 1 or sl(chosen) >= SITELINK_LEAD * next_sl
    confident = clear and sl(chosen) >= SITELINK_FLOOR
    country_state = "country match" if country_ok(chosen) else "country unconfirmed"
    note = f"top settlement by sitelinks ({sl(chosen)} vs next {next_sl}); {country_state}"
    return Proposal(city_id, name, country, chosen["id"], chosen.get("label"),
                    chosen.get("description"), confident, note)


def resolve_all(conn: psycopg.Connection | None, write: bool) -> list[Proposal]:
    """Resolve every seed city whose QID is empty. Returns all proposals.

    If ``write`` and a live connection are given, confident proposals are written
    to ``cities.entity_qid`` only where it is currently NULL.
    """
    rows = _read_seed(CITIES_SEED)
    proposals: list[Proposal] = []
    for row in rows:
        if (row.get("entity_qid") or "").strip():
            continue  # already resolved in the seed
        proposals.append(resolve_city(row))

    out_path = REPO_ROOT / "qid_proposals.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["city_id", "city_name", "country", "proposed_qid",
                    "candidate_label", "candidate_description", "confident", "note"])
        for p in proposals:
            w.writerow([p.city_id, p.city_name, p.country, p.proposed_qid or "",
                        p.candidate_label or "", p.candidate_description or "",
                        p.confident, p.note])

    if write and conn is not None:
        confident = [p for p in proposals if p.confident and p.proposed_qid]
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE cities SET entity_qid = %s
                WHERE city_id = %s AND entity_qid IS NULL
                """,
                [(p.proposed_qid, p.city_id) for p in confident],
            )
        conn.commit()

    return proposals
