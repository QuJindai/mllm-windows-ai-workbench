"""Optional image-space reference initialization, using detection geometry only."""
import math
from pathlib import Path


def similarity_alignment(source, target):
    import numpy as np
    source, target = np.asarray(source, dtype=float), np.asarray(target, dtype=float)
    if source.shape != (5, 2) or target.shape != (5, 2) or not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError('参考脸关键点不可用，请使用清晰近正脸')
    if min(np.linalg.norm(source[1]-source[0]), np.linalg.norm(target[1]-target[0])) < 8:
        raise ValueError('人脸关键点间距过小，无法可靠对齐')
    rows, values = [], []
    for (x, y), (u, v) in zip(source, target):
        rows.extend([[x, -y, 1, 0], [y, x, 0, 1]])
        values.extend([u, v])
    a, b, tx, ty = np.linalg.lstsq(np.array(rows), np.array(values), rcond=None)[0]
    matrix = np.array([[a, -b, tx], [b, a, ty], [0., 0., 1.]])
    predicted = np.column_stack([source, np.ones(5)]) @ matrix[:2].T
    error = float(np.sqrt(np.mean(np.sum((predicted-target)**2, axis=1))) / np.linalg.norm(target[1]-target[0]))
    # This is geometric fit error, never an identity-similarity score.
    if not np.isfinite(matrix).all() or not math.isfinite(error) or error > .18 or a*a+b*b < 1e-6:
        raise ValueError('参考脸与目标脸姿态差异过大，已保留原图；请换近似角度参考')
    return matrix, error


def align_reference_face(reference, image, source_points, target_points, box, strength):
    import numpy as np
    from PIL import Image, ImageChops
    from identity_anime import face_mask
    if type(strength) not in (int, float) or not math.isfinite(strength) or not .3 <= strength <= 1:
        raise ValueError('参考脸保留强度必须为 0.3–1')
    if len(box) != 4 or not all(math.isfinite(v) for v in box) or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
        raise ValueError('目标脸区域无效')
    matrix, error = similarity_alignment(source_points, target_points)
    inverse = tuple(np.linalg.inv(matrix)[:2].ravel())
    aligned = reference.convert('RGB').transform(image.size, Image.Transform.AFFINE, inverse, Image.Resampling.BICUBIC)
    # Warped pixels outside the source canvas are invalid, not black face pixels.
    valid = Image.new('L', reference.size, 255).transform(image.size, Image.Transform.AFFINE, inverse, Image.Resampling.BILINEAR)
    face = face_mask(image.size, box)
    support = np.asarray(face) >= 128
    if not support.any() or float(np.mean(np.asarray(valid)[support])) < 255*.90:
        raise ValueError('参考图有效像素不足以覆盖目标脸，已保留原图')
    mask = ImageChops.multiply(face, valid).point(lambda value: round(value*strength))
    return Image.composite(aligned, image.convert('RGB'), mask), {'anchorStrength': strength, 'alignmentError': error}


class ReferenceAnchor:
    def __init__(self, config, image_path, face_index):
        import numpy as np
        import onnxruntime as ort
        from PIL import Image
        from insightface.model_zoo.scrfd import SCRFD
        model = Path(config['insightfaceRoot']) / 'models/buffalo_l/det_10g.onnx'
        if not model.is_file():
            raise ValueError('参考脸对齐检测模型未配置')
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
        self.detector = SCRFD(str(model), session=ort.InferenceSession(str(model), sess_options=options, providers=['CPUExecutionProvider']))
        self.detector.prepare(ctx_id=-1, input_size=(640,640))
        with Image.open(image_path) as source:
            self.reference = source.convert('RGB')
        boxes, points = self.detector.detect(np.asarray(self.reference)[:,:,::-1].copy(), max_num=0)
        ordered = sorted(range(len(boxes)), key=lambda i:(float(boxes[i][0]),float(boxes[i][1])))
        if not 0 <= face_index < len(ordered) or points is None:
            raise ValueError('参考图未取得可靠五点位置，请使用清晰近正脸')
        self.points = points[ordered[face_index]]

    def apply(self, image, strength):
        import numpy as np
        boxes, points = self.detector.detect(np.asarray(image.convert('RGB'))[:,:,::-1].copy(), max_num=0)
        if len(boxes) > 1:
            raise ValueError('目标图有多个人脸，未自动选择替换对象')
        if len(boxes) != 1 or points is None:
            raise ValueError('目标图未取得可靠五点位置，请使用清晰近正脸')
        box = [float(max(0,min(v,limit))) for v,limit in zip(boxes[0][:4],(image.width,image.height,image.width,image.height))]
        result, info = align_reference_face(self.reference,image,self.points,points[0],box,strength)
        return result, box, info
