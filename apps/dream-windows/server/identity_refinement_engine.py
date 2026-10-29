"""Independent one-pass edits; plain restoration never loads a generation session."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from identity_events import emit_event
from identity_models import is_visual_model_id
from identity_quality import compare_images


class _EditSettings(BaseModel):
    # The service also sends version/request identifiers, which are not inference
    # options. Only these fields may override the validated generation request.
    model_config = ConfigDict(strict=True, allow_inf_nan=False)
    mode: Literal['restore', 'redraw', 'reference-anchor', 'edge-lighting']
    strength: float = Field(ge=.15, le=.65)
    prompt: str = Field(default='', max_length=2000)
    negativePrompt: str = Field(default='', max_length=2000)
    seed: int = Field(ge=0, le=2147483647)


def _publish_image(image, output):
    """Publish complete pixels without replacing another edit or a fixed .tmp."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w+b', prefix='.refine-', suffix='.tmp',
                                         dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            image.save(stream, format='PNG')
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory hard-link publication is atomic and fails on an existing
        # output (including one created concurrently). The parent publishes its
        # version only after this private pending file has been validated.
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def refine(config, request, *, restore_factory=None):
    started = perf_counter()
    phases = {}
    settings = _EditSettings.model_validate(request['editSettings'])
    visual = is_visual_model_id(request.get('modelId'))
    edge_lighting = settings.mode == 'edge-lighting'
    if not edge_lighting and (settings.mode == 'restore') == visual:
        raise ValueError('精修模式与人物模型不兼容')
    source, output = Path(request['sourcePath']), Path(request['outputPath'])
    if output.exists() or output.is_symlink():
        raise FileExistsError('精修输出已存在，未覆盖')
    if output.resolve() in (source.resolve(), Path(request['imagePath']).resolve()):
        raise ValueError('精修输出不能覆盖原图或参考照')

    point = perf_counter()
    with Image.open(source) as opened:
        if opened.size != (request['width'], request['height']):
            raise ValueError('精修源图尺寸与原任务不一致')
        baseline = opened.convert('RGB')
    phases['read'] = (perf_counter() - point) * 1000

    item = {**request, 'seed': settings.seed}
    if not edge_lighting:
        item.update(facePolish=True, faceRestoreStrength=settings.strength,
                    animeDenoiseStrength=settings.strength, visualPolishPasses=1)
    if visual and not edge_lighting:
        item.update(visualPolishMode=settings.mode, visualPolishPrompt=settings.prompt,
                    visualPolishNegativePrompt=settings.negativePrompt)
    elif item.get('animeProfileId') and not edge_lighting:
        # The session must initialize anime_projected even when the source was
        # generated with optional polishing disabled. Empty text keeps the scene
        # prompt needed by the existing anime polisher/identity request contract.
        item.update(prompt=settings.prompt.strip() or request['prompt'],
                    negativePrompt=settings.negativePrompt)

    def emit(event):
        emit_event(request.get('eventPath'), {**event, 'elapsedMs': round((perf_counter() - started) * 1000)})

    def stage(label):
        emit({'type': 'stage', 'stage': label})

    owned_stages = False
    try:
        if visual and not edge_lighting:
            from identity_stage_artifacts import visual_stage_path
            # A fresh parent-issued jobId owns this directory. Refuse collisions
            # before creating a polisher that could clean up pre-existing stages.
            folder = visual_stage_path(item, 'anchor').parent
            folder.mkdir(parents=True, exist_ok=False)
            owned_stages = True
            visual_stage_path(item, 'anchor')
        point = perf_counter()
        if edge_lighting:
            from identity_edge_lighting import improve_edge_lighting
        elif not visual and not item.get('animeProfileId'):
            from identity_pipeline import configure_cuda
            from identity_face_polish import FacePolisher
            configure_cuda()
            processor = (restore_factory or FacePolisher)(config, item)
        else:
            from identity_pipeline import IdentitySession
            session = IdentitySession(config, item, emit)
            processor = session.face_polisher(item)
        phases['load'] = (perf_counter() - point) * 1000
        point = perf_counter()
        # Do not use optional_face_polish: its fallback is appropriate for base
        # generation, but would turn a failed independent edit into fake success.
        if edge_lighting:
            candidate, details = improve_edge_lighting(config, item, baseline.copy(), settings.strength, stage)
        else:
            candidate, details = processor.apply(baseline.copy(), item, settings.strength, stage)
        phases['polish'] = (perf_counter() - point) * 1000
        if candidate.size != baseline.size or candidate.mode != 'RGB':
            raise ValueError('精修输出尺寸或颜色格式异常')
        if details.get('status') in ('failed', 'disabled') or details.get('enabled') is False:
            raise ValueError('精修处理未成功，未发布回退图像')
    finally:
        if owned_stages:
            from identity_stage_artifacts import cleanup_visual_stages
            inference_error = sys.exc_info()[1]
            try:
                cleanup_visual_stages(item)
            except Exception as cleanup_error:
                if inference_error is None:
                    raise
                # Preserve the actual pipeline failure as the worker's cause.
                # No output is published on this path; retain cleanup evidence.
                inference_error.add_note(f'Refinement stage cleanup also failed: {cleanup_error}')

    point = perf_counter()
    diagnostics = details.get('diagnostics')
    if edge_lighting and not isinstance(diagnostics, dict):
        raise ValueError('edge-lighting helper must return diagnostics from its actual masks')
    if diagnostics is None:
        diagnostics = compare_images(baseline, candidate, baseline_label='selected-source', candidate_label='refinement')
        unchanged = diagnostics['retention']['whole']['changedPixels'] == 0
    else:
        if not isinstance(diagnostics, dict):
            raise ValueError('Invalid processor diagnostics')
        # Keep the helper's measured edit/protected regions. Do not infer masks
        # from a bounding box or pixel difference, and verify no-op independently.
        unchanged = baseline.tobytes() == candidate.tobytes()
    if unchanged:
        raise ValueError('精修未产生像素变化，未发布未修改图像')
    phases['diagnostics'] = (perf_counter() - point) * 1000
    point = perf_counter()
    _publish_image(candidate, output)
    phases['save'] = (perf_counter() - point) * 1000
    # Those stage images were private scratch, not readable history versions.
    polish = {key: value for key, value in details.items() if key not in ('snapshots', 'diagnostics')}
    return {'ok': True, 'mode': settings.mode, 'sessionReused': False, 'durationMs': round((perf_counter() - started) * 1000, 3),
            'phasesMs': {name: round(value, 3) for name, value in phases.items()},
            'polish': polish, 'diagnostics': diagnostics}
