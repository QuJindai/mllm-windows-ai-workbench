from __future__ import annotations

import math


MIN_CUDA_BUDGET_GB = 3.0
DEFAULT_RESERVE_MIB = 1024
DEFAULT_OVERHEAD_MIB = 512


def safe_cuda_budget_gb(
    total_vram_mib: int,
    other_vram_mib: int = 0,
    reserve_mib: int = DEFAULT_RESERVE_MIB,
    overhead_mib: int = DEFAULT_OVERHEAD_MIB,
) -> float:
    """Return a conservative native CUDA budget while preserving desktop headroom."""
    total = max(0, int(total_vram_mib))
    other = max(0, int(other_vram_mib))
    reserve = max(0, int(reserve_mib))
    overhead = max(0, int(overhead_mib))
    available_mib = total - other - reserve - overhead
    if available_mib <= 0:
        return MIN_CUDA_BUDGET_GB
    budget = math.floor((available_mib / 1024) * 10) / 10
    return max(MIN_CUDA_BUDGET_GB, round(budget, 1))
