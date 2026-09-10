from vram_policy import safe_cuda_budget_gb


def test_reserves_browser_headroom_for_six_gigabyte_gpu():
    assert safe_cuda_budget_gb(6141) == 4.4


def test_accounts_for_other_gpu_usage_and_keeps_a_safe_floor():
    assert safe_cuda_budget_gb(6141, other_vram_mib=700) == 3.8
    assert safe_cuda_budget_gb(6141, other_vram_mib=5000) == 3.0
