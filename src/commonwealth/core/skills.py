"""Reading the skills a profile has to be able to serve.

`design/skills.md` § 1 puts a machine-readable requirement in every skill:
`metadata.commonwealth.required_capabilities`. Decision 0002 says profiles
are generated from that so the two never drift, and they are not — the
profiles are still the hand-written dict in `toolreg.PROFILES`, and the
2026-09-01 amendment on 0002 records why.

What this module does is the half that is buildable with one skill: read
what the skills declare, and warn at startup when the registry cannot
answer a declared capability (design/hub-catalog.md § 2). A skill that
lists a capability nothing serves is a walk that dead-ends at step two,
so the server log names it before the first query.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SkillRequirements:
    name: str
    path: Path
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...]
    description: str = ""
    compatibility: str = ""
    body: str = ""
    accepts_question: bool = False


def _split_skill(text: str) -> tuple[dict, str]:
    """Split only at delimiter lines; keep later Markdown rules in the walk."""
    lines = text.splitlines(keepends=True)
    if lines and lines[0].rstrip("\r\n") == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.rstrip("\r\n") == "---":
                return yaml.safe_load("".join(lines[1:i])) or {}, "".join(lines[i + 1:]).strip()
    return {}, text.strip()


def load_skills(skills_dir: Path) -> list[SkillRequirements]:
    """Every `<skills_dir>/*/SKILL.md`, in directory-name order.

    A missing directory returns nothing and starts the server anyway. A
    checkout with no skills was the normal state until the first one was
    written, and a fork may remove the directory; refusing to start for a
    file the project never had would be the worse failure.
    """
    if not skills_dir.is_dir():
        return []
    out = []
    for path in sorted(skills_dir.glob("*/SKILL.md")):
        fm, body = _split_skill(path.read_text(encoding="utf-8"))
        cw = (fm.get("metadata") or {}).get("commonwealth") or {}
        out.append(SkillRequirements(
            name=fm.get("name") or path.parent.name,
            path=path,
            description=(fm.get("description") or "").strip(),
            compatibility=(fm.get("compatibility") or "").strip(),
            body=body,
            accepts_question=cw.get("prompt_input") == "question",
            required_capabilities=tuple(cw.get("required_capabilities") or ()),
            optional_capabilities=tuple(cw.get("optional_capabilities") or ()),
        ))
    return out


def unroutable_capabilities(
        skills: list[SkillRequirements],
        servable: set[str]) -> dict[str, list[str]]:
    """Required capabilities no active source can answer, by skill name.

    Only the required ones. An optional capability is the skill saying it
    improves the walk where it exists, which is a coverage statement rather
    than a prerequisite.
    """
    out = {}
    for skill in skills:
        missing = [c for c in skill.required_capabilities
                   if c not in servable]
        if missing:
            out[skill.name] = missing
    return out
