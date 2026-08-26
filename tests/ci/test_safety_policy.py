from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks"
POLICY = ROOT / "config" / "task-policy.json"
SYSTEM_MUTATION_PATTERNS = {
    "winget install": re.compile(r"\bwinget(?:\.exe)?\b.*\binstall\b|\$wg\.Source\s+install", re.I),
    "msiexec": re.compile(r"\bmsiexec(?:\.exe)?\b", re.I),
    "scheduled task": re.compile(r"\bschtasks(?:\.exe)?\b\s+/Create\b", re.I),
    "registry mutation": re.compile(r"\b(?:Set|New)-ItemProperty\b|\breg(?:\.exe)?\b\s+(?:add|delete)\b", re.I),
}
def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")
def test_safe_core_preset_has_no_system_installers():
    policy = json.loads(read(POLICY)); ids = policy["presets"]["Core"]; violations = []
    for task_id in ids:
        text = read(TASKS / f"{task_id}.task.ps1")
        for name, pattern in SYSTEM_MUTATION_PATTERNS.items():
            if pattern.search(text): violations.append(f"{task_id}: {name}")
    assert not violations, "Core must be portable-only; found: " + ", ".join(violations)
def test_task_files_do_not_import_core_module():
    offenders=[]; pat=re.compile(r"Import-Module\s+.*Core\.psm1",re.I)
    for path in sorted(TASKS.glob("*.task.ps1")):
        if pat.search(read(path)): offenders.append(path.name)
    assert not offenders, "Task scripts must run in the engine loader scope, not recursively import Core: " + ", ".join(offenders)
def test_wpf_fallback_is_independent_of_primary_doctor():
    text=read(ROOT / "Start_M_LLM_Workbench.ps1"); fallback=re.search(r"WPF_FALLBACK=CLI(?P<body>.*?)(?:exit\s+2)",text,flags=re.I|re.S)
    assert fallback, "WPF fallback block not found"
    assert "Invoke-MLLMEmergencyDoctor" in fallback.group("body"), "WPF fallback must call independent Invoke-MLLMEmergencyDoctor, not the same engine Doctor"
def test_safe_core_does_not_create_startup_tasks():
    core_ids=set(json.loads(read(POLICY))["presets"]["Core"])
    for task_id in core_ids: assert not re.search(r"schtasks(?:\.exe)?\b\s+/Create",read(TASKS / f"{task_id}.task.ps1"),re.I),task_id
def test_python_install_has_no_system_exe_installer_route():
    text=read(TASKS / "python.task.ps1"); assert "Python.Python.3.12" not in text; assert not re.search(r"python-3\.12\.10-amd64\.exe",text,re.I); assert "python-portable" in text
def test_llama_install_has_no_winget_route():
    text=read(TASKS / "llama-cpp.task.ps1"); assert not SYSTEM_MUTATION_PATTERNS["winget install"].search(text); assert "runtime\\llama.cpp" in text
def test_modelscope_install_is_isolated_below_data_root():
    text=read(TASKS / "modelscope.task.ps1"); assert "runtime\\modelscope\\site-packages" in text; assert "--target" in text; assert "pip uninstall" not in text.lower()
def test_full_setup_does_not_include_system_developer_tools():
    policy=json.loads(read(POLICY)); assert "git" not in policy["presets"]["Full Setup"]; assert "git-lfs" not in policy["presets"]["Full Setup"]
def test_qwen_download_uses_isolated_modelscope_target():
    text=read(TASKS / "qwen35-4b.task.ps1"); assert "runtime\\modelscope\\site-packages" in text
