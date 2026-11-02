import pytest
from pydantic import ValidationError
from hq_service import HQParameters
from identity_contract import IdentityGenerateRequest


def identity(**values):
    return IdentityGenerateRequest(referenceId='ref-' + 'a'*24, faceIndex=0,
                                   prompt='full body studio photograph', **values)


@pytest.mark.parametrize('width,height', [(640,960),(768,1152),(1152,768)])
def test_hq_hd_dimensions_reach_existing_identity_contract(width,height):
    parameters=HQParameters(width=width,height=height)
    request=identity(width=parameters.width,height=parameters.height)
    assert (request.width,request.height)==(width,height)


@pytest.mark.parametrize('width,height', [(1024,1024),(1152,1152),(1280,512)])
def test_hq_and_identity_keep_bounded_hd_pixel_budget(width,height):
    for factory in (HQParameters,identity):
        with pytest.raises(ValidationError):factory(width=width,height=height)


def test_other_models_and_research_do_not_inherit_unvalidated_hd_budget():
    with pytest.raises(ValidationError):identity(modelId='illustrious-xl-v2.0-faceid',width=768,height=1152)
    for trace in ('basic','h6','h7'):
        with pytest.raises(ValidationError):identity(width=768,height=1152,traceLevel=trace)


def test_approved_hq_defaults_are_scoped_to_tryon():
    p = HQParameters()
    assert (p.width, p.height, p.steps, p.seed) == (768, 1152, 30, 20261104)
    assert (identity().width, identity().height) == (512, 768)
