#!/usr/bin/env python3
"""Install repository-shipped Flow skills and future-session instructions."""
import argparse
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
START = '<!-- flow-skills:start -->'
END = '<!-- flow-skills:end -->'


def install(skill_root: Path, instructions: Path) -> None:
    source = REPO / '.agents' / 'skills'
    sources = sorted(source.glob('flow-*/SKILL.md'))
    if len(sources) != 9:
        raise ValueError('Expected nine repository skills')
    # Validate all destinations before writing; never replace unrelated content.
    for src in sources:
        destination = skill_root / src.parent.name
        if destination.is_symlink():
            raise ValueError(f'Refusing symlink destination: {destination}')
        target = destination / 'SKILL.md'
        if target.is_symlink() or (target.exists() and target.read_bytes() != src.read_bytes()):
            raise ValueError(f'Existing skill differs; review before updating: {target}')
    if instructions.is_symlink():
        raise ValueError('Refusing symlink instructions')
    existing = instructions.read_text() if instructions.exists() else ''
    if (START in existing) != (END in existing):
        raise ValueError('Incomplete Flow instructions block; review manually')
    block = f'''{START}
## Flow skills for future sessions

Repository-shipped Flow skills are installed in `{skill_root}`.
At the start of a relevant task, read the matching SKILL.md before applying it:

'''
    block += '\n'.join(f'- `{src.parent.name}`: `{skill_root / src.parent.name / "SKILL.md"}`' for src in sources)
    block += f'''

Apply only skills relevant to the user's request. Preserve existing work.
A skill never grants tool access, cross-tenant access, or permission for external
actions. Follow the user's existing scoped authorization. These local skills do
not install Render/Vercel plugins or credentials. Repository instructions apply
when working in Flow; do not assume any environment or app is production-ready.
{END}'''
    if START in existing:
        before, tail = existing.split(START, 1)
        _, after = tail.split(END, 1)
        updated = before + block + after
    else:
        updated = existing.rstrip() + '\n\n' + block + '\n'
    for src in sources:
        destination = skill_root / src.parent.name
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, destination / 'SKILL.md')
    instructions.parent.mkdir(parents=True, exist_ok=True)
    instructions.write_text(updated)
    print(f'Installed {len(sources)} skills in {skill_root}; instructions: {instructions}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root', type=Path, default=Path.home() / '.agents' / 'skills')
    parser.add_argument('--instructions', type=Path, default=Path.home() / '.codex' / 'AGENTS.md')
    args = parser.parse_args()
    install(args.skill_root.expanduser().absolute(), args.instructions.expanduser().absolute())
