"""Exercise release notes/tagging against a real Git remote protecting main."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / 'source'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'config', 'user.name', 'Release Test')
    git(repo, 'config', 'user.email', 'release-test@example.invalid')
    (repo / 'scripts').mkdir()
    shutil.copyfile(ROOT / 'scripts/ci_release.py', repo / 'scripts/ci_release.py')
    (repo / 'CHANGELOG.md').write_text('# Changelog\n')
    (repo / 'main.py').write_text('print("previous")\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'feat: previous release')
    git(repo, 'tag', 'v1.0.34')
    (repo / 'main.py').write_text('print("verified deployment")\n')
    git(repo, 'commit', '-qam', 'fix: deliver verified app')
    return repo


def notes(repo):
    result = subprocess.run([sys.executable, 'scripts/ci_release.py', '--notes-only'], cwd=repo, capture_output=True, text=True, check=True)
    version = next(line.split('=', 1)[1] for line in result.stdout.splitlines() if line.startswith('NEW_VERSION='))
    return version, (repo / '.release-notes.md').read_text()


def tag_step(repo, version, sha):
    workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())
    step = next(s for s in workflow['jobs']['release']['steps'] if s.get('name') == 'Tag verified deployment')
    shell = step['run'].replace('${{ steps.release.outputs.version }}', version)
    return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', shell], cwd=repo,
                          env=dict(os.environ, GITHUB_SHA=sha), capture_output=True, text=True)


def test_notes_and_retries_preserve_the_verified_commit_and_tracked_changelog(repository):
    repo = repository
    head = git(repo, 'rev-parse', 'HEAD')
    changelog = (repo / 'CHANGELOG.md').read_text()
    version, first_notes = notes(repo)
    assert version == 'v1.0.35'
    assert 'deliver verified app' in first_notes
    git(repo, 'tag', version, head)
    assert notes(repo) == (version, first_notes)
    assert git(repo, 'rev-parse', 'HEAD') == head
    assert (repo / 'CHANGELOG.md').read_text() == changelog
    assert not git(repo, 'diff', '--name-only')


def test_workflow_tags_exact_deployment_without_pushing_to_protected_main(repository, tmp_path):
    repo = repository
    remote = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'push', '-q', 'origin', 'main')
    hook = remote / 'hooks/pre-receive'
    hook.write_text('#!/bin/sh\nwhile read old new ref; do\n  if [ "$ref" = refs/heads/main ]; then\n    echo "main requires a pull request" >&2\n    exit 1\n  fi\ndone\n')
    hook.chmod(0o700)
    deployed = git(repo, 'rev-parse', 'HEAD')
    version, _ = notes(repo)
    result = tag_step(repo, version, deployed)
    assert result.returncode == 0, result.stderr
    assert git(remote, 'rev-parse', 'refs/heads/main') == deployed
    assert git(remote, 'rev-parse', f'refs/tags/{version}') == deployed
    assert tag_step(repo, version, deployed).returncode == 0
    assert not git(repo, 'diff', '--name-only')


def test_existing_tag_for_another_commit_is_never_overwritten(repository):
    repo = repository
    previous = git(repo, 'rev-parse', 'HEAD^')
    git(repo, 'tag', 'v1.0.35', previous)
    result = tag_step(repo, 'v1.0.35', git(repo, 'rev-parse', 'HEAD'))
    assert result.returncode != 0
    assert 'refusing to overwrite' in result.stdout
    assert git(repo, 'rev-parse', 'v1.0.35') == previous
