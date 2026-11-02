from pathlib import Path
import pytest


def test_upscale_missing_config_does_not_advertise_ready(tmp_path):
    from identity_upscale import upscale_status
    assert not upscale_status({})['ready']
    assert not upscale_status({'upscaleModel':str(tmp_path/'missing.pth')})['ready']


def test_enhance_rejects_oversized_source_before_loading_model(monkeypatch):
    from PIL import Image
    from identity_upscale import enhance
    with pytest.raises(ValueError,match='尺寸'):
        enhance({},Image.new('RGB',(1024,1024)),lambda _:None)


def test_tiled_processing_matches_full_context_and_covers_odd_edges():
    import torch
    from identity_upscale import tiled_forward
    # Context-dependent convolution detects missing halo and tile boundary bugs.
    torch.manual_seed(31)
    class Network(torch.nn.Module):
        def forward(self,x):
            smoothed=torch.nn.functional.avg_pool2d(x,3,stride=1,padding=1)
            return torch.nn.functional.interpolate(smoothed,scale_factor=4,mode='nearest')
    model=Network()
    source=torch.rand(1,3,67,83)
    actual,calls=tiled_forward(model,source,scale=4,tile=32,padding=4,device='cpu')
    assert calls==9
    torch.testing.assert_close(actual,model(source),rtol=0,atol=0)


def test_bad_inference_pixels_cannot_publish():
    import torch
    from identity_upscale import tiled_forward
    def broken(x):return torch.full((1,3,x.shape[-2]*4,x.shape[-1]*4),float('nan'))
    with pytest.raises(ValueError,match='数值'):
        tiled_forward(broken,torch.zeros(1,3,12,12),scale=4,tile=32,padding=4,device='cpu')


def test_tile_callback_can_abort_before_the_next_model_call():
    import torch
    from identity_upscale import tiled_forward
    calls=[]
    def model(x):
        calls.append(1)
        return torch.nn.functional.interpolate(x,scale_factor=4,mode='nearest')
    def stage(current,total):
        if current==2:raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):
        tiled_forward(model,torch.ones(1,3,40,40),scale=4,tile=32,padding=4,device='cpu',progress=stage)
    assert len(calls)==1
