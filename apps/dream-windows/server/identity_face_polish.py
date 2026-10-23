"""Optional, local-only identity reapplication and GFPGAN face restoration.

No ComfyUI imports, downloads, or inference imports on the disabled path.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
import time
from pathlib import Path


def face_polish_status(config, find_spec=importlib.util.find_spec):
    paths = (config.get('faceSwapModel', ''), config.get('faceRestoreModel', ''),
             Path(config.get('faceDetectionRoot', '')) / 'detection_Resnet50_Final.pth',
             Path(config.get('faceDetectionRoot', '')) / 'parsing_parsenet.pth')
    if not all(Path(path).is_file() for path in paths):
        return {'ready': False, 'message': '可选修脸模型配置不完整；关闭修脸仍可生成人物'}
    missing = [name for name in ('spandrel', 'facexlib', 'cv2', 'insightface', 'onnxruntime', 'torch') if find_spec(name) is None]
    if missing:
        return {'ready': False, 'message': '可选修脸组件缺少：' + ', '.join(missing)}
    return {'ready': True, 'message': '本地身份回贴与 GFPGAN 模型就绪；修脸效果请对比原图'}


def single_target(faces):
    if not faces:
        raise ValueError('生成图未检测到清晰人脸，请尝试近景肖像')
    if len(faces) != 1:
        raise ValueError('生成图有多个人脸，未自动选择替换对象；请使用单人构图')
    return faces[0]


def save_original(image, item):
    root = Path(item['dreamRoot']).resolve()
    path = root / 'data' / 'identity' / 'originals' / (item['jobId'] + '.png')
    if path.resolve() != path:
        raise ValueError('人物原图路径被重定向，未写入')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != path or path.exists():
        raise ValueError('人物原图路径无效或已存在，未覆盖')
    temp = None
    try:
        # Exclusive, random temporary file: don't follow an attacker-supplied .tmp.
        with tempfile.NamedTemporaryFile(mode='w+b', prefix=item['jobId'] + '-', suffix='.tmp', dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            image.save(stream, format='PNG')
        if path.resolve() != path:
            raise ValueError('人物原图路径被重定向，未写入')
        os.replace(temp, path)
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError as exc:
                print(f'Original temporary cleanup failed: {exc}', file=sys.stderr)


def optional_face_polish(image, params, item, processor_factory, stage):
    if not params.facePolish:
        return image, {'enabled': False, 'status': 'disabled'}
    job_id = item['jobId']
    if not re.fullmatch(r'identity-[a-f0-9]{24}', job_id):
        raise ValueError('人物任务编号无效')
    info = {'enabled': True, 'status': 'failed', 'restoreStrength': params.faceRestoreStrength}
    started = time.perf_counter()
    try:
        save_original(image, item)
        info['originalImageUrl'] = f'/api/identity/jobs/{job_id}/original'
        processed, details = processor_factory().apply(image, item, params.faceRestoreStrength, stage)
        if processed.size != image.size or processed.mode != 'RGB':
            raise ValueError('修脸输出尺寸或颜色格式异常')
        info.update(details)
        info['status'] = 'completed'
        return processed, info
    except Exception as exc:
        # Base generation remains usable, but never label a partial swap as repaired.
        print(f'Face polish failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        reason = str(exc) if isinstance(exc, ValueError) else '处理异常，请查看本地任务日志'
        info['message'] = '修脸失败，已保留原图：' + reason[:240]
        return image, info
    finally:
        info['durationMs'] = round((time.perf_counter() - started) * 1000)


class FacePolisher:
    """CPU face detection/swap, sequential CUDA restoration, reused within a batch."""
    def __init__(self, config, item):
        status = face_polish_status(config)
        if not status['ready']:
            raise ValueError(status['message'])
        import onnxruntime as ort
        import torch
        from facexlib.utils.face_restoration_helper import FaceRestoreHelper
        from insightface.model_zoo.inswapper import INSwapper
        from insightface.model_zoo.scrfd import SCRFD
        from spandrel import ModelLoader
        from identity_features import FingerprintCache
        from identity_pipeline import face_analysis, select_face

        self.reference = (item['imagePath'], item['faceIndex'])
        _, faces = face_analysis(config, item['imagePath'])
        self.source = select_face(faces, item['faceIndex'])
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        def session(path):
            return ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])
        detector = Path(config['insightfaceRoot']) / 'models/buffalo_l/det_10g.onnx'
        self.detector = SCRFD(str(detector), session=session(detector))
        self.detector.prepare(ctx_id=-1, input_size=(640, 640))
        self.swapper = INSwapper(config['faceSwapModel'], session=session(config['faceSwapModel']))
        # All files were checked first: the helper must use existing local weights.
        self.helper = FaceRestoreHelper(1, face_size=512, crop_ratio=(1, 1),
                                       det_model='retinaface_resnet50', use_parse=True,
                                       device=torch.device('cpu'), model_rootpath=config['faceDetectionRoot'])
        weights = torch.load(config['faceRestoreModel'], map_location='cpu', weights_only=True)
        descriptor = ModelLoader(device='cpu').load_from_state_dict(weights.get('params_ema', weights.get('params', weights)))
        if str(descriptor.architecture.id) != 'GFPGAN':
            raise ValueError('修脸配置必须使用 GFPGAN 模型')
        self.restorer = descriptor.model.eval()
        fingerprints = FingerprintCache(Path(item['dreamRoot']) / 'data/identity/fingerprints.json')
        self.hashes = {key: fingerprints.digest(config[key]) for key in ('faceSwapModel', 'faceRestoreModel')}

    def apply(self, image, item, strength, stage):
        import cv2
        import numpy as np
        import torch
        from PIL import Image
        from insightface.app.common import Face
        if (item['imagePath'], item['faceIndex']) != self.reference:
            raise ValueError('修脸参考人脸与当前档案不一致')
        stage('身份回贴')
        bgr = np.asarray(image.convert('RGB'))[:, :, ::-1].copy()
        boxes, landmarks = self.detector.detect(bgr, max_num=0)
        target = single_target([Face(bbox=box[:4], kps=points) for box, points in zip(boxes, landmarks)])
        swapped = self.swapper.get(bgr, target, self.source, paste_back=True)
        if strength == 0:
            return Image.fromarray(swapped[:, :, ::-1]), self.details(restore=False)
        stage('面部细节修复')
        helper = self.helper
        helper.clean_all()
        try:
            helper.read_image(swapped)
            count = helper.get_face_landmarks_5(eye_dist_threshold=5)
            single_target(list(range(count)))
            helper.align_warp_face()
            crop = helper.cropped_faces[0]
            tensor = torch.from_numpy(np.ascontiguousarray(crop[:, :, ::-1].transpose(2, 0, 1))).float().div_(127.5).sub_(1).unsqueeze(0).to('cuda')
            # The generating pipeline is offloaded before this call. No FP16 GFPGAN:
            # its original clean architecture requires FP32 for stable facial details.
            self.restorer.to('cuda')
            with torch.inference_mode():
                restored = self.restorer(tensor, return_rgb=False, randomize_noise=False)[0]
            if not torch.isfinite(restored).all():
                raise ValueError('修脸输出含非有限数值')
            restored = restored.squeeze(0).float().cpu().clamp_(-1, 1).add_(1).mul_(127.5).numpy().transpose(1, 2, 0)[:, :, ::-1]
            restored = np.clip(crop * (1 - strength) + restored * strength, 0, 255).round().astype(np.uint8)
            helper.add_restored_face(restored)
            helper.get_inverse_affine()
            final = helper.paste_faces_to_input_image()
            if final.shape != bgr.shape:
                raise ValueError('修脸输出尺寸异常')
            return Image.fromarray(cv2.cvtColor(final, cv2.COLOR_BGR2RGB)), self.details()
        finally:
            self.restorer.to('cpu')
            helper.clean_all()
            torch.cuda.empty_cache()

    def details(self, restore=True):
        return {'swapModel': 'inswapper_128.onnx', 'restoreModel': 'GFPGANv1.4.pth',
                'swapDevice': 'CPU', 'restoreDevice': 'CUDA FP32' if restore else 'not-run (strength=0)', 'assetHashes': self.hashes}
