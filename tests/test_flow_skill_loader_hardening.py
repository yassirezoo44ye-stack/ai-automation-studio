"""Regression checks for untrusted or malformed repository skill documents."""
import pytest

from app.core.ai import skills


@pytest.mark.parametrize("document", [
    "name: flow-project-planning\ndescription: missing delimiters\n# Title",
    "---\nname: flow-project-planning\ndescription: incomplete\n# Title",
    "---\nname: flow-project-planning\ndescription: valid\ninvalidline\n---\n# Title",
    "---\nname: flow-project-planning\nname: duplicate\ndescription: valid\n---\n# Title",
    "---\nname: flow-project-planning\ndescription: valid\n---\nno heading",
])
def test_invalid_skill_documents_fail_closed(tmp_path, monkeypatch, document):
    root = tmp_path
    directory = root / "flow-project-planning"
    directory.mkdir()
    (directory / "SKILL.md").write_text(document, encoding="utf-8")
    monkeypatch.setattr(skills, "SKILLS_ROOT", root)
    skills.load_skill.cache_clear()
    try:
        with pytest.raises(ValueError):
            skills.load_skill("flow-project-planning")
    finally:
        skills.load_skill.cache_clear()


def test_skill_body_can_contain_horizontal_rule(tmp_path, monkeypatch):
    directory = tmp_path / "flow-project-planning"
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        "---\nname: flow-project-planning\ndescription: valid\n---\n"
        "# Plan\nFirst section\n---\nSecond section\n", encoding="utf-8"
    )
    monkeypatch.setattr(skills, "SKILLS_ROOT", tmp_path)
    skills.load_skill.cache_clear()
    try:
        skill = skills.load_skill("flow-project-planning")
        assert skill.title == "Plan"
        assert "Second section" in skill.instructions
    finally:
        skills.load_skill.cache_clear()
