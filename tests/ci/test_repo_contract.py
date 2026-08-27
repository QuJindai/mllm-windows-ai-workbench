from pathlib import Path
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]

def test_required_files_exist():
    required = [
        "Start_M_LLM_Workbench.ps1",
        "engine/Core.psm1",
        "gui/Workbench.Wpf.ps1",
        "gui/Workbench.xaml",
        "config/task-policy.json",
        "config/defaults.json",
        "M_LLM_UNIVERSAL_INSTALLER.cmd",
        "installer/Start-UniversalInstaller.ps1",
        "installer/InstallerPaths.psm1",
    ]
    missing = [x for x in required if not (ROOT / x).is_file()]
    assert not missing, missing

def test_json_configs_parse():
    for path in (ROOT / "config").glob("*.json"):
        json.loads(path.read_text(encoding="utf-8-sig"))

def test_xaml_is_well_formed_xml():
    ET.parse(ROOT / "gui" / "Workbench.xaml")


def test_direct_windows_ps51_entrypoints_are_ascii_only():
    # Windows PowerShell 5.1 reads UTF-8 files without a BOM using the active
    # Windows ANSI code page. GitHub archives do not add a BOM, so any script
    # invoked directly from the raw snapshot can be mis-tokenized on a
    # non-English Windows host even when it parses on an English CI runner.
    direct_entrypoints = [
        "Bootstrap_SafeCore.ps1",
        "M_LLM_PHYSICAL_PREFLIGHT.ps1",
        "M_LLM_GUI_PREFLIGHT.ps1",
        "Start_M_LLM_Workbench.ps1",
        "M_LLM_UNIVERSAL_INSTALLER.cmd",
        "installer/Start-UniversalInstaller.ps1",
    ]
    offenders = []
    for relative in direct_entrypoints:
        path = ROOT / relative
        raw = path.read_bytes()
        if any(byte > 0x7F for byte in raw):
            offenders.append(relative)
    assert not offenders, (
        "Direct Windows PowerShell 5.1 entrypoints must be ASCII-only because "
        "raw GitHub archives are UTF-8 without BOM: " + ", ".join(offenders)
    )
