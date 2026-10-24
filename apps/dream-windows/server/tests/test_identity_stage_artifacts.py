"""Only synthetic pixels in temporary directories; no private images or GPU."""
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image

import history_transactions


def artifacts():
    assert importlib.util.find_spec("identity_stage_artifacts"), "Stage artifact storage is missing"
    return importlib.import_module("identity_stage_artifacts")


def item(tmp_path, index=0):
    return dict(dreamRoot=str(tmp_path), jobId="identity-" + f"{index:024x}", width=256, height=256)


def stage_path(value, kind="anchor"):
    return Path(value["dreamRoot"]) / "data/identity/stages" / value["jobId"] / f"{kind}.png"


def test_stage_publication_is_immutable_full_size_and_cleanup_is_job_scoped(tmp_path):
    module = artifacts()
    value, sibling = item(tmp_path), item(tmp_path, 1)
    image = Image.new("RGB", (256, 256), "navy")
    for kind in ("anchor", "harmonize", "detail"):
        assert module.save_visual_stage(image, value, kind) == f"/api/identity/jobs/{value['jobId']}/stages/{kind}"
    module.save_visual_stage(image, sibling, "anchor")
    path = stage_path(value)
    saved = path.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        module.save_visual_stage(Image.new("RGB", (256, 256), "red"), value, "anchor")
    assert path.read_bytes() == saved
    extra = path.parent / "unrelated.txt"
    extra.write_text("preserve")
    original = tmp_path / "data/identity/originals" / f"{value['jobId']}.png"
    original.parent.mkdir()
    image.save(original)
    module.cleanup_visual_stages(value)
    assert not list(path.parent.glob("*.png"))
    assert stage_path(sibling).read_bytes() == saved
    assert original.read_bytes() == saved and extra.read_text() == "preserve"
    module.cleanup_visual_stages(value)


@pytest.mark.parametrize("change,kind", [({"jobId": "../private"}, "anchor"), ({}, "../private"),
                                      ({}, "original"), ({"width": 512}, "anchor")])
def test_invalid_stage_identifiers_and_size_never_publish(tmp_path, change, kind):
    with pytest.raises((ValueError, TypeError)):
        artifacts().save_visual_stage(Image.new("RGB", (256, 256)), {**item(tmp_path), **change}, kind)
    assert not list(tmp_path.rglob("*.png"))


def test_racing_stage_publication_does_not_overwrite_winner(tmp_path, monkeypatch):
    module = artifacts()
    value = item(tmp_path)
    path = stage_path(value)
    original_link = os.link
    def publish_first(source, target, *args, **kwargs):
        Path(target).write_bytes(b"other publisher")
        return original_link(source, target, *args, **kwargs)
    monkeypatch.setattr(os, "link", publish_first)
    with pytest.raises(FileExistsError):
        module.save_visual_stage(Image.new("RGB", (256, 256)), value, "anchor")
    assert path.read_bytes() == b"other publisher"
    assert list(path.parent.iterdir()) == [path]


def test_interrupted_png_encoding_leaves_no_published_or_temporary_stage(tmp_path, monkeypatch):
    module = artifacts()
    value = item(tmp_path)
    def interrupted(image, stream, **kwargs):
        stream.write(b"incomplete PNG")
        raise OSError("controlled interrupted write")
    monkeypatch.setattr(Image.Image, "save", interrupted)
    with pytest.raises(OSError, match="interrupted write"):
        module.save_visual_stage(Image.new("RGB", (256, 256)), value, "harmonize")
    assert list(stage_path(value).parent.iterdir()) == []


@pytest.mark.parametrize("kind", ["anchor", "harmonize", "detail"])
@pytest.mark.parametrize("boundary", ["encoding", "publication", "published"])
def test_cleanup_removes_orphan_temps_after_publisher_process_exits(tmp_path, kind, boundary):
    module = artifacts()
    value, sibling = item(tmp_path), item(tmp_path, 1)
    script = '''import os, sys
from PIL import Image
from identity_stage_artifacts import save_visual_stage
root, job_id, kind, boundary = sys.argv[1:]
publish = os.link
def stop_encoding(self, stream, **kwargs):
    stream.write(b"partial PNG")
    stream.flush()
    os._exit(17)
def stop_publication(*args, **kwargs):
    if boundary == "published":
        publish(*args, **kwargs)
    os._exit(17)
if boundary == "encoding":
    Image.Image.save = stop_encoding
else:
    os.link = stop_publication
save_visual_stage(Image.new("RGB", (256, 256)),
    dict(dreamRoot=root, jobId=job_id, width=256, height=256), kind)
'''
    # run() waits for child exit before cleanup; no live publisher is raced.
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), value["jobId"], kind, boundary],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
    assert result.returncode == 17, result.stderr.decode(errors="replace")
    folder = stage_path(value).parent
    temps = list(folder.glob(f".{kind}-*.tmp"))
    assert len(temps) == 1 and temps[0].stat().st_size > 0
    protected = [folder / ".other-abc.tmp", folder / ".detail-abc.tmp.bak",
                 stage_path(sibling).parent / f".{kind}-sibling.tmp"]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preserve")
    module.cleanup_visual_stages(value)
    assert not temps[0].exists()
    assert not stage_path(value, kind).exists()
    assert all(path.read_bytes() == b"preserve" for path in protected)


def test_temp_cleanup_rejects_symlinks_and_preserves_matching_directories(tmp_path):
    module = artifacts()
    value = item(tmp_path)
    folder = stage_path(value).parent
    folder.mkdir(parents=True)
    protected = tmp_path / "protected.tmp"
    protected.write_bytes(b"protected")
    link = folder / ".detail-redirect.tmp"
    try:
        link.symlink_to(protected)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")
    with pytest.raises(ValueError):
        module.cleanup_visual_stages(value)
    assert protected.read_bytes() == b"protected" and link.is_symlink()
    link.unlink()
    matching_directory = folder / ".anchor-directory.tmp"
    matching_directory.mkdir()
    (matching_directory / ".detail-nested.tmp").write_bytes(b"preserve nested")
    module.cleanup_visual_stages(value)
    assert (matching_directory / ".detail-nested.tmp").read_bytes() == b"preserve nested"


def test_stage_validation_rejects_oversized_file_before_decoding(tmp_path, monkeypatch):
    module = artifacts()
    value = item(tmp_path)
    module.save_visual_stage(Image.new("RGB", (256, 256)), value, "anchor")
    monkeypatch.setattr(module, "MAX_STAGE_BYTES", 1)
    with pytest.raises(ValueError):
        module.validate_visual_stage(value, "anchor")


def test_redirected_stage_directory_cannot_be_written_or_cleaned(tmp_path):
    module = artifacts()
    value = item(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "anchor.png"
    protected.write_bytes(b"protected")
    path = stage_path(value)
    path.parent.parent.mkdir(parents=True)
    try:
        path.parent.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")
    with pytest.raises(ValueError):
        module.save_visual_stage(Image.new("RGB", (256, 256)), value, "anchor")
    with pytest.raises(ValueError):
        module.cleanup_visual_stages(value)
    assert protected.read_bytes() == b"protected"
    output = tmp_path / "outputs" / f"{value['jobId']}.png"
    output.parent.mkdir()
    output.write_bytes(b"preserve output")
    from errors import DreamApiError
    with pytest.raises(DreamApiError) as error:
        history_transactions.delete_history_files(tmp_path, value["jobId"], [output])
    assert error.value.code == "HISTORY_DELETE_PATH_INVALID"
    assert protected.read_bytes() == b"protected" and output.read_bytes() == b"preserve output"


@pytest.mark.parametrize("fail_commit", [False, True])
def test_history_transaction_moves_all_stages_and_rolls_back_together(tmp_path, monkeypatch, fail_commit):
    module = artifacts()
    value, sibling = item(tmp_path), item(tmp_path, 1)
    image = Image.new("RGB", (256, 256))
    for kind in ("anchor", "harmonize", "detail"):
        module.save_visual_stage(image, value, kind)
    module.save_visual_stage(image, sibling, "anchor")
    output = tmp_path / "outputs/2026-10-24" / f"{value['jobId']}.png"
    output.parent.mkdir(parents=True)
    image.save(output)
    metadata = output.with_suffix(".json")
    metadata.write_text("{}")
    original = tmp_path / "data/identity/originals" / output.name
    original.parent.mkdir()
    image.save(original)
    all_paths = [output, metadata, original, *[stage_path(value, kind) for kind in ("anchor", "harmonize", "detail")]]
    saved = {path: path.read_bytes() for path in all_paths}
    write_record = history_transactions._write_record
    def write(root, path, record):
        if path.name == "committed.json" and fail_commit:
            raise PermissionError("controlled commit failure")
        return write_record(root, path, record)
    monkeypatch.setattr(history_transactions, "_write_record", write)
    if fail_commit:
        with pytest.raises(Exception, match="历史删除失败"):
            history_transactions.delete_history_files(tmp_path, value["jobId"], [output, metadata, original])
        assert {path: path.read_bytes() for path in all_paths} == saved
    else:
        history_transactions.delete_history_files(tmp_path, value["jobId"], [output, metadata, original])
        assert not any(path.exists() for path in all_paths)
        assert value["jobId"] in history_transactions.committed_history_deletions(tmp_path)
    assert stage_path(sibling).exists()
