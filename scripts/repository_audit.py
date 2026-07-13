"""Audit repository hygiene and prohibited dependency rules."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parents[1]
BANNED = ("langchain", "langgraph", "openhands", "openclaw", "openai-agents")
REQUIRED = (
    "README.md",
    "docs/AI_PROMPTS.md",
    "docs/PROBLEM_SOLVING.md",
    "docs/WEB_UI_CHECKLIST.md",
)
REAL_KEY_PATTERN = re.compile(
    r"(?:\bsk-[A-Za-z0-9]{32,}\b|\b(?:api[_-]?key|token|secret)\s*[:=]\s*"
    r"[\"'][A-Za-z0-9._~+/=-]{32,}[\"'])",
    re.IGNORECASE,
)


def git_lines(*arguments: str) -> List[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def is_ignored(path: str) -> bool:
    return subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=ROOT,
        check=False,
    ).returncode == 0


def tracked_text_files(names: Iterable[str]):
    for name in names:
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            yield name, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def audit() -> List[str]:
    failures: List[str] = []
    ignore_samples = {
        ".env": ".env",
        ".venv": ".venv/audit-placeholder",
        "data/*.db": "data/audit.db",
        "data/*.db-wal": "data/audit.db-wal",
        "data/*.db-shm": "data/audit.db-shm",
    }
    for rule, sample in ignore_samples.items():
        if not is_ignored(sample):
            failures.append("gitignore rule missing: {}".format(rule))

    tracked = git_lines("ls-files")
    for name in tracked:
        path = Path(name)
        if path.name == ".env":
            failures.append("tracked environment file: {}".format(name))
        if path.suffix in {".db", ".sqlite", ".sqlite3"} or name.endswith(
            (".db-wal", ".db-shm")
        ):
            failures.append("tracked database file: {}".format(name))

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for package in BANNED:
        if package in requirements:
            failures.append("prohibited dependency: requirements.txt ({})".format(package))

    import_pattern = re.compile(
        r"^\s*(?:from|import)\s+(langchain|langgraph|openhands|openclaw|openai_agents)\b",
        re.MULTILINE,
    )
    for name, text in tracked_text_files(tracked):
        if Path(name).suffix == ".py" and import_pattern.search(text):
            failures.append("prohibited framework import: {}".format(name))
        if REAL_KEY_PATTERN.search(text):
            failures.append("possible real credential: {}".format(name))
        if name.startswith("web/") and Path(name).suffix in {".html", ".css", ".js"}:
            if re.search(r"(?:src|href)=[\"']https?://|@import\s+url\(https?://", text):
                failures.append("external CDN reference: {}".format(name))

    for required in REQUIRED:
        if not (ROOT / required).is_file():
            failures.append("required file missing: {}".format(required))
    return failures


def main() -> int:
    try:
        failures = audit()
    except (OSError, subprocess.SubprocessError) as error:
        print("Repository audit: FAIL")
        print("- audit could not run: {}".format(error.__class__.__name__))
        return 1
    if failures:
        print("Repository audit: FAIL")
        for failure in failures:
            print("- {}".format(failure))
        return 1
    print("Repository audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
