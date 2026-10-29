import copy
import importlib
import importlib.util

import pytest


def compare(left, right):
    assert importlib.util.find_spec('research_comparison'), 'Cross-run comparison has not been implemented'
    return importlib.import_module('research_comparison').compare_latent_runs(left, right)


def trace(run_id='run-a', mean=1.):
    return {'available': True, 'truth': 'observed', 'runId': run_id,
            'evidence': {'truth': 'observed', 'modelId': 'model-a', 'backend': 'CUDA',
                         'backendTruth': 'observed', 'steps': 20, 'cfg': 4.,
                         'samplingMethod': 'euler', 'scheduler': 'karras'},
            'latentTelemetry': [{'step': 0, 'shape': [64, 64, 4, 1], 'mean': mean,
                                 'std': 2., 'l2': 3., 'truth': 'observed', 'kind': 'latent-state'}]}


def test_comparison_retains_sample_coverage_and_per_run_provenance():
    result = compare(trace(), trace('run-b', 5.))
    assert result['rows'][0] == {'step': 0, 'metric': 'mean', 'left': 1., 'right': 5., 'delta': 4.}
    assert result['coverage'] == {'capturedSteps': [0], 'capturedCount': 1, 'configuredSteps': 20}
    assert result['provenance']['left']['runId'] == 'run-a'
    assert result['provenance']['right']['runId'] == 'run-b'
    assert result['provenance']['left']['backend'] == 'CUDA'
    assert len(result['provenance']['left']['recordSha256']) == 64
    assert result['scope'] == 'descriptive-recorded-latent-statistics'


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(runId='run-a'),
    lambda d: d.update(available=False),
    lambda d: d.update(truth='demo'),
    lambda d: d['evidence'].pop('backend'),
    lambda d: d['evidence'].update(modelId='other'),
    lambda d: d['evidence'].update(cfg=7),
    lambda d: d['evidence'].update(scheduler='discrete'),
    lambda d: d['latentTelemetry'][0].update(shape=[32, 32, 4, 1]),
    lambda d: d['latentTelemetry'][0].update(step=1),
    lambda d: d['latentTelemetry'][0].pop('mean'),
    lambda d: d['latentTelemetry'][0].update(l2=None),
    lambda d: d['latentTelemetry'][0].update(std=float('nan')),
    lambda d: d['latentTelemetry'].append(copy.deepcopy(d['latentTelemetry'][0])),
    lambda d: d.update(latentTelemetry=[]),
])
def test_missing_incompatible_duplicate_or_demo_data_never_becomes_a_chart(mutation):
    right = trace('run-b')
    mutation(right)
    with pytest.raises(ValueError):
        compare(trace(), right)
