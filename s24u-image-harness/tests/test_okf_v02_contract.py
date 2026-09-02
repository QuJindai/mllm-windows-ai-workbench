from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from okf.okf_v02 import OkfError, iter_progressive_entries, load_bundle


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_required_type_and_unknown_extensions_are_preserved(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "metrics/revenue.md",
        """---
type: Metric
title: Revenue
x-enterprise-signal:
  owner: plant-a
---
# Definition
Revenue definition.
""",
    )
    doc = load_bundle(tmp_path).by_id("metrics/revenue")
    assert doc.type == "Metric"
    assert doc.frontmatter["x-enterprise-signal"]["owner"] == "plant-a"


def test_missing_type_is_hard_conformance_error(tmp_path: Path) -> None:
    _write(tmp_path, "broken.md", "---\ntitle: Broken\n---\nbody\n")
    with pytest.raises(OkfError, match="non-empty type"):
        load_bundle(tmp_path)


def test_verified_mapping_normalizes_and_derives_human_trust(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "policy.md",
        """---
type: Policy
verified: { by: human:reviewer, at: 2026-09-01T00:00:00Z }
---
Current policy.
""",
    )
    doc = load_bundle(tmp_path).by_id("policy")
    assert len(doc.verified) == 1
    assert doc.trust_tier == "human-reviewed"


def test_machine_confirmed_and_unverified_tiers(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "machine.md",
        """---
type: Reference
verified:
  - { by: process:nightly, at: 2026-09-01T00:00:00Z }
---
Machine checked.
""",
    )
    _write(tmp_path, "plain.md", "---\ntype: Reference\n---\nPlain.\n")
    bundle = load_bundle(tmp_path)
    assert bundle.by_id("machine").trust_tier == "machine-confirmed"
    assert bundle.by_id("plain").trust_tier == "unverified"


def test_stale_after_uses_absolute_offset_aware_instant(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "freshness.md",
        """---
type: Reference
stale_after: 2026-09-02T12:00:00Z
---
Freshness test.
""",
    )
    doc = load_bundle(tmp_path).by_id("freshness")
    assert not doc.is_stale(datetime(2026, 9, 2, 11, 59, tzinfo=timezone.utc))
    assert doc.is_stale(datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc))


def test_sources_links_and_attested_computation_metadata_are_observable(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "computations/revenue.md",
        """---
type: Attested Computation
runtime: bigquery
parameters:
  - { name: year, type: integer, required: true }
executor:
  resource: ../references/run.md
  receipt: [job_id, executed_sql, result]
attester:
  resource: ../references/attest.py
sources:
  - id: revenue-policy
    resource: https://example.invalid/policy
---
# Computation
See [metric](../metrics/revenue.md).
""",
    )
    doc = load_bundle(tmp_path).by_id("computations/revenue")
    assert doc.is_attested_computation
    assert doc.frontmatter["runtime"] == "bigquery"
    assert doc.sources[0]["id"] == "revenue-policy"
    assert doc.internal_links == ("../metrics/revenue.md",)


def test_root_index_supports_okf_version_and_progressive_disclosure(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "index.md",
        """---
okf_version: "0.2"
---
# Metrics
* [Revenue](metrics/revenue.md) - revenue definition
* [Computations](computations/) - sanctioned computations
""",
    )
    _write(tmp_path, "metrics/revenue.md", "---\ntype: Metric\n---\nRevenue.\n")
    bundle = load_bundle(tmp_path)
    index = bundle.indexes[0]
    assert index.frontmatter["okf_version"] == "0.2"
    assert list(iter_progressive_entries(index)) == [
        ("Revenue", "metrics/revenue.md"),
        ("Computations", "computations/"),
    ]


def test_non_root_index_frontmatter_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "nested/index.md", "---\nokf_version: \"0.2\"\n---\n# Nested\n")
    with pytest.raises(OkfError, match="only the bundle-root index"):
        load_bundle(tmp_path)
