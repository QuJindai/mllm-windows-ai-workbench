"""Summarize observed timing receipts; never launches/stops a worker or GPU job."""
from __future__ import annotations

import argparse
import copy
import math
from pathlib import Path
from statistics import median

from benchmark_dream_quality import canonical_hash, read_json, validate_manifest, write_new_json


PHASES = ('load', 'samplingDecode', 'facePolish', 'save')


def _duration(value, field):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
        raise ValueError(f'{field} must be a finite nonnegative duration or null')


def _stats(values):
    return {'count': len(values), 'median': median(values) if values else None,
            'min': min(values) if values else None, 'max': max(values) if values else None}


def summarize_runs(manifest, runs):
    """Bind explicit cold/warm receipts to frozen cases and group compatible runs.

    Durations are milliseconds, disjoint wall-clock intervals inside wallMs.
    Cold means new worker/pipeline, NOT necessarily cold OS/model-file caches.
    Each run must supply human/instrument temperatureEvidence and environment.
    Omitted/null phases stay unknown. No duration is inferred from progress text.
    """
    validate_manifest(manifest)
    manifest_hash = canonical_hash(manifest)
    canonical_hash(runs)
    if not isinstance(runs, list):
        raise ValueError('runs must be a list')
    bindings = {(case['id'], variant['id']): (case, variant)
                for case in manifest['cases'] for variant in case['variants']}
    seen, normalized, excluded, grouped = set(), [], [], {}
    for original in runs:
        row = copy.deepcopy(original)
        if row.get('manifestSha256') != manifest_hash:
            raise ValueError('run manifestSha256 does not match the frozen dataset')
        for field in ('runId', 'sessionId', 'temperatureEvidence'):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f'{field} is required')
        if row['runId'] in seen:
            raise ValueError('duplicate runId')
        seen.add(row['runId'])
        binding = (row.get('caseId'), row.get('variantId'))
        if binding not in bindings:
            raise ValueError('run is not bound to a manifest case/variant')
        case, variant = bindings[binding]
        if row.get('temperature') not in ('cold', 'warm'):
            raise ValueError('temperature must be explicit cold or warm')
        if row.get('outcome') not in ('complete', 'failed', 'cancelled'):
            raise ValueError('outcome must be explicit complete/failed/cancelled')
        for field in ('environment', 'source'):
            if not isinstance(row.get(field), dict) or not row[field]:
                raise ValueError(f'{field} provenance is required')
        if type(row.get('uncontended')) is not bool:
            raise ValueError('uncontended must be an explicit observation')
        wall = row.get('wallMs')
        _duration(wall, 'wallMs')
        if row['outcome'] == 'complete' and wall is None:
            raise ValueError('complete run requires wallMs')
        phases = row.get('phasesMs', {})
        if not isinstance(phases, dict) or set(phases) - set(PHASES):
            raise ValueError('unknown phase; phases must be disjoint load/samplingDecode/facePolish/save')
        for name, value in phases.items():
            _duration(value, name)
        known_sum = sum(v for v in phases.values() if v is not None)
        if wall is not None and known_sum > wall:
            raise ValueError('phase sum exceeds wallMs; check overlapping or stale load timings')
        # save is optional instrumentation; the three principal phases determine
        # whether unattributed time (including any unmeasured save) is reportable.
        principal_known = all(phases.get(key) is not None for key in PHASES[:3])
        row['timingCoverage'] = {'observedPhaseSumMs': known_sum,
            'missingPhases': [name for name in PHASES if phases.get(name) is None],
            'unattributedMs': wall - known_sum if principal_known and wall is not None else None}
        row['provenance'] = copy.deepcopy(variant)
        row['route'] = case['route']
        normalized.append(row)
        if row['outcome'] != 'complete' or not row['uncontended']:
            excluded.append({'runId': row['runId'], 'reason': 'not complete' if row['outcome'] != 'complete' else 'contended'})
            continue
        key = (*binding, row['temperature'], canonical_hash(row['environment']))
        grouped.setdefault(key, []).append(row)
    groups = []
    for (case_id, variant_id, temperature, environment_hash), rows in sorted(grouped.items()):
        groups.append({'caseId': case_id, 'variantId': variant_id, 'route': rows[0]['route'],
            'temperature': temperature, 'environmentSha256': environment_hash,
            'environment': rows[0]['environment'], 'wallMs': _stats([r['wallMs'] for r in rows]),
            'phasesMs': {name: _stats([r['phasesMs'][name] for r in rows
                                     if r.get('phasesMs', {}).get(name) is not None]) for name in PHASES}})
    return {'schemaVersion': 1, 'kind': 'dream-observed-performance',
            'scope': 'Operator/instrument supplied wall timings; no GPU measurements made by this tool. '
                     'Cold is worker/pipeline initialization, not proof of an empty OS or disk cache. '
                     'Groups retain case, variant, temperature and environment; no universal speed ranking.',
            'manifestSha256': manifest_hash, 'manifest': copy.deepcopy(manifest),
            'runs': normalized, 'groups': groups, 'excludedRuns': excluded}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('receipts', type=Path, help='JSON array of observed runs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = summarize_runs(read_json(args.manifest), read_json(args.receipts))
        write_new_json(args.output, report)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, f'{exc}\n')
    print(str(args.output.resolve()))


if __name__ == '__main__':
    main()
