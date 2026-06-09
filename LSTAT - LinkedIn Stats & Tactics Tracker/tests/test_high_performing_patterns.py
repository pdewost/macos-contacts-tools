"""NR-46/47: patterns load + compose UNDER the authoritative 07 voice; no voice
duplication in the patterns file."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import strategy.generator as g  # noqa: E402
from strategy.generator import _load_patterns, _build_prompt, _PATTERNS_PATH  # noqa: E402


def test_patterns_file_exists_and_loads():
    assert _PATTERNS_PATH.exists()
    p = _load_patterns()
    assert p and len(p) > 200
    for kw in ("Hook", "Coin a memorable label", "REACH mode", "DEPTH mode", "sovereignty"):
        assert kw in p, kw


def test_patterns_file_has_no_voice_duplication():
    """NR-47(a): voice content must live ONLY in 07_Style_Profile, not here."""
    p = _PATTERNS_PATH.read_text(encoding="utf-8")
    assert "VOICE IS THE FLOOR" in p                 # explicit deferral present
    assert "Voice cues" not in p                     # the duplicated section is gone
    assert "anaphora" not in p and "aphorism" not in p
    assert "De mémoire vive" not in p
    # number-hook refined to respect the voice interdit
    assert "chiffre seul en titre" in p and "bare number" in p


def test_voice_composed_above_patterns(monkeypatch, tmp_path):
    """NR-47(b): voice spec injected, ABOVE the patterns, marked authoritative."""
    vf = tmp_path / "voice.md"; vf.write_text("VOICE-RHYTHM-SPEC", encoding="utf-8")
    g._load_voice_prompt.cache_clear()
    monkeypatch.setattr(g, "_VOICE_PROMPT_PATH", vf)
    system, _ = _build_prompt("ai_governance")
    assert "VOICE-RHYTHM-SPEC" in system
    assert "authoritative" in system.lower()
    # ordering: voice spec appears BEFORE the patterns block
    assert system.index("VOICE-RHYTHM-SPEC") < system.lower().index("high-performing patterns")
    assert "within the voice specification above" in system
    g._load_voice_prompt.cache_clear()


def test_voice_load_is_failsafe(monkeypatch):
    g._load_voice_prompt.cache_clear()
    monkeypatch.setattr(g, "_VOICE_PROMPT_PATH", Path("/nonexistent/voice.md"))
    assert g._load_voice_prompt() == ""
    # prompt still builds without the voice file
    system, _ = _build_prompt("ai_governance")
    assert "high-performing patterns" in system.lower()
    g._load_voice_prompt.cache_clear()
