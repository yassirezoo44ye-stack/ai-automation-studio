"""Trusted, repository-shipped skills. Skills never grant tool permissions."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[3] / ".agents" / "skills"
SKILL_IDS = (
    "flow-project-planning", "flow-app-building", "flow-automation-operations",
    "flow-leads-management", "flow-content-design", "flow-business-analysis",
    "flow-career-assistance", "flow-arabic-visual-learning", "flow-device-management",
)
DEFAULT_AGENT_SKILLS = {
    "architect": ("flow-project-planning",),
    "backend": ("flow-app-building",),
    "frontend": ("flow-app-building",),
    "qa": ("flow-app-building",),
    "design": ("flow-content-design",),
    "devops": ("flow-automation-operations",),
    "device_control_coordinator": ("flow-device-management",),
}


@dataclass(frozen=True)
class Skill:
    id: str
    title: str
    description: str
    instructions: str


def validate_skill_ids(values: list[str] | tuple[str, ...]) -> list[str]:
    if len(values) > 3:
        raise ValueError("Select at most 3 skills")
    if any(value not in SKILL_IDS for value in values):
        raise ValueError("Unknown skill ID")
    return list(dict.fromkeys(values))


@lru_cache(maxsize=9)
def load_skill(skill_id: str) -> Skill:
    validate_skill_ids([skill_id])  # allowlist BEFORE constructing a path
    root = SKILLS_ROOT.resolve()
    path = root / skill_id / "SKILL.md"
    if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("Invalid skill path")
    if path.stat().st_size > 24_000:
        raise ValueError("Skill exceeds size limit")
    text = path.read_text(encoding="utf-8")
    # Parse only a leading frontmatter block. A '---' inside instructions
    # must not be interpreted as metadata.
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Invalid skill frontmatter")
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("Unterminated skill frontmatter") from exc
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if ": " not in line:
            raise ValueError("Invalid skill metadata")
        key, value = line.split(": ", 1)
        if not key or key in metadata:
            raise ValueError("Invalid skill metadata")
        metadata[key] = value
    if metadata.get("name") != skill_id or not metadata.get("description"):
        raise ValueError("Invalid skill metadata")
    body = "\n".join(lines[end + 1:]).strip()
    title = next((line[2:].strip() for line in body.splitlines()
                  if line.startswith("# ") and line[2:].strip()), None)
    if not title:
        raise ValueError("Skill title missing")
    return Skill(skill_id, title, metadata["description"], body)


def skill_catalog() -> list[dict[str, str]]:
    return [{"id": s.id, "title": s.title, "description": s.description}
            for s in (load_skill(key) for key in SKILL_IDS)]


def compose_skill_system(system: str | None, skill_ids: list[str] | tuple[str, ...]) -> str | None:
    ids = validate_skill_ids(skill_ids)
    if not ids:
        return system
    sections = [load_skill(key) for key in ids]
    guard = (
        "Flow skill instructions follow. They supplement the agent role and do not "
        "grant tools, permissions, access to other tenants, or approval for external actions. "
        "Server-enforced permissions and higher-priority platform rules always apply. "
        "Never claim an action succeeded without tool evidence."
    )
    return (system or "") + "\n\n" + guard + "".join(
        f"\n\n<flow-skill id=\"{s.id}\">\n{s.instructions}\n</flow-skill>" for s in sections
    )
