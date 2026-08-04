"""Adapters for the model APIs, one complete() call per point.

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

    The block order IS the presentation order (N, E, S, W, sorted by heading
    by the caller); the prompt text references that order explicitly.
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
            # no tools / web search: the model must answer from what it knows
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


def gemini_schema(schema: dict) -> dict:
    """Gemini's response_schema uses an OpenAPI subset: it rejects
    additionalProperties, so strip that key recursively (required/enum/items
    all pass through fine)."""
    if isinstance(schema, dict):
        return {k: gemini_schema(v) for k, v in schema.items()
                if k != "additionalProperties"}
    if isinstance(schema, list):
        return [gemini_schema(v) for v in schema]
    return schema


class GeminiProvider:
    """Gemini via the google-genai SDK (free-tier friendly).

    Same contract as AnthropicProvider: 4 images + prompt in, structured
    JSON out, no tools of any kind. Sleeps between calls to respect the
    free tier's requests-per-minute cap and retries once on 429.
    """

    # thinking tokens count toward max_output_tokens on Gemini 3.x, so the
    # budget must be well above what the JSON answer alone needs, since a 4096
    # cap produced a truncated (unparseable) response in the pilot
    def __init__(self, model_id: str, max_tokens: int = 8192, pause_s: float = 6.5):
        from google import genai
        from google.genai import types

        self.model_id = model_id
        self.max_tokens = max_tokens
        self.pause_s = pause_s
        # hard timeout (ms): without it a dropped connection blocks forever
        self._client = genai.Client(
            http_options=types.HttpOptions(timeout=120_000))  # reads GEMINI_API_KEY

    def complete(self, prompt_text: str, image_paths: list, schema: dict) -> dict:
        import httpx
        from google.genai import errors, types

        parts = [types.Part.from_bytes(data=Path(p).read_bytes(),
                                       mime_type=media_type_for(p))
                 for p in image_paths]
        parts.append(types.Part.from_text(text=prompt_text))
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=gemini_schema(schema),
            max_output_tokens=self.max_tokens,
            # no tools passed -> the model cannot search or retrieve anything
        )
        t0 = time.monotonic()
        resp = None
        for attempt in range(4):
            time.sleep(self.pause_s)
            try:
                resp = self._client.models.generate_content(
                    model=self.model_id, contents=parts, config=config)
                break
            except errors.APIError as exc:
                # free tier: back off on rate limits (429) and temporary
                # overload (503); give up on anything else
                if getattr(exc, "code", None) in (429, 503) and attempt < 3:
                    time.sleep(45)
                    continue
                raise
            except httpx.HTTPError:
                # timeout / dropped connection: retry like a 503
                if attempt < 3:
                    time.sleep(45)
                    continue
                raise
        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = getattr(resp, "usage_metadata", None)
        out_tokens = getattr(usage, "candidates_token_count", None) or 0
        text = resp.text
        if not text:   # safety-blocked or empty candidate
            return {"raw": {"text": None, "blocked": True}, "parsed": None,
                    "latency_ms": latency_ms, "tokens": out_tokens,
                    "model_reported": getattr(resp, "model_version", self.model_id)}
        return {"raw": {"text": text,
                        "usage": {"output_tokens": out_tokens}},
                "parsed": json.loads(text), "latency_ms": latency_ms,
                "tokens": out_tokens,
                "model_reported": getattr(resp, "model_version", self.model_id)}


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
