"""Check the label and launcher resources actually present in the C206 APK."""
from pathlib import Path
import re
import struct
import sys
import zipfile


def verify(apk_path, badging, manifest):
    name = "绘梦PLUS"
    labels = re.findall(r"^application-label(?:-[^:]+)?:'([^']*)'", badging, re.M)
    assert labels and set(labels) == {name}, set(labels)
    nodes = re.split(r"(?m)^[ \t]*E: ", manifest)
    application, = [node for node in nodes if node.startswith("application ")]
    activity, = [node for node in nodes if node.startswith("activity ") and '"io.github.xororz.localdream.MainActivity"' in node]

    def resource(node, attribute):
        return re.search(rf":{attribute}\(0x[0-9a-f]+\)=(@0x[0-9a-f]+)", node).group(1)

    assert resource(application, "label") == resource(activity, "label")
    icon_ids = {resource(node, key) for node in (application, activity) for key in ("icon", "roundIcon")}
    assert len(icon_ids) == 1, icon_ids
    icons = re.findall(r"^application-icon-\d+:'([^']+)'", badging, re.M)
    icon, = set(icons)
    assert re.fullmatch(r"res/drawable-nodpi(?:-v\d+)?/hq_huimeng_plus\.png", icon), icon
    launcher, = [line for line in badging.splitlines() if line.startswith("launchable-activity:")]
    assert f"label='{name}'" in launcher and f"icon='{icon}'" in launcher, launcher
    with zipfile.ZipFile(apk_path) as apk:
        png = apk.read(icon)
        assert png.startswith(b"\x89PNG\r\n\x1a\n") and struct.unpack(">II", png[16:24]) == (512, 512)
        page = apk.read("assets/s24u_microscope/index.html").decode("utf-8")
        assert f"<title>{name} · 扩散显微镜</title>" in page and f">{name} · C206 · H6R5R1<" in page
    print(f"{name}: {len(labels)} locale labels; application and launcher use {icon}")


if __name__ == "__main__":
    apk, badging, manifest = map(Path, sys.argv[1:])
    verify(apk, badging.read_text(encoding="utf-8-sig"), manifest.read_text(encoding="utf-8-sig"))
