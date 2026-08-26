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
    ]
    missing = [x for x in required if not (ROOT / x).is_file()]
    assert not missing, missing

def test_json_configs_parse():
    for path in (ROOT / "config").glob("*.json"):
        json.loads(path.read_text(encoding="utf-8-sig"))

def test_xaml_is_well_formed_xml():
    ET.parse(ROOT / "gui" / "Workbench.xaml")
