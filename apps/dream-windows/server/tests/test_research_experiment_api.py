from fastapi.testclient import TestClient

from app import create_app
from test_generation_jobs import make_config
from test_research_comparison import trace
from test_research_fusion import prediction_artifact


class ReadOnlyRuntime:
    def runtime_trace(self, run_id):
        return trace(run_id, 1. if run_id == 'run-a' else 5.)


def client(tmp_path):
    return TestClient(create_app(make_config(tmp_path), ReadOnlyRuntime()))


def test_capability_and_cpu_replay_are_usable_without_a_generation_engine(tmp_path):
    api = client(tmp_path)
    capability = api.get('/api/research/fusion/capability')
    assert capability.status_code == 200
    assert capability.json()['nativeGenerationAvailable'] is False
    response = api.post('/api/research/fusion/replay', json=prediction_artifact())
    assert response.status_code == 200
    assert response.json()['variants'][1]['prediction'] == [6.5, 9.5]


def test_cross_run_endpoint_resolves_fixed_record_ids_and_returns_derived_values(tmp_path):
    api = client(tmp_path)
    response = api.get('/api/research/comparison', params={'left': 'run-a', 'right': 'run-b'})
    assert response.status_code == 200
    assert response.json()['rows'][0]['delta'] == 4.
    invalid = api.get('/api/research/comparison', params={'left': 'latest', 'right': 'run-b'})
    assert invalid.status_code == 422


def test_replay_rejects_duplicate_keys_missing_tensors_and_oversized_body(tmp_path):
    api = client(tmp_path)
    assert api.post('/api/research/fusion/replay', content='{"cfg":1,"cfg":2}').status_code == 422
    assert api.post('/api/research/fusion/replay', json={'meanAbs': 2, 'l2': 4}).status_code == 422
    assert api.post('/api/research/fusion/replay', content=b' ' * (12*1024*1024+1)).status_code == 413
