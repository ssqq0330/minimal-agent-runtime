"""Audit final documentation completeness, safety, and basic structure."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DOCUMENTS = (
    "README.md",
    "docs/SYSTEM_DESIGN.md",
    "docs/MEMORY_DESIGN.md",
    "docs/API_REFERENCE.md",
    "docs/AI_PROMPTS.md",
    "docs/PROBLEM_SOLVING.md",
    "docs/TEST_PLAN.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/WEB_UI_CHECKLIST.md",
    "docs/RECORDING_SCRIPT.md",
    "docs/SUBMISSION_CHECKLIST.md",
    "docs/FINAL_PROJECT_REPORT.md",
)
README_MARKERS = (
    "https://github.com/ssqq0330/minimal-agent-runtime",
    "python3.11 -m venv .venv",
    "python -m uvicorn app.main:app --reload",
    "python -m pytest -q",
    "python -m scripts.documentation_audit",
    "Agent Runtime Loop",
    "Memory 在每次",
    "docs/MEMORY_DESIGN.md",
    "LLM_API_KEY=your_api_key",
    "OpenAI-Compatible Chat Completions API",
    "docs/RECORDING_SCRIPT.md",
)
PROBLEM_MARKERS = (
    "pydantic-core",
    "pytest 临时目录权限",
    "Python 3.9 到 3.11",
    "Windows 到 Mac",
    "GitHub HTTPS",
    "LLM JSON 输出解析",
    "Session 隔离",
    "Context 过长",
    "同一 Session 并发 Chat",
    "前端 XSS",
    "Inspector 请求竞态",
)
PERSONAL_PATH_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("macOS personal path", re.compile(r"/Users/[^/\s`]+/")),
    ("Linux personal path", re.compile(r"/home/[^/\s`]+/")),
    ("Windows absolute path", re.compile(r"(?i)\b[A-Z]:\\(?:Users|Documents|Desktop|Claude)[^\n`]*")),
)
KEY_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "Bearer credential",
        re.compile(r"(?i)\bBearer\s+(?!\[REDACTED\]|<[^>]+>)[A-Za-z0-9._~+/=-]{16,}"),
    ),
)
PLACEHOLDER_VALUES = {
    "",
    "your_api_key",
    "your-api-key",
    "example",
    "example-key",
    "[redacted]",
    "<api_key>",
}


def markdown_files() -> Iterable[Path]:
    yield ROOT / "README.md"
    yield from sorted((ROOT / "docs").glob("*.md"))


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def find_unclosed_mermaid(text: str) -> bool:
    """Return True when a Mermaid code fence has no later closing fence."""
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip().lower().startswith("```mermaid"):
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                index += 1
            if index >= len(lines):
                return True
        index += 1
    return False


def _check_api_key_assignments(name: str, text: str, failures: List[str]) -> None:
    for match in re.finditer(
        r"(?im)^[ \t]*LLM_API_KEY[ \t]*=[ \t]*([^\s#]*)",
        text,
    ):
        value = match.group(1).strip().strip("\"'")
        normalized = value.lower()
        is_named_placeholder = normalized.startswith(
            ("your", "example", "test", "fake", "demo")
        )
        if normalized not in PLACEHOLDER_VALUES and not is_named_placeholder:
            failures.append("possible real LLM_API_KEY value: {}".format(name))
            return


def audit() -> List[str]:
    failures: List[str] = []

    for relative_path in REQUIRED_DOCUMENTS:
        if not (ROOT / relative_path).is_file():
            failures.append("required document missing: {}".format(relative_path))

    if failures:
        return failures

    readme = read_text("README.md")
    for marker in README_MARKERS:
        if marker not in readme:
            failures.append("README marker missing: {}".format(marker))

    prompts = read_text("docs/AI_PROMPTS.md")
    for stage in range(1, 12):
        marker = "## Stage {:02d}".format(stage)
        if marker not in prompts:
            failures.append("AI prompt stage missing: {}".format(marker))
    for marker in ("目标：", "Prompt：", "生成内容：", "人工检查结果："):
        if prompts.count(marker) < 11:
            failures.append("AI prompt metadata incomplete: {}".format(marker))

    problems = read_text("docs/PROBLEM_SOLVING.md")
    for marker in PROBLEM_MARKERS:
        if marker not in problems:
            failures.append("problem record missing: {}".format(marker))
    for marker in ("现象：", "原因：", "解决过程：", "最终方案：", "验证方式："):
        if problems.count(marker) < 15:
            failures.append("problem record format incomplete: {}".format(marker))

    api_reference = read_text("docs/API_REFERENCE.md")
    for route in (
        "/api/health",
        "/api/sessions",
        "/api/sessions/{session_id}/messages",
        "/api/sessions/{session_id}/todos",
        "/api/chat",
        "/api/traces",
        "/api/traces/{run_id}",
    ):
        if route not in api_reference:
            failures.append("API reference route missing: {}".format(route))

    for path in markdown_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            failures.append("document unreadable: {}".format(path.relative_to(ROOT)))
            continue
        name = str(path.relative_to(ROOT))
        for label, pattern in PERSONAL_PATH_PATTERNS:
            if pattern.search(text):
                failures.append("{} in {}".format(label, name))
        for label, pattern in KEY_PATTERNS:
            if pattern.search(text):
                failures.append("possible {} in {}".format(label, name))
        _check_api_key_assignments(name, text, failures)
        if find_unclosed_mermaid(text):
            failures.append("unclosed Mermaid fence: {}".format(name))

    return failures


def main() -> int:
    try:
        failures = audit()
    except OSError as error:
        print("Documentation audit: FAIL")
        print("- audit could not run: {}".format(error.__class__.__name__))
        return 1
    if failures:
        print("Documentation audit: FAIL")
        for failure in failures:
            print("- {}".format(failure))
        return 1
    print("Documentation audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
