import copy
import importlib
import importlib.util
import math

import pytest


def fusion_module():
    assert importlib.util.find_spec('research_fusion'), 'CPU prediction fusion has not been implemented'
    return importlib.import_module('research_fusion')


def prediction_artifact():
    return {
        'contractVersion': 'mobile-chunk-predictions-v1', 'predictionType': 'epsilon',
        'family': 'sdxl', 'shape': [2], 'cfg': 2., 'canSkipUncond': True, 'alpha': .25,
        'provenance': {'runId': 'phone-run-1', 'modelId': 'test-model', 'modelSha256': 'a' * 64,
                       'engine': 'android-qnn', 'engineRevision': 'test-build', 'step': 0,
                       'timestep': 999., 'latentSha256': 'b' * 64, 'promptSha256': 'c' * 64,
                       'negativePromptSha256': 'd' * 64, 'seed': 42, 'capturedAt': '2026-10-29T00:00:00Z'},
        'chunks': [
            {'index': 0, 'positiveTokens': 3, 'negativeTokens': 1, 'positive': [2., 4.], 'negative': [1., 2.]},
            {'index': 1, 'positiveTokens': 1, 'negativeTokens': 1, 'positive': [6., 8.], 'negative': [2., 3.]},
        ],
    }


def test_mobile_cfg_then_fusion_matches_hand_computed_predictions():
    result = fusion_module().replay_fusion(prediction_artifact())
    variants = {item['mode']: item for item in result['variants']}
    assert variants['first_only']['prediction'] == [3., 6.]
    assert variants['equal_mean']['prediction'] == [6.5, 9.5]
    assert variants['token_weighted']['prediction'] == [4.75, 7.75]
    assert variants['anchor_residual']['prediction'] == [4.75, 7.75]
    assert variants['anchor_residual']['weights'] == [.75, .25]
    assert variants['first_only']['deltaL2FromEqualMean'] == pytest.approx(math.sqrt(24.5))
    assert result['truth'] == 'derived'
    assert result['provenance']['inputVerification'] == 'imported-unverified'
    assert len(result['provenance']['inputSha256']) == 64


def test_cfg_one_skips_negative_only_when_backend_supports_it():
    data = prediction_artifact()
    data['cfg'] = 1.
    data['chunks'][1]['negativeTokens'] = 9
    for chunk in data['chunks']:
        del chunk['negative']
    result = fusion_module().replay_fusion(data)
    assert result['variants'][2]['weights'] == [.75, .25]
    assert result['variants'][2]['prediction'] == [3., 5.]
    data['canSkipUncond'] = False
    with pytest.raises(ValueError, match='negative'):
        fusion_module().replay_fusion(data)


def test_guided_weights_use_max_paired_count_and_anchor_excludes_first_count():
    data = prediction_artifact()
    data['chunks'][1]['negativeTokens'] = 9
    data['chunks'].append({'index': 2, 'positiveTokens': 3, 'negativeTokens': 1,
                           'positive': [10., 12.], 'negative': [0., 0.]})
    variants = fusion_module().replay_fusion(data)['variants']
    assert variants[2]['weights'] == pytest.approx([.2, .6, .2])
    assert variants[3]['weights'] == pytest.approx([.75, .1875, .0625])
    assert variants[3]['prediction'] == pytest.approx([5.375, 8.4375])


def test_single_chunk_and_zero_norm_have_no_fabricated_cosine():
    data = prediction_artifact()
    data['chunks'] = [dict(data['chunks'][0], positive=[0., 0.], negative=[0., 0.])]
    result = fusion_module().replay_fusion(data)
    assert all(v['weights'] == [1.] and v['prediction'] == [0., 0.] for v in result['variants'])
    assert all(v['cosineToEqualMean'] is None for v in result['variants'])


@pytest.mark.parametrize('mutation', [
    lambda d: d.pop('provenance'),
    lambda d: d['provenance'].pop('latentSha256'),
    lambda d: d.update(predictionType='v_prediction'),
    lambda d: d.update(family='anima'),
    lambda d: d.update(shape=[128, 128, 128]),
    lambda d: d.update(chunks=d['chunks'] * 3),
    lambda d: d['chunks'][0].update(positive=[float('nan'), 1]),
    lambda d: d['chunks'][0].update(negative=[1]),
    lambda d: d['chunks'][0].update(positiveTokens=76),
    lambda d: d['chunks'][0].update(positiveTokens=True),
    lambda d: d['chunks'][1].update(index=0),
    lambda d: d.update(alpha=1.01),
    lambda d: d.update(cfg=float('inf')),
])
def test_missing_incompatible_or_unbounded_inputs_are_rejected(mutation):
    data = copy.deepcopy(prediction_artifact())
    mutation(data)
    with pytest.raises(ValueError):
        fusion_module().replay_fusion(data)
