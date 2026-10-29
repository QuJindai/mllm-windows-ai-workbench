"""One restore-only processor in the existing owned JSON-lines transport.

The service must use its SINGLE persistent-worker slot and release barrier,
switching processes when moving between batch generation and this adapter.
No inference imports occur before the ownership handshake and first request.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import os
from pathlib import Path
import sys
from time import perf_counter

from identity_persistent_worker import _asset, _json, IDLE_TTL, WorkerRestartRequired, serve

MAX_RESTORES = 32
RESTORE_MODELS = ('realistic-vision-v5.1-faceid', 'illustrious-xl-v2.0-faceid')
PER_EDIT = {'sourcePath', 'outputPath', 'jobId', 'eventPath', 'editSettings', 'seed', 'prompt', 'negativePrompt', 'steps'}


def is_restore_only(request):
    settings = request.get('editSettings')
    return (isinstance(settings, dict) and settings.get('mode') == 'restore'
            and request.get('modelId', RESTORE_MODELS[0]) in RESTORE_MODELS
            and not request.get('animeProfileId') and not request.get('animeProfile'))


def build_restore_key(config, request):
    """Hash only consumed restoration/reference assets, including their bytes.

    Generation weights are deliberately not scanned. Content changes, even at
    identical sizes/timestamps, invalidate reuse before any edit starts.
    """
    from identity_contract import IdentityGenerateRequest
    from identity_refinement_engine import _EditSettings
    if not is_restore_only(request):
        raise ValueError('Warm refinement supports only plain FaceID restore')
    _EditSettings.model_validate(request['editSettings'])
    normalized = IdentityGenerateRequest.model_validate({key: value for key, value in request.items()
                                                        if key in IdentityGenerateRequest.model_fields}).model_dump()
    paths = {}
    for key in ('faceSwapModel', 'faceRestoreModel', 'faceDetectionRoot', 'insightfaceRoot'):
        if not isinstance(config.get(key), str) or not config[key]:
            raise ValueError('Restore asset configuration is incomplete')
        path = Path(config[key])
        paths[key] = path / 'models' / 'buffalo_l' if key == 'insightfaceRoot' else path
    paths['reference'] = Path(request['imagePath'])
    if request.get('configPath'):
        paths['runtimeConfig'] = Path(request['configPath'])
    inputs = {}
    for key, path in paths.items():
        inputs[key] = _asset(path)
        if inputs[key].get('missing'):
            raise ValueError('Restore asset is missing')
    fixed = {key: value for key, value in {**request, **normalized}.items() if key not in PER_EDIT}
    return hashlib.sha256(_json({'version': 1, 'config': config, 'inputs': inputs, 'fixed': fixed})).hexdigest()


class WarmRestoreWorker:
    def __init__(self, config_loader, *, processor_factory=None):
        self.config_loader = config_loader
        self.processor_factory = processor_factory
        self.processor = None
        self.key = None
        self.completed_restores = 0
        self.closed = False

    def close(self):
        self.closed = True
        self.processor = None
        self.key = None
        gc.collect()

    def run_refine(self, request):
        if self.closed:
            raise RuntimeError('Restore worker is closed')
        try:
            started = perf_counter()
            if not is_restore_only(request):
                raise ValueError('Warm refinement supports only plain FaceID restore')
            config = self.config_loader(request)
            key = build_restore_key(config, request)
            if self.processor is not None and (self.key != key or self.completed_restores >= MAX_RESTORES):
                # The client may restart only here, before calling the engine.
                raise WorkerRestartRequired('A fresh restore processor is required')
            compatibility_ms = (perf_counter() - started) * 1000
            reused = self.processor is not None

            def processor(config, item):
                if self.processor is None:
                    factory = self.processor_factory
                    if factory is None:
                        from identity_face_polish import FacePolisher
                        factory = FacePolisher
                    self.processor = factory(config, item)
                    self.key = key
                return self.processor

            from identity_refinement_engine import refine
            result = refine(config, request, restore_factory=processor)
            self.completed_restores += 1
            return {**result, 'processorReused': reused, 'sessionReused': reused,
                    'durationMs': round((perf_counter() - started) * 1000, 3),
                    'phasesMs': {'compatibility': round(compatibility_ms, 3), **result['phasesMs']}}
        except BaseException:
            self.close()
            raise


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--ownership-handshake', action='store_true')
    parser.add_argument('--idle-ttl', type=float, default=IDLE_TTL)
    args = parser.parse_args()
    from identity_worker import load_config
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    worker = WarmRestoreWorker(lambda request: load_config(request, operation='refine'))
    code = serve(worker, sys.stdin.buffer, sys.stdout.buffer, operation='refine',
                 idle_ttl=args.idle_ttl, ownership_handshake=args.ownership_handshake)
    # Same blocked-reader finalization boundary as the existing persistent CLI.
    os._exit(code)


if __name__ == '__main__':
    main()
