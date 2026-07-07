"""The prompts for both tasks, with their JSON answer schemas.

Prompt text and schema are versioned together — changing either means a new
version string, so every stored answer is traceable to the exact question
it was given. The city task asks for one best guess with coordinates (the
scoring works on distance, so coordinates matter more than the name). The
neighbourhood task tells the model the city and asks for the district.
Both require a `cues` list typed to Lynch's elements plus text_signage —
readable text is a separate category because reading a sign is OCR, not
recognising a place. Schemas follow the structured-output rules: every
object closed and every property required.
"""
from __future__ import annotations

CUE_TYPES = ["landmark", "district", "node", "edge", "path",
             "text_signage", "vegetation", "architecture", "other"]

_CUES_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "cue_type": {
                "type": "string",
                "enum": CUE_TYPES,
                "description": ("What kind of visual evidence this is. Use "
                                "text_signage ONLY for readable text (shop signs, "
                                "street plates, licence plates)."),
            },
            "description": {"type": "string",
                            "description": "The specific visual evidence, one sentence."},
        },
        "required": ["cue_type", "description"],
        "additionalProperties": False,
    },
}

CITY_PROMPT_V1 = {
    "prompt_version": "city_v1",
    "task": "city",
    "text": (
        "You are shown 4 photographs taken from the same street-level location, "
        "facing north (0°), east (90°), south (180°) and west (270°), "
        "in that order.\n\n"
        "Identify where in the world this location is. Give your single best guess "
        "even if you are uncertain — do not refuse and do not answer 'unknown'. "
        "Estimate the coordinates of the camera position as precisely as you can.\n\n"
        "Report the visual cues that informed your guess, each classified by type, "
        "and explain your reasoning briefly. Report confidence as a number between "
        "0 and 1."
    ),
    "output_schema": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "Best-guess city name, in English"},
            "country": {"type": "string", "description": "Best-guess country name, in English"},
            "latitude": {"type": "number", "description": "Estimated latitude in decimal degrees (-90 to 90)"},
            "longitude": {"type": "number", "description": "Estimated longitude in decimal degrees (-180 to 180)"},
            "confidence": {"type": "number", "description": "Confidence in the city guess, 0 to 1"},
            "cues": _CUES_SCHEMA,
            "reasoning": {"type": "string", "description": "Brief reasoning for the guess"},
        },
        "required": ["city", "country", "latitude", "longitude",
                     "confidence", "cues", "reasoning"],
        "additionalProperties": False,
    },
}

NEIGHBOURHOOD_PROMPT_V1 = {
    "prompt_version": "nbhd_v1",
    "task": "neighbourhood",
    # {city_name} and {country} are filled per point at request time; the
    # template itself (with placeholders) is what is stored/versioned.
    "text": (
        "You are shown 4 photographs taken from the same street-level location in "
        "{city_name}, {country}, facing north (0°), east (90°), south (180°) "
        "and west (270°), in that order.\n\n"
        "Identify which neighbourhood or district of {city_name} this location is in. "
        "Give your single best guess even if you are uncertain — do not refuse. Use "
        "the name of an administrative district or commonly recognised neighbourhood.\n\n"
        "Report the visual cues that informed your guess, each classified by type, "
        "and explain your reasoning briefly. Report confidence as a number between "
        "0 and 1."
    ),
    "output_schema": {
        "type": "object",
        "properties": {
            "neighbourhood": {"type": "string",
                              "description": "Best-guess neighbourhood/district name"},
            "confidence": {"type": "number", "description": "Confidence in the guess, 0 to 1"},
            "cues": _CUES_SCHEMA,
            "reasoning": {"type": "string", "description": "Brief reasoning for the guess"},
        },
        "required": ["neighbourhood", "confidence", "cues", "reasoning"],
        "additionalProperties": False,
    },
}

PROMPTS = [CITY_PROMPT_V1, NEIGHBOURHOOD_PROMPT_V1]
