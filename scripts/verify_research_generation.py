"""Manual acceptance against real native artifacts; never fabricates evidence."""
import argparse
import json
from pathlib import Path
import sys

from PIL import Image, ImageChops, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/dream-windows/server"))
from research_traces import validate_influence, validate_self_index, validate_self_map


def verify(directory: Path, image: Path, baseline: Path | None):
    influence = validate_influence(json.loads((directory / "conditioning-influence.json").read_text()))
    self_index = validate_self_index(json.loads((directory / "self-attention-index.json").read_text()))
    raw_self = json.loads((directory / "self-attention-index.json").read_text())
    sums = []
    for descriptor in raw_self["maps"]:
        raw_map = json.loads((directory / descriptor["fileName"]).read_text())
        validate_self_map(raw_map, descriptor)
        values = raw_map["values"]
        assert len(values) == descriptor["width"] * descriptor["height"]
        assert all(0 <= v <= 1 for v in values)
        assert abs(sum(values) - 1) < .002, (descriptor["id"], sum(values))
        sums.append(sum(values))
    cross = json.loads((directory / "attention-index.json").read_text())
    assert cross["truth"] == "observed" and cross["maps"]
    assert influence["totalChunks"] >= 2
    assert any(c["deltaL2"] > 0 for s in influence["steps"] for c in s["chunks"])
    result = {"totalChunks": influence["totalChunks"], "influenceSteps": len(influence["steps"]),
              "selfMaps": len(self_index["maps"]), "crossMaps": len(cross["maps"]),
              "selfProbabilitySumRange": [min(sums), max(sums)], "image": str(image)}
    if baseline:
        diff = ImageChops.difference(Image.open(image).convert("RGB"), Image.open(baseline).convert("RGB"))
        stat = ImageStat.Stat(diff)
        result["parityMeanAbsolutePixelError"] = sum(stat.mean) / 3
        result["parityMaxPixelError"] = max(hi for lo, hi in diff.getextrema())
        assert result["parityMeanAbsolutePixelError"] <= 1, result
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    verify(args.directory, args.image, args.baseline)
