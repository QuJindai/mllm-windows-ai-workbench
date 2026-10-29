"""Fail-closed descriptive comparison of recorded latent statistics.

Matching model IDs are NOT proof of identical weights, seeds or prompts. No
quality, identity similarity, performance or controlled-causality claims.
"""
from __future__ import annotations

from research_fusion import digest, finite, require

COMPATIBILITY = ('modelId', 'backend', 'samplingMethod', 'scheduler', 'steps', 'cfg')
METRICS = ('mean', 'std', 'l2')


def _record(trace):
    require(isinstance(trace, dict) and trace.get('available') is True and trace.get('truth') == 'observed',
            '运行记录缺失或不是实测记录')
    run_id = trace.get('runId')
    require(isinstance(run_id, str) and run_id and run_id != 'latest', '缺少固定运行 ID')
    evidence = trace.get('evidence')
    require(isinstance(evidence, dict) and evidence.get('truth') == 'observed'
            and evidence.get('backendTruth') == 'observed', '缺少实测来源')
    for name in COMPATIBILITY[:4]:
        require(isinstance(evidence.get(name), str) and evidence[name].strip(), f'缺少来源字段 {name}')
    require(type(evidence.get('steps')) is int and 1 <= evidence['steps'] <= 50, '来源 steps 无效')
    require(finite(evidence.get('cfg'), 0, 30), '来源 cfg 无效')
    samples = trace.get('latentTelemetry')
    require(isinstance(samples, list) and 1 <= len(samples) <= 51, '缺少潜变量实测指标')
    indexed = {}
    for sample in samples:
        require(isinstance(sample, dict) and sample.get('truth') == 'observed'
                and sample.get('kind') == 'latent-state', '指标来源不是实测 latent-state')
        step = sample.get('step')
        require(type(step) is int and 0 <= step <= evidence['steps'] and step not in indexed,
                '采集步号无效或重复')
        shape = sample.get('shape')
        require(isinstance(shape, list) and 2 <= len(shape) <= 4
                and all(type(v) is int and 1 <= v <= 4096 for v in shape), '缺少有效 tensor shape')
        for name in METRICS:
            require(finite(sample.get(name), -1e100 if name == 'mean' else 0, 1e100), f'缺少有效指标 {name}')
        indexed[step] = {name: sample[name] for name in (*METRICS, 'shape')}
    provenance = {'runId': run_id, **{key: evidence[key] for key in COMPATIBILITY},
                  'recordSha256': digest({'runId': run_id, 'evidence': evidence, 'samples': indexed}),
                  'source': f'/api/traces/{run_id}', 'metricSource': 'latentTelemetry', 'truth': 'observed'}
    return indexed, provenance


def compare_latent_runs(left, right):
    a, pa = _record(left)
    b, pb = _record(right)
    require(pa['runId'] != pb['runId'], '必须选择两个不同运行')
    for field in COMPATIBILITY:
        require(pa[field] == pb[field], f'运行不兼容：{field} 不一致')
    require(a.keys() == b.keys(), '采集覆盖不一致：不截取交集、不填补缺失值')
    rows = []
    for step in sorted(a):
        require(a[step]['shape'] == b[step]['shape'], f'运行不兼容：第 {step} 个采集步 shape 不一致')
        for metric in METRICS:
            rows.append({'step': step, 'metric': metric, 'left': a[step][metric],
                         'right': b[step][metric], 'delta': b[step][metric] - a[step][metric]})
    return {'contractVersion': 'latent-run-comparison-v1', 'truth': 'derived',
            'scope': 'descriptive-recorded-latent-statistics', 'rows': rows,
            'coverage': {'capturedSteps': sorted(a), 'capturedCount': len(a), 'configuredSteps': pa['steps']},
            'provenance': {'left': pa, 'right': pb},
            'limitations': '记录统计对照；未核验同一权重、随机种子或提示词，不代表相似度、画质或因果效果。'}
