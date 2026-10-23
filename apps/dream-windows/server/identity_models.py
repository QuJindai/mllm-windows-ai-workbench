"""Allowlisted identity bundles. Client requests select IDs, never local paths."""
from pathlib import Path

DEFAULT_MODEL_ID = 'realistic-vision-v5.1-faceid'
ILLUSTRIOUS_MODEL_ID = 'illustrious-xl-v2.0-faceid'
VISUAL_MODEL_ID = 'cyberrealistic-xl-plus-face'
ILLUSTRIOUS_VISUAL_MODEL_ID = 'illustrious-xl-v2.0-plus-face'
EXPERIMENTAL_VISUAL_DISABLED_MESSAGE = '实验性：本机画质验收未通过，默认禁用，请使用Cyber视觉路线'
MODEL_SPECS = {
    DEFAULT_MODEL_ID: ('Realistic Vision V5.1 + FaceID Plus V2', 'SD1.5'),
    ILLUSTRIOUS_MODEL_ID: ('Illustrious XL v2.0 + FaceID Plus V2 SDXL', 'SDXL'),
    VISUAL_MODEL_ID: ('CyberRealistic XL + Plus Face（动漫视觉参考）', 'SDXL'),
    ILLUSTRIOUS_VISUAL_MODEL_ID: ('Illustrious XL v2.0 + Plus Face（动漫视觉参考）', 'SDXL'),
}
BUNDLE_KEYS = ('checkpoint', 'adapter', 'faceLora', 'pipelineConfig')


def is_visual_model_id(model_id):
    return model_id in (VISUAL_MODEL_ID, ILLUSTRIOUS_VISUAL_MODEL_ID)


def require_identity_model_enabled(config, model_id):
    # Runtime-only opt-in. Truthy strings/numbers and request fields are not consent.
    if model_id == ILLUSTRIOUS_VISUAL_MODEL_ID and config.get('allowExperimentalVisualModels') is not True:
        raise ValueError(EXPERIMENTAL_VISUAL_DISABLED_MESSAGE)


def visual_restore_model(model_id):
    if not is_visual_model_id(model_id):
        raise ValueError('不支持的视觉参考模型')
    return MODEL_SPECS[model_id][0].split('（', 1)[0] + ' visual reference'


def validate_extraction_assets(config, *, clip=True, reference_kind='faceid'):
    if clip and not Path(config.get('clipVision', '')).is_file():
        raise ValueError('人物模型配置不完整：clipVision')
    for filename in (('det_10g.onnx',) if reference_kind == 'visual' else ('det_10g.onnx', 'w600k_r50.onnx')):
        if not (Path(config.get('insightfaceRoot', '')) / 'models' / 'buffalo_l' / filename).is_file():
            raise ValueError('本地 InsightFace 模型配置不完整')
    return config


def resolve_identity_model(config, model_id=DEFAULT_MODEL_ID):
    if model_id not in MODEL_SPECS:
        raise ValueError('人物模型配置不支持该模型')
    require_identity_model_enabled(config, model_id)
    selected = dict(config)
    if model_id != DEFAULT_MODEL_ID:
        bundle = config.get('models', {}).get(model_id, {})
        if model_id == ILLUSTRIOUS_VISUAL_MODEL_ID:
            # Explicit composition of installed SDXL assets, never root/SD1.5
            # defaults or the FaceID adapter/LoRA from the checkpoint bundle.
            models = config.get('models', {})
            base = models.get(ILLUSTRIOUS_MODEL_ID, {})
            visual = models.get(VISUAL_MODEL_ID, {})
            bundle = {key: base.get(key, '') for key in ('checkpoint', 'pipelineConfig')}
            bundle['adapter'] = visual.get('adapter', '')
        # Never inherit SD1.5 assets when an SDXL bundle is incomplete.
        for key in BUNDLE_KEYS:
            selected[key] = bundle.get(key, '')
    name, architecture = MODEL_SPECS[model_id]
    kind = 'visual' if is_visual_model_id(model_id) else 'faceid'
    selected.update(modelId=model_id, modelName=name, architecture=architecture, referenceKind=kind)
    if kind == 'visual':
        selected['faceLora'] = ''
    for key in (('checkpoint', 'adapter') if kind == 'visual' else ('checkpoint', 'adapter', 'faceLora')):
        if not Path(selected.get(key, '')).is_file():
            raise ValueError(f'人物模型配置不完整：{key}')
    if not selected.get('pipelineConfig') or not Path(selected['pipelineConfig']).is_dir():
        raise ValueError(f'{architecture} 配置目录不可用')
    validate_extraction_assets(selected, reference_kind=kind)
    return selected


def identity_model_catalog(config):
    from identity_pipeline import registered_loras
    rows = []
    for model_id, (name, architecture) in MODEL_SPECS.items():
        row = dict(id=model_id, name=name, architecture=architecture, ready=False, loras=[],
                   referenceKind='visual' if is_visual_model_id(model_id) else 'faceid')
        if model_id == ILLUSTRIOUS_VISUAL_MODEL_ID:
            row.update(experimental=True, qualityStatus='failed')
            if config.get('allowExperimentalVisualModels') is not True:
                row['message'] = EXPERIMENTAL_VISUAL_DISABLED_MESSAGE
                rows.append(row)
                continue
        try:
            resolved = resolve_identity_model(config, model_id)
            row.update(ready=True, message='模型文件就绪，实际效果需生成验证',
                       loras=[{key: entry[key] for key in ('id', 'name')} for entry in registered_loras(resolved)])
            if model_id == ILLUSTRIOUS_VISUAL_MODEL_ID:
                row['message'] = '实验性：本机画质验收未通过，已显式启用，仅供实验；建议使用Cyber视觉路线'
        except (ValueError, OSError, TypeError, AttributeError):
            row['message'] = '本机配套模型配置不完整，无法使用此底模'
        rows.append(row)
    return rows
