"""Molly Skills: reusable, on-demand instructions for specific kinds of
task (deploying a particular stack, following a house style, a recurring
maintenance procedure, etc), the same idea as the SKILL.md convention
Claude itself uses.

A skill is a directory under settings.skills_dir:

    data/skills/<skill-name>/
        SKILL.md          # required: frontmatter + instructions
        (anything else)   # optional supporting files (scripts, templates)
                           # the agent can read_file()/view once it has
                           # loaded this skill - not indexed here.

SKILL.md is YAML-frontmatter-shaped but parsed with a tiny hand-rolled
parser rather than pulling in a real YAML library: the only fields Molly
needs are flat strings (`name`, `description`), and every dependency added
here is one more thing to compile with Nuitka (see backend/NUITKA_BUILD.md)
and one more thing that can go stale in a chain of provider/model configs.

Why the filesystem instead of the DB: skills are meant to be inspectable
and editable the same way any other file on the server is - via `molly` tools,
scp, git, or a text editor - not hidden behind an opaque DB row. This also
means an operator can add a skill without touching the API at all: just
create the directory and SKILL.md.
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.config import settings

SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
MAX_INDEX_DESCRIPTION_CHARS = 200


class InvalidSkillNameError(ValueError):
    pass


class SkillNotFoundError(LookupError):
    pass


@dataclass
class SkillInfo:
    name: str
    description: str


@dataclass
class Skill(SkillInfo):
    body: str  # the SKILL.md content after the frontmatter block
    files: List[str]  # other files in this skill's directory, if any


def _validate_skill_name(name: str) -> str:
    """Skill names become directory names on disk, so this is the one
    thing that has to be strict - lowercase kebab-case only, no path
    separators, no leading dot, bounded length. Raises rather than
    silently sanitizing, so a bad name is caught at creation time, not
    discovered later as a confusing filesystem mismatch."""
    if not SKILL_NAME_RE.match(name or ""):
        raise InvalidSkillNameError(
            f"Invalid skill name '{name}'. Use lowercase letters, digits, and hyphens only "
            "(e.g. 'deploy-rails-app'), 1-64 characters, not starting or ending with a hyphen."
        )
    return name


def _skill_dir(name: str) -> Path:
    _validate_skill_name(name)
    return settings.skills_path / name


def _parse_skill_md(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter dict, body). Frontmatter is a
    `---`-delimited block of flat `key: value` lines - no nesting, no
    lists, no multiline values. Missing/malformed frontmatter just yields
    an empty dict rather than raising, so a hand-edited file with a typo
    degrades to "no description" instead of breaking skill discovery
    entirely."""
    frontmatter: dict = {}
    body = text

    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm_block = text[3:end].strip("\n")
            body = text[end + 4:].lstrip("\n")
            for line in fm_block.splitlines():
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                frontmatter[key.strip().lower()] = value.strip().strip('"').strip("'")

    return frontmatter, body


def _render_skill_md(name: str, description: str, body: str) -> str:
    # description is a single frontmatter line, so any newline in it would
    # corrupt the block - collapse it defensively rather than rejecting the
    # write outright.
    safe_description = " ".join((description or "").split())
    return f"---\nname: {name}\ndescription: {safe_description}\n---\n\n{body.strip()}\n"


def list_skills() -> List[SkillInfo]:
    """The lightweight index used both by GET /skills and by the system
    prompt (see app/agent/context.py) - name + description only, so
    skimming the list of what's available stays cheap even with many
    skills. Skips any directory whose SKILL.md is missing or unreadable
    rather than failing the whole listing over one bad entry."""
    skills_dir = settings.skills_path
    if not skills_dir.exists():
        return []

    results: List[SkillInfo] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            frontmatter, _ = _parse_skill_md(skill_md.read_text(encoding="utf-8"))
        except OSError:
            continue
        description = frontmatter.get("description", "")
        if len(description) > MAX_INDEX_DESCRIPTION_CHARS:
            description = description[:MAX_INDEX_DESCRIPTION_CHARS].rstrip() + "…"
        results.append(SkillInfo(name=frontmatter.get("name") or entry.name, description=description))
    return results


def get_skill(name: str) -> Skill:
    """Full skill content, for the read_skill tool and GET /skills/{name}."""
    skill_dir = _skill_dir(name)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise SkillNotFoundError(f"No skill named '{name}'")

    frontmatter, body = _parse_skill_md(skill_md.read_text(encoding="utf-8"))
    other_files = sorted(
        str(p.relative_to(skill_dir)) for p in skill_dir.rglob("*") if p.is_file() and p.name != "SKILL.md"
    )
    return Skill(
        name=frontmatter.get("name") or name,
        description=frontmatter.get("description", ""),
        body=body,
        files=other_files,
    )


def write_skill(name: str, description: str, body: str) -> Skill:
    """Create or overwrite a skill's SKILL.md. Doesn't touch any other
    files already in that skill's directory (supporting scripts/
    templates an operator or the agent added directly) - only SKILL.md
    itself is managed through this API."""
    if not description.strip():
        raise ValueError("A skill needs a description - it's how Molly decides when to load it.")
    skill_dir = _skill_dir(name)
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_render_skill_md(name, description, body), encoding="utf-8")
    return get_skill(name)


def delete_skill(name: str) -> None:
    """Remove a skill's entire directory, including any supporting files -
    unlike write_skill, this isn't scoped to just SKILL.md, since a
    deleted skill leaving orphaned files behind would just clutter
    settings.skills_dir with no way to discover they're there."""
    import shutil

    skill_dir = _skill_dir(name)
    if not skill_dir.exists():
        raise SkillNotFoundError(f"No skill named '{name}'")
    shutil.rmtree(skill_dir)


def render_skills_index() -> str:
    """The block appended to the system prompt (see
    app/agent/context.py's ContextManager.initialize). Empty string when
    there are no skills, so a fresh install's prompt doesn't carry a
    dangling "Available skills:" header with nothing under it."""
    skills = list_skills()
    if not skills:
        return ""

    lines = [
        "\nAvailable skills (call read_skill(name) to load one's full instructions "
        "before starting a matching task - the description below is only enough "
        "to judge relevance, not to act on):",
    ]
    for skill in skills:
        lines.append(f"- {skill.name}: {skill.description}")
    return "\n".join(lines)
