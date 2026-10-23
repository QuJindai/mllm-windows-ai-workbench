import pytest
from errors import DreamApiError
from models import GenerateRequest
from runtime import DreamRuntime
from research_fixtures import install_research_engine
from test_generation_jobs import make_config


@pytest.mark.parametrize("level", ["h6", "h7"])
def test_oversized_research_is_rejected_before_native_generation(tmp_path, level):
    config = make_config(tmp_path)
    install_research_engine(config)
    class NoSubmit:
        def submit(self, request):
            pytest.fail("unsupported research size reached native queue")
    runtime = DreamRuntime(config, job_runner=NoSubmit())
    with pytest.raises(DreamApiError) as failure:
        runtime.generate(GenerateRequest(prompt="lake", modelId="model", traceLevel=level, width=1536, height=1024))
    assert failure.value.code == "RESEARCH_RESOLUTION_LIMIT"
    assert failure.value.status_code == 422
