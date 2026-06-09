"""Draft generator using the local_llm cascade.

Mock-friendly: pass a custom `cascade_call` callable for tests.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .topic_dict import TOPICS, get_topic as _get_topic_or_none

_PATTERNS_PATH = Path(__file__).with_name("high_performing_patterns.md")

# NR-47(b): the AUTHORITATIVE voice spec lives in 07_Style_Profile (single source of
# truth). Composed into the prompt at generation — never copied/merged here. Override
# the path via LSTAT_VOICE_PROMPT_PATH.
_VOICE_PROMPT_PATH = Path(os.environ.get(
    "LSTAT_VOICE_PROMPT_PATH",
    "/Users/pdewost/Documents/Personnel/Developpement/Project PAIA - Personal AI Assistant/"
    "07_Style_Profile/outputs/system_prompt_short.md",
))


@lru_cache(maxsize=1)
def _load_patterns() -> str:
    """NR-46: data-backed 'what works' patterns injected into the draft prompt.
    Fail-safe: returns '' if the file is missing so drafting never breaks."""
    try:
        return _PATTERNS_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


@lru_cache(maxsize=1)
def _load_voice_prompt() -> str:
    """NR-47(b): the authoritative VOICE spec from 07_Style_Profile (the floor).
    Composed ABOVE the performance patterns. Fail-safe: '' if missing."""
    try:
        return _VOICE_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _build_prompt(
    topic_key: str,
    *,
    source_url: str | None = None,
    top_reactor_headlines: list[str] | None = None,
    top_audience_segments: list[str] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt)."""
    topic = _get_topic_or_none(topic_key)
    if topic is None:
        raise ValueError(f"Unknown topic: {topic_key}")
    system = (
        "You are drafting a LinkedIn post in the voice of Philippe Dewost — "
        "a French tech executive with experience spanning banking infrastructure, "
        "BFM Business media, and venture capital. "
    )
    # NR-47(b): the authoritative VOICE spec (07_Style_Profile) is the FLOOR — composed
    # first and never violated. Performance patterns (below) apply within it.
    _voice = _load_voice_prompt()
    if _voice:
        system += "\n\nVOICE SPECIFICATION (authoritative — never violate):\n" + _voice + "\n\n"
    system += (
        "Style guidance for this topic: " + topic["style_fragment"] + " "
        "Length: 800-1200 characters. No hashtags. Use emoji sparingly (at most one). "
        "Return only the draft text — no preamble, no explanation."
    )
    # NR-46/47: performance patterns are SUBORDINATE to the voice specification above.
    _patterns = _load_patterns()
    if _patterns:
        system += ("\n\nApply these proven high-performing patterns, strictly within "
                   "the voice specification above:\n" + _patterns)
    user_parts = [f'Draft a LinkedIn post on the topic of "{topic_key}".']
    if source_url:
        user_parts.append(f"Anchor on this event: {source_url}")
    if top_reactor_headlines:
        joined = "; ".join(top_reactor_headlines[:5])
        user_parts.append(f"Recent top reactors include: {joined}")
    if top_audience_segments:
        joined = ", ".join(top_audience_segments[:3])
        user_parts.append(f"Top audience segments: {joined}")
    user = "\n\n".join(user_parts)
    return system, user


def generate_draft(
    topic_key: str,
    *,
    source_url: str | None = None,
    top_reactor_headlines: list[str] | None = None,
    top_audience_segments: list[str] | None = None,
    cascade_call: Callable[..., str] | None = None,
    model_name: str = "qwen3.5-opus-27b",
) -> dict:
    """Generate a single draft.

    If cascade_call is None, lazy-import local_llm.cascade.CascadeRouter().call.
    Returns {
        'draft_id': str,                # uuid4
        'generated_at': ISO,
        'prompt_topic': str,
        'source_event_url': str | None,
        'draft_text': str,
        'status': 'pending',
        'resonance_score': None,        # filled by resonance.score_topic if caller wants
        'model_used': str,
        'notes': None,
    }
    Raises ValueError if topic_key unknown.
    """
    if topic_key not in TOPICS:
        raise ValueError(f"Unknown topic: {topic_key}")

    system, user = _build_prompt(
        topic_key,
        source_url=source_url,
        top_reactor_headlines=top_reactor_headlines,
        top_audience_segments=top_audience_segments,
    )

    if cascade_call is None:
        # Lazy import -- avoids hard dependency in tests
        import sys
        skill_root = "/Users/pdewost/Documents/Personnel/Developpement/_skills/local_llm"
        if skill_root not in sys.path:
            sys.path.insert(0, skill_root)
        from scripts.cascade import CascadeRouter
        router = CascadeRouter()
        cascade_call = router.call

    draft_text = cascade_call(
        user,
        task="outreach",
        system=system,
        max_tokens=1500,
        temperature=0.7,
    )

    return {
        "draft_id": str(uuid.uuid4()),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "prompt_topic": topic_key,
        "source_event_url": source_url,
        "draft_text": draft_text.strip(),
        "status": "pending",
        "resonance_score": None,
        "model_used": model_name,
        "notes": None,
    }


# Public alias: spec calls for build_prompt (public); _build_prompt is internal
build_prompt = _build_prompt


def save_draft(conn, draft: dict) -> str:
    """INSERT a draft into linkedin_post_strategy_drafts. Returns draft_id."""
    conn.execute(
        """
        INSERT INTO linkedin_post_strategy_drafts
          (draft_id, generated_at, prompt_topic, source_event_url, draft_text,
           status, resonance_score, model_used, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft["draft_id"], draft["generated_at"], draft["prompt_topic"],
            draft.get("source_event_url"), draft["draft_text"], draft["status"],
            draft.get("resonance_score"), draft["model_used"], draft.get("notes"),
        ),
    )
    conn.commit()
    return draft["draft_id"]
