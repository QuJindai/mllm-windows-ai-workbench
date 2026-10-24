"""CPU face parsing and protected-region compositing for reference anchoring."""
from pathlib import Path


def skin_labels(labels):
    import numpy as np
    # ParseNet's taxonomy differs from BiSeNet: 13 is HAIR, 7 is right brow.
    # https://github.com/xinntao/facexlib/blob/master/inference/inference_parsing_parsenet.py
    return np.isin(labels, [1, 2, 3, 4, 5, 6, 7, 10, 11, 12])


class FaceRegionParser:
    def __init__(self, config):
        import torch
        from facexlib.parsing.parsenet import ParseNet
        path = Path(config.get('faceParsingModel', ''))
        if not path.is_file():
            raise ValueError('参考脸边缘融合需要配置本地 ParseNet 模型，请保留原图')
        self.model = ParseNet(in_size=512, out_size=512, parsing_ch=19).eval()
        self.model.load_state_dict(torch.load(path, map_location='cpu', weights_only=True), strict=True)

    def labels(self, image, box):
        import numpy as np
        import torch
        from PIL import Image
        x1, y1, x2, y2 = box
        side = max(x2-x1, y2-y1)*1.4
        cx, cy = (x1+x2)/2, (y1+y2)/2
        rect = (int(cx-side/2), int(cy-side/2), int(cx+side/2), int(cy+side/2))
        rgb = np.asarray(image.convert('RGB').crop(rect).resize((512,512), Image.Resampling.BILINEAR)).copy()
        tensor = torch.from_numpy(rgb.transpose(2,0,1)).float().unsqueeze(0)/127.5-1
        with torch.inference_mode():
            labels = self.model(tensor)[0].argmax(1)[0].numpy().astype('uint8')
        canvas = Image.new('L', image.size)
        canvas.paste(Image.fromarray(labels).resize((rect[2]-rect[0], rect[3]-rect[1]), Image.Resampling.NEAREST), rect[:2])
        return np.asarray(canvas)


def region_masks(source_labels, target_labels, points, box):
    import cv2
    import numpy as np
    from PIL import Image
    from identity_anime import face_mask
    source, target = np.asarray(source_labels), np.asarray(target_labels)
    points = np.asarray(points, dtype=float)
    if source.ndim != 2 or source.shape != target.shape or points.shape != (5,2) or not np.isfinite(points).all():
        raise ValueError('人脸区域数据无效，已保留原图')
    allowed = np.asarray(face_mask((source.shape[1], source.shape[0]), box)) > 0
    support = skin_labels(source) & skin_labels(target) & allowed
    distance = cv2.distanceTransform(support.astype('uint8'), cv2.DIST_L2, 5)
    feather = max(3., min(box[2]-box[0], box[3]-box[1])*.08)
    alpha = np.clip(distance/feather, 0, 1)
    if np.sum(alpha > .95) < 100:
        raise ValueError('参考脸与目标脸有效区域不足，已保留原图')
    for x, y in points:
        ix, iy = round(x), round(y)
        if not (0 <= ix < source.shape[1] and 0 <= iy < source.shape[0]) or alpha[iy,ix] < .8:
            raise ValueError('参考脸五官被遮挡或超出目标脸，已保留原图')
    for label in (2,4,5,6,7,10,11,12):
        feature = source == label
        # Check semantic clipping, not normal feathering next to the hairline.
        if feature.sum() >= 4 and np.mean(support[feature]) < .90:
            raise ValueError('参考脸五官区域被遮挡或裁切，已保留原图；请换相近姿态的底图')
    # Include the source eyebrows explicitly; five SCRFD points alone omit them.
    protected = np.isin(source, [2,3,4,5,6,7,10,11,12]).astype('uint8')*255
    cv2.fillConvexPoly(protected, cv2.convexHull(np.int32(points)), 255)
    radius = max(3, round(np.linalg.norm(points[1]-points[0])*.10))
    protected = cv2.dilate(protected, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1))) > 0
    # Smooth to zero at BOTH sides of the seam. Reapply exclusions after feathering.
    ring = np.sin(np.pi*np.clip(distance/(feather*3), 0, 1))
    feature_distance = cv2.distanceTransform((~protected).astype('uint8'), cv2.DIST_L2, 5)
    ring *= np.clip(feature_distance/max(4.,feather*.7), 0, 1)
    ring[~support | protected | (distance >= feather*3)] = 0
    ring = np.uint8(np.rint(np.clip(ring,0,1)*255))
    if not np.any(ring):
        raise ValueError('缺少可融合的脸部边缘区域，已保留原图')
    return alpha, Image.fromarray(ring), protected


def harmonized_anchor(aligned, image, alpha, strength):
    import cv2
    import numpy as np
    from PIL import Image
    source = cv2.cvtColor(np.asarray(aligned), cv2.COLOR_RGB2LAB).astype(float)
    target = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2LAB).astype(float)
    stable = alpha > .95
    delta = np.clip(np.median(target[stable],axis=0)-np.median(source[stable],axis=0), [-12,-6,-6], [12,6,6])
    # A bounded colour offset, never a reshape or a texture/beauty restorer.
    corrected = cv2.cvtColor(np.uint8(np.clip(source+delta,0,255)),cv2.COLOR_LAB2RGB)
    mask = Image.fromarray(np.uint8(np.rint(alpha*strength*255)))
    return Image.composite(Image.fromarray(corrected), image.convert('RGB'), mask)


def composite_region(image, patch, crop, mask):
    from PIL import Image
    canvas = image.convert('RGB').copy()
    canvas.paste(patch.resize((crop[2]-crop[0],crop[3]-crop[1]), Image.Resampling.LANCZOS), crop[:2])
    # Native-resolution mask is authoritative. VAE/resizing cannot change its zeros.
    return Image.composite(canvas, image.convert('RGB'), mask)
