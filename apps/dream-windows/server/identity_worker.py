from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


def load_config(request, *, operation='generate'):
    path = Path(request.get('configPath') or os.environ.get('DREAM_IDENTITY_CONFIG', r'E:\Dream\data\identity\runtime.json'))
    if not path.is_file():
        raise ValueError('人物运行配置不存在')
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if operation == 'status':
        return config
    from identity_models import DEFAULT_MODEL_ID, resolve_identity_model, validate_extraction_assets
    if operation in ('inspect', 'prepare', 'anime_prepare'):
        kind = request.get('referenceKind', 'faceid') if operation != 'anime_prepare' else 'faceid'
        if kind not in ('faceid', 'visual'):
            raise ValueError('参考类型配置无效')
        return validate_extraction_assets(config, clip=operation != 'inspect', reference_kind=kind)
    selected = request.get('items', [request])[0]
    return resolve_identity_model(config, selected.get('modelId', DEFAULT_MODEL_ID))


def require_dependencies(find_spec=importlib.util.find_spec):
    missing = [name for name in ('torch', 'diffusers', 'transformers', 'insightface', 'onnxruntime', 'peft', 'accelerate', 'safetensors', 'PIL', 'pydantic') if find_spec(name) is None]
    if missing:
        raise ValueError('人物环境配置缺少组件：' + ', '.join(missing))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--persistent', action='store_true')
    parser.add_argument('--ownership-handshake', action='store_true')
    parser.add_argument('--idle-ttl', type=float, default=60.)
    parser.add_argument('--operation', choices=['status', 'inspect', 'generate', 'prepare', 'anime_prepare', 'batch'])
    parser.add_argument('--request', type=Path)
    parser.add_argument('--result', type=Path)
    args = parser.parse_args()
    if args.persistent:
        if args.operation or args.request or args.result:
            parser.error('--persistent does not accept file-operation arguments')
        from identity_persistent_worker import WarmBatchWorker, serve
        os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        code = serve(WarmBatchWorker(lambda request: load_config(request, operation='batch')),
                     sys.stdin.buffer, sys.stdout.buffer, idle_ttl=args.idle_ttl,
                     ownership_handshake=args.ownership_handshake)
        # The daemon reader can still be blocked in buffered stdin on idle
        # expiry. Avoid interpreter-finalization races; serve closed its session
        # and flushed each response. OS process exit is the CUDA release barrier.
        os._exit(code)
    if args.ownership_handshake:
        parser.error('--ownership-handshake requires --persistent')
    if not args.operation or args.request is None or args.result is None:
        parser.error('--operation, --request and --result are required')
    try:
        request = json.loads(args.request.read_text(encoding='utf-8-sig'))
        config = load_config(request, operation=args.operation)
        from identity_pipeline import generate, inspect_reference, registered_loras, prepare, generate_batch
        if args.operation == 'status':
            require_dependencies()
            from identity_face_polish import face_polish_status
            from identity_models import identity_model_catalog, is_visual_model_id
            models = identity_model_catalog(config)
            result = {'ready': any(row['ready'] for row in models), 'modelName': models[0]['name'], 'message': '请选择已就绪的人物底模', 'loras': models[0]['loras'], 'models': models, 'facePolish': face_polish_status(config)}
            from identity_anime import anime_status
            result['animePolish'] = anime_status(config)
            from identity_visual_polish import visual_polish_status
            visual = visual_polish_status(config)
            visual_model_ready = any(is_visual_model_id(row['id']) and row['ready'] for row in models)
            result['visualPolish'] = {
                'ready': visual['ready'] and visual_model_ready,
                'message': visual['message'] if visual_model_ready else '动漫视觉底模未就绪，无法使用视觉局部重绘',
                'referenceAnchorReady': visual.get('referenceAnchorReady', False) and visual_model_ready,
                'referenceAnchorMessage': (visual.get('referenceAnchorMessage', '参考脸对齐组件状态不可用')
                                           if visual_model_ready else '动漫视觉底模未就绪，无法使用参考脸对齐'),
            }
        elif args.operation == 'inspect':
            result = inspect_reference(config, request)
        elif args.operation == 'prepare':
            result = prepare(config, request)
        elif args.operation == 'anime_prepare':
            from identity_anime import prepare_anime
            result = prepare_anime(config, request)
        elif args.operation == 'batch':
            result = generate_batch(config, request)
        else:
            result = generate(config, request)
        code = 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) and '配置' in str(exc) else '人物处理失败，请查看本地任务日志'
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        if args.operation == 'status':
            result = {'ready': False, 'modelName': 'Realistic Vision V5.1 + FaceID Plus V2', 'message': message, 'loras': []}
        else:
            result = {'ok': False, 'code': 'IDENTITY_WORKER_FAILED', 'message': message}
        code = 1
    args.result.parent.mkdir(parents=True, exist_ok=True)
    temp = args.result.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, args.result)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
