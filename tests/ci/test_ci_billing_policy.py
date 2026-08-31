from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DEFAULT_VALIDATION_WORKFLOW = WORKFLOWS / "ci.yml"

BANNED_ACTION_PROVIDERS = re.compile(r"(openai|codex|copilot|anthropic|claude)", re.I)
BANNED_STORAGE_ACTIONS = re.compile(r"actions/(upload-artifact|cache)@", re.I)
BANNED_RUNNER_LABELS = re.compile(r"(large|xlarge|larger)", re.I)


def yaml_directives(paths):
    for path in paths:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("uses:") or stripped.startswith("- uses:"):
                yield path, lineno, "uses", stripped
            elif stripped.startswith("runs-on:"):
                yield path, lineno, "runs-on", stripped


def all_workflows():
    return sorted(WORKFLOWS.glob("*.y*ml"))


def test_no_workflow_uses_metered_ai_actions():
    violations = [
        f"{path.name}:{lineno}: {text}"
        for path, lineno, kind, text in yaml_directives(all_workflows())
        if kind == "uses" and BANNED_ACTION_PROVIDERS.search(text)
    ]
    assert not violations, violations


def test_default_validation_workflow_does_not_upload_or_cache_artifacts():
    violations = [
        f"{path.name}:{lineno}: {text}"
        for path, lineno, kind, text in yaml_directives([DEFAULT_VALIDATION_WORKFLOW])
        if kind == "uses" and BANNED_STORAGE_ACTIONS.search(text)
    ]
    assert not violations, violations


def test_workflows_use_only_standard_runner_labels():
    violations = [
        f"{path.name}:{lineno}: {text}"
        for path, lineno, kind, text in yaml_directives(all_workflows())
        if kind == "runs-on" and BANNED_RUNNER_LABELS.search(text.split(":", 1)[1].strip())
    ]
    assert not violations, violations
