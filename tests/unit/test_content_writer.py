"""Markdown composition for BL-4 .md sourozenec — pure logic tests."""
from __future__ import annotations

from types import SimpleNamespace

from plaudsync.content_writer import compose


def _meta() -> SimpleNamespace:
    return SimpleNamespace(
        plaud_id="abc123",
        title="ALZA: Kickoff",
        created_at="2026-04-29T09:15:00+00:00",
    )


def _detail(language: str = "cs", speakers: int = 3) -> SimpleNamespace:
    return SimpleNamespace(language=language, speakers_count=speakers)


def test_compose_full_md_has_frontmatter_and_three_sections() -> None:
    md = compose(
        meta=_meta(),
        detail=_detail(),
        sections={"summary": "S text", "outline": "O text", "transcript": "T text"},
        project="ALZA",
        classification_source="name",
    )
    assert md.startswith("---\n")
    # Frontmatter fields
    assert "plaud_id: abc123" in md
    assert "title: ALZA: Kickoff" in md
    assert "created_at: 2026-04-29T09:15:00+00:00" in md
    assert "language: cs" in md
    assert "speakers: 3" in md
    assert "project: ALZA" in md
    assert "classification_source: name" in md
    # Section ordering: Summary → Outline → Transcript
    assert md.index("## Summary") < md.index("## Outline") < md.index("## Transcript")
    assert "S text" in md and "O text" in md and "T text" in md


def test_compose_omits_empty_sections() -> None:
    md = compose(
        meta=_meta(), detail=_detail(),
        sections={"summary": "S", "outline": "", "transcript": "T"},
        project="ALZA", classification_source="name",
    )
    assert "## Outline" not in md
    assert "## Summary" in md
    assert "## Transcript" in md


def test_compose_omits_whitespace_only_sections() -> None:
    md = compose(
        meta=_meta(), detail=_detail(),
        sections={"summary": "   \n\n  ", "outline": "O", "transcript": "T"},
        project="ALZA", classification_source="folder",
    )
    assert "## Summary" not in md
    assert "## Outline" in md


def test_compose_excludes_business_fields_from_frontmatter() -> None:
    """Spec §7 — never include headline / recommend_questions / industry_category."""
    md = compose(
        meta=_meta(), detail=_detail(),
        sections={"summary": "S", "outline": "", "transcript": ""},
        project="ALZA", classification_source="name",
    )
    assert "headline" not in md.lower()
    assert "recommend_questions" not in md
    assert "industry_category" not in md
    assert "aiContentHeader" not in md


def test_compose_classification_source_folder() -> None:
    md = compose(
        meta=_meta(), detail=_detail(),
        sections={"summary": "S", "outline": "", "transcript": ""},
        project="ALZA", classification_source="folder",
    )
    assert "classification_source: folder" in md


def test_compose_ends_with_single_newline() -> None:
    """Avoid double-newline tail (some markdown renderers add a blank section)."""
    md = compose(
        meta=_meta(), detail=_detail(),
        sections={"summary": "S", "outline": "", "transcript": ""},
        project="ALZA", classification_source="name",
    )
    assert md.endswith("\n")
    assert not md.endswith("\n\n")
