"""Bounded, fail-closed readers for the opt-in native research sidecars."""
from __future__ import annotations

import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any

from errors import DreamApiError


SELF_MARKER = {
    "contractVersion": "h7-self-attention-v1", "kind": "self-attention",
    "truth": "observed", "source": "debug-unet",
}
INFLUENCE_MARKER = {
    "contractVersion": "h6-conditioning-v1", "kind": "conditioning-influence",
    "truth": "observed", "source": "debug-unet",
}
INDEX_BYTES = 8 * 1024 * 1024
MAP_BYTES = 1024 * 1024
# 5 * 3 * 128 * 128 native floats plus nlohmann's per-value indentation.
INFLUENCE_BYTES = 12 * 1024 * 1024
TRACE_BYTES = 4 * 1024 * 1024
MAX_STEPS = 5
MAX_STEP = 49
MAX_DIMENSION = 128
MAX_MAPS = 512
MAX_ANCHORS = 9


class InvalidArtifact(ValueError):
    pass


def require(condition: bool) -> None:
    if not condition:
        raise InvalidArtifact("Invalid research artifact")


def integer(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def number(value: Any, minimum: float, maximum: float = math.inf) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum
    except OverflowError:
        return False


def safe_id(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) is not None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def _reject_constant(_value):
    raise InvalidArtifact("Nonfinite JSON constant")


def read_bounded_json(path: Path, maximum_bytes: int) -> dict[str, Any]:
    """Bound both allocation and parsing; reject ambiguous JSON and non-files."""
    try:
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum_bytes)
            data = stream.read(maximum_bytes + 1)
        require(len(data) <= maximum_bytes)
        result = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        require(isinstance(result, dict))
        return result
    except (OSError, ValueError, RecursionError) as exc:
        raise InvalidArtifact("Unreadable research artifact") from exc


def marker(document, expected):
    require(isinstance(document, dict) and document.get('source') in ('debug-unet', 'diffusers-unet'))
    require(all(document.get(key) == value for key, value in expected.items() if key != 'source'))


def dimensions(document):
    width, height = document.get("width"), document.get("height")
    require(integer(width, 1, MAX_DIMENSION) and integer(height, 1, MAX_DIMENSION))
    return width, height


def metrics(document, names, minimum=0, maximum=math.inf):
    require(all(number(document.get(name), minimum, maximum) for name in names))
    return {name: float(document[name]) for name in names}


def validate_research_provenance(raw):
    """Optional for historic artifacts; new visual observations are explicit."""
    from identity_models import MODEL_SPECS, is_visual_model_id
    if 'provenance' not in raw:
        return {}
    value = raw['provenance']
    require(raw.get('source') == 'diffusers-unet' and isinstance(value, dict))
    model = value.get('modelId')
    require(isinstance(model, str) and model in MODEL_SPECS)
    require(value.get('referenceKind') == ('visual' if is_visual_model_id(model) else 'faceid'))
    require(value.get('intervention') == 'ip-adapter-scale-zero'
            and value.get('attentionSemantics') == 'conditional-text'
            and value.get('referenceImageTokenAttribution') is False)
    start, end = value.get('referenceStart'), value.get('referenceEnd')
    require(number(start, 0, 1) and number(end, 0, 1) and start < end)
    require(is_visual_model_id(model) or (start, end) == (0., 1.))
    return {'provenance': {key: value[key] for key in (
        'modelId', 'referenceKind', 'intervention', 'attentionSemantics',
        'referenceImageTokenAttribution', 'referenceStart', 'referenceEnd')}}


def validate_influence(raw):
    marker(raw, INFLUENCE_MARKER)
    identity = raw['source'] == 'diffusers-unet'
    provenance = validate_research_provenance(raw)
    visual = provenance.get('provenance', {}).get('referenceKind') == 'visual'
    method = 'visual-reference-ablation-guided' if visual else 'identity-ablation-guided' if identity else 'chunk-vs-full-guided'
    require(raw.get("method") == method and type(raw.get("chunkSize")) is int and raw["chunkSize"] == 77)
    total, captured = raw.get("totalChunks"), raw.get("capturedChunks")
    require(integer(total, 1, 2**31 - 1) and integer(captured, 1, min(3, total)))
    raw_steps = raw.get("steps")
    require(not identity or total == captured == 1)
    require(isinstance(raw_steps, list) and 1 <= len(raw_steps) <= (12 if identity else MAX_STEPS))
    steps, step_ids = [], set()
    chunk_layout = None
    grid = None
    for sample in raw_steps:
        require(isinstance(sample, dict))
        step = sample.get("step")
        require(integer(step, 0, MAX_STEP) and step not in step_ids)
        step_ids.add(step)
        width, height = dimensions(sample)
        require(grid is None or grid == (width, height))
        grid = (width, height)
        cfg_metrics = {**metrics(sample, ("cfgDeltaL2",)), **metrics(sample, ("cfgCosine",), -1, 1)}
        raw_chunks = sample.get("chunks")
        require(isinstance(raw_chunks, list) and len(raw_chunks) == captured)
        chunks, chunk_ids = [], set()
        for item in raw_chunks:
            require(isinstance(item, dict))
            chunk, start, end = item.get("chunk"), item.get("tokenStart"), item.get("tokenEnd")
            require(integer(chunk, 0, total - 1) and chunk not in chunk_ids)
            require(integer(start, 0, total * 77 - 1) and start == chunk * 77)
            require(integer(end, start + 1, start + 77))
            # Only the last embedding chunk can end before its 77-token boundary.
            require(chunk == total - 1 or end == start + 77)
            chunk_ids.add(chunk)
            chunk_metrics = {**metrics(item, ("meanAbs", "l2", "deltaL2")), **metrics(item, ("cosineFull",), -1, 1)}
            spatial = item.get("spatialDelta")
            require(isinstance(spatial, list) and len(spatial) == width * height and all(number(value, 0) for value in spatial))
            require(identity or total != 1 or (chunk_metrics["deltaL2"] == 0 and all(value == 0 for value in spatial)))
            chunks.append({"chunk": chunk, "tokenStart": start, "tokenEnd": end,
                           **chunk_metrics, "spatialDelta": [float(value) for value in spatial]})
        chunks.sort(key=lambda item: item["chunk"])
        layout = [(item["chunk"], item["tokenStart"], item["tokenEnd"]) for item in chunks]
        require(chunk_layout is None or chunk_layout == layout)
        chunk_layout = layout
        steps.append({"step": step, "width": width, "height": height, **cfg_metrics, "chunks": chunks})
    return {**INFLUENCE_MARKER, **provenance, "source": raw['source'], "method": method, "chunkSize": 77,
            "totalChunks": total, "capturedChunks": captured, "steps": sorted(steps, key=lambda item: item["step"])}


def self_descriptor(raw):
    require(isinstance(raw, dict) and safe_id(raw.get("id")) and safe_id(raw.get("layerId")))
    width, height = dimensions(raw)
    step, query, x, y = (raw.get(key) for key in ("step", "queryIndex", "queryX", "queryY"))
    require(integer(step, 0, MAX_STEP) and integer(query, 0, width * height - 1))
    require(integer(x, 0, width - 1) and integer(y, 0, height - 1) and query == y * width + x)
    return {"id": raw["id"], "step": step, "layerId": raw["layerId"], "queryIndex": query,
            "queryX": x, "queryY": y, "width": width, "height": height,
            **metrics(raw, ("entropy", "peak", "coverage"), 0, 1)}


def validate_self_index(raw):
    marker(raw, SELF_MARKER)
    provenance = validate_research_provenance(raw)
    identity = raw['source'] == 'diffusers-unet'
    raw_layers, raw_maps = raw.get("layers"), raw.get("maps")
    require(isinstance(raw_layers, list) and 1 <= len(raw_layers) <= (32 if identity else 3))
    require(isinstance(raw_maps, list) and 1 <= len(raw_maps) <= (4000 if identity else MAX_MAPS))
    layers, layer_ids, stages = [], set(), set()
    for layer in raw_layers:
        require(isinstance(layer, dict))
        layer_id, stage, label = layer.get("id"), layer.get("stage"), layer.get("label")
        require(safe_id(layer_id) and layer_id not in layer_ids)
        require(isinstance(stage, str) and stage in {"down", "mid", "up"} and (identity or stage not in stages))
        require(isinstance(label, str) and 1 <= len(label) <= 128)
        layer_ids.add(layer_id)
        stages.add(stage)
        layers.append({"id": layer_id, "stage": stage, "label": label})
    maps, ids, files, selections, steps = [], set(), set(), set(), set()
    anchors, grids = {}, {}
    for item in raw_maps:
        descriptor = self_descriptor(item)
        layer_id, map_id, step = descriptor["layerId"], descriptor["id"], descriptor["step"]
        file_name = item.get("fileName")
        require(layer_id in layer_ids and map_id not in ids)
        require(isinstance(file_name, str) and len(file_name) <= 160
                and re.fullmatch(r"self-attention-[A-Za-z0-9._-]+\.json", file_name) is not None)
        require(file_name.casefold() not in files)
        selection = (step, layer_id, descriptor["queryIndex"])
        require(selection not in selections)
        steps.add(step)
        require(len(steps) <= (12 if identity else MAX_STEPS))
        anchors.setdefault(layer_id, set()).add(descriptor["queryIndex"])
        require(len(anchors[layer_id]) <= MAX_ANCHORS)
        grid = (descriptor["width"], descriptor["height"])
        require(layer_id not in grids or grids[layer_id] == grid)
        grids[layer_id] = grid
        ids.add(map_id)
        files.add(file_name.casefold())
        selections.add(selection)
        maps.append({**descriptor, "fileName": file_name})
    return {**SELF_MARKER, **provenance, "source": raw['source'], "layers": layers,
            "maps": sorted(maps, key=lambda item: (item["step"], item["layerId"], item["queryIndex"]))}


def validate_self_map(raw, descriptor):
    marker(raw, SELF_MARKER)
    provenance = validate_research_provenance(raw)
    identity = self_descriptor(raw)
    require(identity == {key: value for key, value in descriptor.items() if key != "fileName"})
    values = raw.get("values")
    require(isinstance(values, list) and len(values) == identity["width"] * identity["height"])
    require(all(number(value, 0, 1) for value in values))
    return {**SELF_MARKER, **provenance, "source": raw['source'], **identity, "values": [float(value) for value in values]}


class ResearchTraceStore:
    def __init__(self, dream_root: Path):
        self.dream_root = dream_root

    @staticmethod
    def _safe_path(path: Path, parent: Path) -> bool:
        try:
            # Keep artifacts in this exact run, including through symlinks/junctions.
            return path.resolve().parent == parent.resolve() and path.resolve().name == path.name
        except (OSError, ValueError, RuntimeError):
            return False

    def _run(self, run_id: str):
        trace_root = self.dream_root / "traces"
        if not self._safe_path(trace_root, self.dream_root) or not safe_id(run_id):
            return run_id, None, None
        if run_id == "latest":
            try:
                candidates = sorted(trace_root.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
            except OSError:
                return run_id, None, None
        else:
            candidates = [trace_root / f"{run_id}.json"]
        for path in candidates:
            if not safe_id(path.stem) or not self._safe_path(path, trace_root):
                continue
            try:
                raw = read_bounded_json(path, TRACE_BYTES)
                require(safe_id(raw.get("runId")) and number(raw.get("totalTimeMs"), 0) and isinstance(raw.get("nodes"), list))
            except InvalidArtifact:
                continue
            run_dir = trace_root / path.stem
            return path.stem, run_dir if self._safe_path(run_dir, trace_root) else None, raw
        return run_id, None, None

    def _document(self, run_id, file_name, limit, validator):
        resolved_id, run_dir, trace = self._run(run_id)
        if run_dir is None:
            return resolved_id, None
        path = run_dir / file_name
        if not self._safe_path(path, run_dir):
            return resolved_id, None
        try:
            document = validator(read_bounded_json(path, limit))
            evidence = trace.get("evidence")
            backend = evidence.get("backend") if isinstance(evidence, dict) else None
            # Legacy native roots may omit backend or name their execution
            # device. Diffusers observations require an explicit matching root;
            # an explicit Diffusers root must not adopt native sidecars either.
            if document["source"] == "diffusers-unet" or backend == "diffusers-unet":
                require(trace["runId"] == resolved_id and backend == document["source"] == "diffusers-unet")
            provenance = document.get('provenance')
            from identity_models import is_visual_model_id
            if isinstance(evidence, dict) and (evidence.get('referenceKind') == 'visual'
                    or is_visual_model_id(evidence.get('modelId'))):
                require(provenance is not None and provenance['referenceKind'] == 'visual')
            if provenance is not None:
                require(trace.get('provenance') == provenance and isinstance(evidence, dict)
                        and evidence.get('modelId') == provenance['modelId']
                        and evidence.get('referenceKind') == provenance['referenceKind'])
            return resolved_id, document
        except InvalidArtifact:
            return resolved_id, None

    @staticmethod
    def _unavailable(run_id, name):
        return {"available": False, "runId": run_id, "truth": "unavailable",
                "message": f"No validated native {name} trace is available"}

    def influence(self, run_id):
        resolved_id, document = self._document(run_id, "conditioning-influence.json", INFLUENCE_BYTES, validate_influence)
        return ({"available": True, "runId": resolved_id, **document} if document is not None
                else self._unavailable(resolved_id, "H6 conditioning influence"))

    def _self_index(self, run_id):
        return self._document(run_id, "self-attention-index.json", INDEX_BYTES, validate_self_index)

    def self_attention_index(self, run_id):
        resolved_id, document = self._self_index(run_id)
        if document is None:
            return self._unavailable(resolved_id, "H7 self-attention")
        public_maps = [{**{key: value for key, value in item.items() if key != "fileName"},
                        "mapUrl": f"/api/traces/{resolved_id}/self-attention/maps/{item['id']}"}
                       for item in document["maps"]]
        return {"available": True, "runId": resolved_id, **document, "maps": public_maps}

    def self_attention_map(self, run_id, map_id):
        resolved_id, document = self._self_index(run_id)
        missing = DreamApiError("SELF_ATTENTION_MAP_NOT_FOUND", "H7 self-attention map is not available", status_code=404)
        if document is None or not safe_id(map_id):
            raise missing
        descriptor = next((item for item in document["maps"] if item["id"] == map_id), None)
        if descriptor is None:
            raise missing
        run_dir = self.dream_root / "traces" / resolved_id
        path = run_dir / descriptor["fileName"]
        if not self._safe_path(run_dir, self.dream_root / "traces") or not self._safe_path(path, run_dir) or not path.is_file():
            raise missing
        try:
            result = validate_self_map(read_bounded_json(path, MAP_BYTES), descriptor)
            require(result['source'] == document['source'])
            require(result.get('provenance') == document.get('provenance'))
        except InvalidArtifact as exc:
            raise DreamApiError("SELF_ATTENTION_MAP_INVALID", "H7 self-attention map is invalid", status_code=422) from exc
        return {"available": True, "runId": resolved_id, **result}
