from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Iterable

import yaml


_FRONTMATTER_DELIMITER = "---"
_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class OkfError(ValueError):
    """Raised when an OKF v0.2 document violates a hard conformance rule."""


@dataclass(frozen=True)
class OkfDocument:
    concept_id: str
    path: Path
    frontmatter: dict[str, Any]
    body: str
    is_reserved: bool = False

    @property
    def type(self) -> str | None:
        value = self.frontmatter.get("type")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def sources(self) -> tuple[dict[str, Any], ...]:
        raw = self.frontmatter.get("sources") or []
        if isinstance(raw, dict):
            raw = [raw]
        return tuple(item for item in raw if isinstance(item, dict))

    @property
    def verified(self) -> tuple[dict[str, Any], ...]:
        raw = self.frontmatter.get("verified")
        if raw is None:
            return ()
        if isinstance(raw, dict):
            return (raw,)
        if isinstance(raw, list):
            return tuple(item for item in raw if isinstance(item, dict))
        return ()

    @property
    def trust_tier(self) -> str:
        events = self.verified
        if not events:
            return "unverified"
        if any(str(item.get("by", "")).startswith("human:") for item in events):
            return "human-reviewed"
        return "machine-confirmed"

    def is_stale(self, now: datetime | None = None) -> bool:
        raw = self.frontmatter.get("stale_after")
        if raw is None:
            return False
        if isinstance(raw, datetime):
            stale_after = raw
        elif isinstance(raw, str):
            stale_after = _parse_datetime(raw)
        else:
            raise OkfError(f"{self.concept_id}: stale_after must be an ISO-8601 datetime")
        if stale_after.tzinfo is None:
            raise OkfError(f"{self.concept_id}: stale_after must contain an explicit UTC offset")
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return reference >= stale_after

    @property
    def internal_links(self) -> tuple[str, ...]:
        links: list[str] = []
        for match in _LINK_RE.finditer(self.body):
            target = match.group(1).split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if target.endswith(".md") or target.endswith("/"):
                links.append(target)
        return tuple(links)

    @property
    def is_attested_computation(self) -> bool:
        return self.type == "Attested Computation"


@dataclass(frozen=True)
class OkfBundle:
    root: Path
    documents: tuple[OkfDocument, ...]

    @property
    def concepts(self) -> tuple[OkfDocument, ...]:
        return tuple(doc for doc in self.documents if not doc.is_reserved)

    @property
    def indexes(self) -> tuple[OkfDocument, ...]:
        return tuple(doc for doc in self.documents if doc.path.name == "index.md")

    def by_id(self, concept_id: str) -> OkfDocument:
        for doc in self.concepts:
            if doc.concept_id == concept_id:
                return doc
        raise KeyError(concept_id)


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise OkfError(f"invalid ISO-8601 datetime: {value}") from exc
    return parsed


def _split_frontmatter(text: str, *, allow_missing: bool) -> tuple[dict[str, Any], str]:
    normalized = text.replace("\r\n", "\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        if allow_missing:
            return {}, normalized
        raise OkfError("concept document must begin with YAML frontmatter")

    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_DELIMITER:
            end = idx
            break
    if end is None:
        raise OkfError("frontmatter is missing closing delimiter")

    raw = "\n".join(lines[1:end])
    loaded = yaml.safe_load(raw) if raw.strip() else {}
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise OkfError("frontmatter must be a YAML mapping")
    body = "\n".join(lines[end + 1 :])
    if normalized.endswith("\n"):
        body += "\n"
    return dict(loaded), body


def parse_document(path: Path, root: Path) -> OkfDocument:
    path = Path(path)
    root = Path(root)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise OkfError(f"{path} is outside bundle root {root}") from exc

    reserved = path.name in {"index.md", "log.md"}
    text = path.read_text(encoding="utf-8")
    # Reserved docs normally have no frontmatter. A root index may declare okf_version.
    frontmatter, body = _split_frontmatter(text, allow_missing=reserved)

    concept_id = relative[:-3] if relative.endswith(".md") else relative
    if reserved:
        if path.name == "log.md" and frontmatter:
            raise OkfError(f"{relative}: log.md must not contain frontmatter")
        if path.name == "index.md" and path.parent != root and frontmatter:
            raise OkfError(f"{relative}: only the bundle-root index.md may contain frontmatter")
        if path.name == "index.md" and frontmatter:
            unknown = set(frontmatter) - {"okf_version"}
            if unknown:
                raise OkfError(
                    f"{relative}: root index frontmatter supports only okf_version; got {sorted(unknown)}"
                )
        return OkfDocument(concept_id, path, frontmatter, body, is_reserved=True)

    type_value = frontmatter.get("type")
    if not isinstance(type_value, str) or not type_value.strip():
        raise OkfError(f"{relative}: non-reserved concept requires a non-empty type")
    return OkfDocument(concept_id, path, frontmatter, body, is_reserved=False)


def load_bundle(root: Path) -> OkfBundle:
    root = Path(root)
    if not root.is_dir():
        raise OkfError(f"bundle root does not exist: {root}")
    docs = tuple(
        parse_document(path, root)
        for path in sorted(root.rglob("*.md"), key=lambda p: p.as_posix())
    )
    return OkfBundle(root=root, documents=docs)


def iter_progressive_entries(index: OkfDocument) -> Iterable[tuple[str, str]]:
    if index.path.name != "index.md":
        raise ValueError("progressive entries can only be read from index.md")
    for match in _LINK_RE.finditer(index.body):
        label_match = re.search(r"\[([^\]]+)\]\([^)]+\)", match.group(0))
        if label_match:
            yield label_match.group(1), match.group(1)
