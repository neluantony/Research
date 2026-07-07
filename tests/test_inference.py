"""Tests for the inference harness's pure parts (no DB, no network, no key)."""
import json

import pytest

from inference.harness import parse_city_fields, parse_neighbourhood_fields
from inference.prompts import CUE_TYPES, PROMPTS
from inference.providers import MockProvider, build_user_content, media_type_for
from inference.registry import load_models_seed


# --- prompt/schema integrity --------------------------------------------------

def _walk_objects(schema):
    """Yield every object-typed schema node (for constraint checks)."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for v in schema.values():
            yield from _walk_objects(v)
    elif isinstance(schema, list):
        for v in schema:
            yield from _walk_objects(v)


def test_prompts_cover_both_tasks_with_unique_versions():
    assert {p["task"] for p in PROMPTS} == {"city", "neighbourhood"}
    versions = [(p["prompt_version"], p["task"]) for p in PROMPTS]
    assert len(versions) == len(set(versions))


def test_schemas_meet_structured_output_constraints():
    # every object: additionalProperties false + all properties required
    for p in PROMPTS:
        for obj in _walk_objects(p["output_schema"]):
            assert obj.get("additionalProperties") is False
            assert set(obj["required"]) == set(obj["properties"].keys())


def test_cue_types_isolate_text_from_lynch_elements():
    # the OCR confound must be its own category, never folded into the
    # Lynch elements (codebook design principle text_cue_isolated)
    assert "text_signage" in CUE_TYPES
    for lynch in ("landmark", "district", "node", "edge", "path"):
        assert lynch in CUE_TYPES


def test_neighbourhood_prompt_gives_the_city():
    nbhd = next(p for p in PROMPTS if p["task"] == "neighbourhood")
    assert "{city_name}" in nbhd["text"]      # the model is TOLD the city
    city = next(p for p in PROMPTS if p["task"] == "city")
    assert "{" not in city["text"]            # city prompt has no placeholders


# --- models seed --------------------------------------------------------------

def test_models_seed_refuses_unpinned_versions():
    ready, skipped = load_models_seed()
    assert all(m["exact_version_string"].strip() for m in ready)
    # the placeholders (gpt/gemini/open-weight) must be skipped, not guessed
    assert any("PIN" in name for name in skipped)


# --- request building ---------------------------------------------------------

def test_media_type_mapping():
    assert media_type_for("x/h000.jpg") == "image/jpeg"
    assert media_type_for("x/h090.png") == "image/png"
    with pytest.raises(ValueError):
        media_type_for("x/h000.tiff")


def test_build_user_content_order(tmp_path):
    paths = []
    for h in (0, 90, 180, 270):
        p = tmp_path / f"h{h:03d}.jpg"
        p.write_bytes(bytes([h % 251]))
        paths.append(p)
    content = build_user_content(paths, "where is this?")
    assert [b["type"] for b in content] == ["image"] * 4 + ["text"]
    assert content[-1]["text"] == "where is this?"
    assert all(b["source"]["type"] == "base64" for b in content[:4])


# --- response parsing ---------------------------------------------------------

def test_parse_city_fields():
    parsed = {"city": "Paris", "country": "France", "latitude": 48.85,
              "longitude": 2.35, "confidence": 0.9, "cues": [], "reasoning": "r"}
    f = parse_city_fields(parsed)
    assert f == {"pred_city": "Paris", "pred_country": "France",
                 "pred_lat": 48.85, "pred_lon": 2.35, "reasoning_text": "r"}


def test_parse_fields_survive_refusal():
    assert parse_city_fields(None)["pred_city"] is None
    assert parse_neighbourhood_fields(None)["pred_city"] is None


def test_parse_neighbourhood_fields():
    f = parse_neighbourhood_fields({"neighbourhood": "Le Marais",
                                    "confidence": 0.7, "cues": [], "reasoning": "r"})
    assert f["pred_city"] == "Le Marais"      # free-text name; resolved at scoring
    assert f["pred_lat"] is None


# --- mock provider end-to-end shape -------------------------------------------

def test_mock_provider_contract(tmp_path):
    p = tmp_path / "h000.jpg"
    p.write_bytes(b"x")
    mock = MockProvider()
    out = mock.complete("prompt", [p], {"type": "object"})
    assert set(out) == {"raw", "parsed", "latency_ms", "tokens", "model_reported"}
    assert json.loads(out["raw"]["text"]) == out["parsed"]
    assert mock.calls[0]["prompt_text"] == "prompt"
