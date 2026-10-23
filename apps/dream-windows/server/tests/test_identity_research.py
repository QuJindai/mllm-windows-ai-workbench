"""Contract and real CPU tensor tests; never load user assets or CUDA."""
import json
from pathlib import Path

import pytest


def request(**extra):
    from identity_contract import IdentityGenerateRequest
    return IdentityGenerateRequest(**{'referenceId':'ref-' + 'a' * 24, 'faceIndex':0, 'prompt':'a portrait', **extra})


def test_legacy_request_keeps_research_off_and_rejects_unsafe_extended_request():
    assert request().traceLevel == 'off'
    assert request(traceLevel='h7').researchCoverage == 'representative'
    assert request(traceLevel='h7', researchCoverage='extended', width=512, height=512, steps=8).steps == 8
    with pytest.raises(ValueError):
        request(traceLevel='h7', researchCoverage='extended', width=768, height=768, steps=50)


def test_real_qk_probabilities_are_normalized_and_do_not_mutate_inputs():
    import torch
    from identity_research import attention_probabilities
    q = torch.tensor([[[1., 0.], [0., 1.]]])
    k = torch.tensor([[[1., 0.], [0., 1.]]])
    before = q.clone()
    probabilities = attention_probabilities(q, k, heads=1)
    assert probabilities.shape == (2, 2)
    assert probabilities[0, 0].item() == pytest.approx(.66976155)
    assert probabilities[0, 1].item() == pytest.approx(.33023845)
    assert probabilities.sum(-1).tolist() == pytest.approx([1, 1])
    assert torch.equal(q, before)


def test_identity_intervention_is_not_mislabeled_as_chunk_fusion():
    import torch
    from identity_research import influence_sample
    actual = torch.tensor([[[[1., 1.]]], [[[3., 3.]]]])
    ablated = torch.tensor([[[[1., 1.]]], [[[2., 2.]]]])
    sample = influence_sample(actual, ablated, cfg=2., step=0)
    assert sample['chunks'][0]['spatialDelta'] == [2., 2.]
    assert sample['chunks'][0]['deltaL2'] == pytest.approx(8 ** .5)
    assert sample['cfgDeltaL2'] == pytest.approx(8 ** .5)
    assert sample['width'] == 2 and sample['height'] == 1


def test_latent_statistics_come_from_float_channels_and_preserve_null_variance(tmp_path):
    import torch
    from identity_research import latent_sample
    z = torch.tensor([[[[1., 2.], [3., 4.]], [[4., 3.], [2., 1.]], [[2., 2.], [2., 2.]], [[2., 4.], [6., 8.]]]])
    sample = latent_sample(z, None, 1, tmp_path)
    assert sample['shape'] == [2, 2, 4, 1]
    assert sample['channel_correlation'][0] == pytest.approx([1., -1., None, 1.], nan_ok=True)
    assert sample['channel_correlation'][2] == [None] * 4
    assert sample['channels'][0]['histogram'][0] == 1
    assert len(list(tmp_path.glob('latent-step-001-ch*.png'))) == 4


def test_attention_observer_preserves_real_module_forward_and_removes_hooks(tmp_path):
    import torch
    from types import SimpleNamespace
    from identity_research import IdentityResearch

    class Attention(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.to_q = torch.nn.Linear(4, 4, bias=False)
            self.to_k = torch.nn.Linear(4, 4, bias=False)
            self.to_v = torch.nn.Linear(4, 4, bias=False)
            self.heads = 1
        def forward(self, x, context):
            return torch.nn.functional.scaled_dot_product_attention(self.to_q(x), self.to_k(context), self.to_v(context))

    class UNet(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.down_blocks = torch.nn.ModuleList([torch.nn.Module()])
            self.down_blocks[0].attn2 = Attention()
        def forward(self, sample, timestep, encoder_hidden_states=None, **kwargs):
            return (self.down_blocks[0].attn2(sample, encoder_hidden_states),)

    unet = UNet().eval()
    pipe = SimpleNamespace(unet=unet, tokenizer=None)
    item = {'dreamRoot': str(tmp_path), 'jobId': 'identity-' + 'b' * 24, 'outputPath': str(tmp_path/'out.png')}
    params = request(traceLevel='h7', width=256, height=256, steps=1)
    x, context = torch.ones(2, 4, 4), torch.arange(24.).reshape(2, 3, 4) / 10
    before = unet(x, 1, encoder_hidden_states=context)[0]
    with IdentityResearch(pipe, item, params) as collector:
        # This shape-only fixture exercises Q/K capture, not H6 intervention.
        collector.tokens = [{'slot': i, 'tokenId': i, 'text': str(i), 'chunk': 0, 'weight': 1.} for i in range(3)]
        collector.capture_influence = False
        during = unet(x, 1, encoder_hidden_states=context)[0]
    assert torch.equal(before, during)
    assert not unet._forward_hooks and not unet.down_blocks[0].attn2.to_q._forward_hooks
    index = json.loads((tmp_path/'traces'/item['jobId']/'attention-index.json').read_text())
    assert index['source'] == 'diffusers-unet'
    assert len(index['maps']) == 3
    assert len(list((tmp_path/'traces'/item['jobId']).glob('attention-*.json'))) == 4


def test_disabled_collector_does_not_create_artifacts_or_register_hooks(tmp_path):
    from types import SimpleNamespace
    from identity_research import IdentityResearch
    with IdentityResearch(SimpleNamespace(), {'dreamRoot': str(tmp_path), 'jobId': 'identity-'+'c'*24}, request()) as collector:
        assert not collector.enabled
    assert not (tmp_path/'traces').exists()


def test_sampling_callback_passes_the_actual_latent_without_replacing_it(tmp_path):
    from identity_pipeline import sampling_callback
    captured = []
    class Collector:
        def on_step(self, latent, step):
            captured.append((latent, step))
    value = object()
    values = {'latents': value}
    callback = sampling_callback('identity-'+'a'*24, 0, 28, lambda e: None, tmp_path, 0, 0, research=Collector())
    assert callback(None, 4, 900, values) is values
    assert captured == [(value, 4)]  # same zero-based trace index as H6/H7/native


def test_artifact_preflight_rejects_large_accepted_shape_before_model_load():
    with pytest.raises(ValueError, match='512MiB'):
        request(traceLevel='h7', researchCoverage='extended', width=512, height=512, steps=12, prompt='portrait ' * 150)
    assert request(traceLevel='h7', researchCoverage='extended', width=512, height=512, steps=8).steps == 8


def test_secure_writer_does_not_follow_predictable_temporary_or_png_links(tmp_path):
    from identity_research import write_artifact
    outside = tmp_path/'outside'
    outside.write_bytes(b'preserve')
    root = tmp_path/'research'
    root.mkdir()
    try:
        (root/'map.tmp').symlink_to(outside)
        (root/'frame.png').symlink_to(outside)
    except OSError:
        pytest.skip('symlink privilege unavailable')
    write_artifact(root, root/'map.json', b'{}')
    assert outside.read_bytes() == b'preserve'
    with pytest.raises(ValueError):
        write_artifact(root, root/'frame.png', b'png')
    assert outside.read_bytes() == b'preserve'
    assert (root/'map.json').read_bytes() == b'{}'


def test_latent_png_bytes_are_budgeted(tmp_path):
    import torch
    from identity_research import latent_sample
    recorded = []
    latent_sample(torch.arange(16.).reshape(1,4,2,2), None, 1, tmp_path,
                  writer=lambda name, data: recorded.append((name, data)))
    assert len(recorded) == 4
    assert all(data.startswith(b'\x89PNG') for _,data in recorded)


def test_delta_image_uses_channel_mean_absolute_original_float_difference(tmp_path):
    import torch
    from PIL import Image
    from identity_research import latent_sample
    old = torch.zeros(1,4,1,3)
    z = torch.tensor([[[[0.,1.,2.]],[[0.,3.,6.]],[[0.,1.,2.]],[[0.,3.,6.]]]])
    sample = latent_sample(z, old, 1, tmp_path)
    assert sample['delta_mean_abs'] == 2.
    assert sample['delta_file_name'] == 'latent-step-001-delta.png'
    assert list(Image.open(tmp_path/sample['delta_file_name']).getdata()) == [0,127,255]
    assert 'delta_file_name' not in latent_sample(z, None, 0, tmp_path)
