"""Offline checks for final documentation and its audit command."""

from pathlib import Path

from scripts.documentation_audit import (
    REQUIRED_DOCUMENTS,
    audit,
    find_unclosed_mermaid,
    main,
)


ROOT = Path(__file__).resolve().parents[1]


def test_required_documents_exist() -> None:
    for relative_path in REQUIRED_DOCUMENTS:
        assert (ROOT / relative_path).is_file(), relative_path


def test_readme_contains_submission_essentials() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "https://github.com/ssqq0330/minimal-agent-runtime" in readme
    assert "Agent Runtime Loop" in readme
    assert "Memory 在每次" in readme
    assert "python -m pytest -q" in readme
    assert "python -m scripts.documentation_audit" in readme
    assert "docs/RECORDING_SCRIPT.md" in readme
    assert "LLM_API_KEY=your_api_key" in readme


def test_prompt_record_has_all_stages_and_metadata() -> None:
    text = (ROOT / "docs" / "AI_PROMPTS.md").read_text(encoding="utf-8")
    for stage in range(1, 12):
        assert "## Stage {:02d}".format(stage) in text
    for marker in ("目标：", "Prompt：", "生成内容：", "人工检查结果："):
        assert text.count(marker) >= 11


def test_problem_record_uses_uniform_format() -> None:
    text = (ROOT / "docs" / "PROBLEM_SOLVING.md").read_text(encoding="utf-8")
    for marker in ("现象：", "原因：", "解决过程：", "最终方案：", "验证方式："):
        assert text.count(marker) >= 15


def test_mermaid_checker_accepts_closed_and_rejects_unclosed_fence() -> None:
    assert not find_unclosed_mermaid("```mermaid\nflowchart LR\nA-->B\n```\n")
    assert find_unclosed_mermaid("```mermaid\nflowchart LR\nA-->B\n")


def test_documentation_audit_passes(capsys) -> None:
    assert audit() == []
    assert main() == 0
    assert capsys.readouterr().out.strip() == "Documentation audit: PASS"
