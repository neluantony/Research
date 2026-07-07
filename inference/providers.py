"""Adapters for the model APIs — one complete() call per point.

Every adapter takes the same inputs (prompt text, the 4 image files in
order, the output JSON schema) and returns the same record shape. None of
them passes tools or web search to the API: the models see the images and
the question, nothing else.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".png": "image/png", ".webp": "image/webp"}


def media_type_for(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix not in MEDIA_TYPES:
        raise ValueError(f"unsupported image type: {suffix}")
    return MEDIA_TYPES[suffix]


def build_user_content(image_paths: list, prompt_text: str) -> list[dict]:
    """Anthropic-style content blocks: the 4 views in order, then the prompt.

    The block order IS the presentation order (N, E, S, W — the caller sorts
    by heading); the prompt text references that order explicitly.
    """
    content = []
    for p in image_paths:
        data = base64.standard_b64encode(Path(p).read_bytes()).decode("utf-8")
        content.append({
            "type": "image",
            "source": {"type": "base64",
                       "media_type": media_type_for(p),
                       "data": data},
        })
    content.append({"type": "text", "text": prompt_text})
    return content


class AnthropicProvider:
    """Claude via the Messages API with structured output (json_schema)."""

    def __init__(self, model_id: str, max_tokens: int = 4096):
        import anthropic

        self.model_id = model_id
        self.max_tokens = max_tokens
        self._client = anthropic.Anthropic()

    def complete(self, prompt_text: str, image_paths: list, schema: dict) -> dict:
        t0 = time.monotonic()
        resp = self._client.messages.create(
            model=self.model_id,
            max_tokens=self.max_tokens,
            # structured output: the first text block is guaranteed-valid JSON
            output_config={"format": {"type": "json_schema", "schema": schema}},
            # no tools / web search — the model must answer from what it knows
            messages=[{"role": "user",
                       "content": build_user_content(image_paths, prompt_text)}],
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        if resp.stop_reason == "refusal":
            return {"raw": {"stop_reason": "refusal",
                            "stop_details": getattr(resp, "stop_details", None) and
                                            resp.stop_details.__dict__},
                    "parsed": None, "latency_ms": latency_ms,
                    "tokens": resp.usage.output_tokens,
                    "model_reported": resp.model}
        text = next(b.text for b in resp.content if b.type == "text")
        return {"raw": {"text": text, "stop_reason": resp.stop_reason,
                        "usage": {"input_tokens": resp.usage.input_tokens,
                                  "output_tokens": resp.usage.output_tokens}},
                "parsed": json.loads(text), "latency_ms": latency_ms,
                "tokens": resp.usage.output_tokens,
                "model_reported": resp.model}


class MockProvider:
    """Deterministic stand-in for tests and --mock dry runs (no network)."""

    def __init__(self, canned: dict | None = None):
        self.canned = canned or {
            "city": "Testville", "country": "Testland",
            "latitude": 1.0, "longitude": 2.0, "confidence": 0.5,
            "cues": [{"cue_type": "landmark", "description": "a test tower"}],
            "reasoning": "mock",
        }
        self.calls: list[dict] = []

    def complete(self, prompt_text: str, image_paths: list, schema: dict) -> dict:
        self.calls.append({"prompt_text": prompt_text,
                           "image_paths": list(image_paths), "schema": schema})
        return {"raw": {"text": json.dumps(self.canned), "stop_reason": "end_turn"},
                "parsed": dict(self.canned), "latency_ms": 1, "tokens": 42,
                "model_reported": "mock"}
