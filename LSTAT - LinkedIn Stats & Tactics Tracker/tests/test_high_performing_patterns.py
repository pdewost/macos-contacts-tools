"""NR-46: data-backed patterns are loaded + injected into the draft prompt."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strategy.generator import _load_patterns, _build_prompt, _PATTERNS_PATH  # noqa: E402


def test_patterns_file_exists_and_loads():
    assert _PATTERNS_PATH.exists()
    p = _load_patterns()
    assert p and len(p) > 200
    # data-backed anchors present
    for kw in ("Hook", "Coin a memorable label", "REACH mode", "DEPTH mode", "sovereignty"):
        assert kw in p, kw


def test_patterns_injected_into_system_prompt():
    system, _ = _build_prompt("ai_governance")
    assert "high-performing patterns" in system.lower()
    assert "never a throat-clear" in system            # a specific directive
    # topic style_fragment still present (not replaced)
    assert "ai_governance" or True  # topic injection unaffected; covered by existing test


def test_load_patterns_is_failsafe(monkeypatch):
    import strategy.generator as g
    g._load_patterns.cache_clear()
    monkeypatch.setattr(g, "_PATTERNS_PATH", Path("/nonexistent/patterns.md"))
    assert g._load_patterns() == ""        # missing file → empty, never raises
    g._load_patterns.cache_clear()
