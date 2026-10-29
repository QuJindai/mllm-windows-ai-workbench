"""Freeze and evaluate local image datasets. Does not generate images or use GPU."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys


SERVER = Path(__file__).resolve().parents[1] / 'apps/dream-windows/server'
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')


def validate_manifest(manifest, *, require_hashes=True):
    """Validate structure and provenance; does not touch image files."""
    canonical_hash(manifest)  # Reject NaN and non-JSON settings/source values.
    if manifest.get('schemaVersion') != 1:
        raise ValueError('unsupported manifest schemaVersion')
    _text(manifest.get('datasetId'), 'datasetId')
    cases = manifest.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('cases must be a nonempty list')
    ids = set()
    for case in cases:
        _text(case.get('id'), 'case id')
        if case['id'] in ids:
            raise ValueError('duplicate case id')
        ids.add(case['id'])
        _text(case.get('route'), 'route')
        variants = case.get('variants')
        if not isinstance(variants, list) or not variants:
            raise ValueError('variants must be a nonempty list')
        variant_ids = set()
        for variant in variants:
            _text(variant.get('id'), 'variant id')
            if variant['id'] in variant_ids:
                raise ValueError('duplicate variant id')
            variant_ids.add(variant['id'])
        images = [case.get('baseline', {})] + variants
        for record in images:
            if type(record.get('seed')) is not int or record['seed'] < 0:
                raise ValueError('seed must be an explicit nonnegative integer')
            for key in ('settings', 'source'):
                if not isinstance(record.get(key), dict) or not record[key]:
                    raise ValueError(f'{key} provenance is required')
        masks = case.get('masks', {})
        if not isinstance(masks, dict) or set(masks) - {'edit', 'protected'}:
            raise ValueError('masks supports only edit and protected')
        for record in images + list(masks.values()):
            _text(record.get('path'), 'artifact path')
            if require_hashes:
                digest = record.get('sha256', '')
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('artifact sha256 is required')
                if not Path(record['path']).is_absolute():
                    raise ValueError('frozen artifact path must be absolute')


def freeze_manifest(spec, *, base_dir):
    """Copy spec, resolve local paths and pin file bytes; preserve all metadata."""
    validate_manifest(spec, require_hashes=False)
    manifest = copy.deepcopy(spec)
    for case in manifest['cases']:
        records = [case['baseline']] + case['variants'] + list(case.get('masks', {}).values())
        for record in records:
            path = Path(record['path'])
            path = (Path(base_dir) / path).resolve()
            digest = file_hash(path)
            if record.get('sha256') is not None and record['sha256'] != digest:
                raise ValueError(f'sha256 mismatch: {path}')
            record.update(path=str(path), sha256=digest)
    validate_manifest(manifest)
    return manifest


def _read_image(record, *, mask=False):
    # Decode exactly the bytes hashed, avoiding replacement between hash and open.
    from io import BytesIO
    from PIL import Image
    data = Path(record['path']).read_bytes()
    if hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError(f'sha256 mismatch: {record["path"]}')
    with Image.open(BytesIO(data)) as image:
        if image.mode not in (('1', 'L') if mask else ('RGB',)):
            raise ValueError('mask must be L/1 or image must be RGB; preprocess explicitly')
        return image.copy()


def evaluate_manifest(manifest):
    """Return deterministic diagnostics and complete input provenance; read only."""
    from identity_quality import compare_images
    validate_manifest(manifest)
    cases = []
    for case in manifest['cases']:
        baseline = _read_image(case['baseline'])
        masks = {key: _read_image(record, mask=True) for key, record in case.get('masks', {}).items()}
        variants = []
        for variant in case['variants']:
            diagnostics = compare_images(baseline, _read_image(variant),
                edit_mask=masks.get('edit'), protected_mask=masks.get('protected'),
                baseline_label=case['baseline'].get('label', 'baseline'), candidate_label=variant['id'])
            variants.append({'id': variant['id'], 'diagnostics': diagnostics})
        cases.append({'id': case['id'], 'route': case['route'], 'variants': variants})
    return {'schemaVersion': 1, 'kind': 'dream-pixel-diagnostics',
            'manifestSha256': canonical_hash(manifest), 'manifest': copy.deepcopy(manifest), 'cases': cases}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new_json(path, value):
    """Never overwrite a source, manifest or previous report."""
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['freeze', 'evaluate'])
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = read_json(args.input)
        result = (freeze_manifest(value, base_dir=args.input.resolve().parent)
                  if args.command == 'freeze' else evaluate_manifest(value))
        write_new_json(args.output, result)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, f'{exc}\n')
    print(str(args.output.resolve()))


if __name__ == '__main__':
    main()
