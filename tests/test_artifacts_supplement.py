"""Supplemental tests for zcli.artifacts — read_chunk edges, search no matches, metadata mismatch, persist_if_large."""

from __future__ import annotations

from pathlib import Path

import pytest

from zcli.artifacts import ArtifactStore


# ── persist_if_large ────────────────────────────────────────────────────

def test_persist_if_large_below_threshold(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data", persist_threshold=100)

    result = store.persist_if_large("session-a", "tool-1", "bash", "short output")

    assert result == "short output"


def test_persist_if_large_above_threshold(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data", persist_threshold=10)

    result = store.persist_if_large("session-a", "tool-1", "bash", "long enough output")

    assert "<artifact-result>" in result
    assert "Artifact ID" in result


def test_persist_if_large_already_artifact_result(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data", persist_threshold=10)

    existing = "<artifact-result>\nArtifact ID: existing-id\n</artifact-result>"
    result = store.persist_if_large("session-a", "tool-1", "bash", existing)

    assert result == existing


# ── _validate_session_id ────────────────────────────────────────────────

def test_validate_session_id_invalid():
    with pytest.raises(ValueError, match="invalid session id"):
        ArtifactStore._validate_session_id("../escape")


def test_validate_session_id_valid():
    assert ArtifactStore._validate_session_id("session-abc") == "session-abc"
    assert ArtifactStore._validate_session_id("A" * 80) == "A" * 80


# ── _validate_artifact_id ────────────────────────────────────────────────

def test_validate_artifact_id_invalid():
    with pytest.raises(ValueError, match="invalid artifact id"):
        ArtifactStore._validate_artifact_id("bad-id")

    with pytest.raises(ValueError, match="invalid artifact id"):
        ArtifactStore._validate_artifact_id("../escape")


def test_validate_artifact_id_valid():
    artifact_id = "artifact_" + "a" * 20
    assert ArtifactStore._validate_artifact_id(artifact_id) == artifact_id


# ── read_chunk edges ─────────────────────────────────────────────────────

def test_read_chunk_negative_offset(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")
    metadata, _ = store.persist("session-a", "tool-1", "bash", "hello world")

    with pytest.raises(ValueError, match="non-negative"):
        store.read_chunk("session-a", metadata.artifact_id, offset=-1)


def test_read_chunk_zero_limit(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")
    metadata, _ = store.persist("session-a", "tool-1", "bash", "hello world")

    with pytest.raises(ValueError, match="positive"):
        store.read_chunk("session-a", metadata.artifact_id, limit=0)


def test_read_chunk_offset_beyond_content(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")
    metadata, _ = store.persist("session-a", "tool-1", "bash", "hello")

    result = store.read_chunk("session-a", metadata.artifact_id, offset=100)

    # Should return empty content but valid header
    assert "offset" in result
    assert "has_more" in result


# ── search edges ─────────────────────────────────────────────────────────

def test_search_empty_query(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")
    metadata, _ = store.persist("session-a", "tool-1", "bash", "content")

    with pytest.raises(ValueError, match="query must not be empty"):
        store.search("session-a", metadata.artifact_id, "")


def test_search_no_matches(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")
    metadata, _ = store.persist("session-a", "tool-1", "bash", "hello world")

    result = store.search("session-a", metadata.artifact_id, "nonexistent")

    assert "No matches" in result


def test_search_context_lines_clamped(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")
    metadata, _ = store.persist("session-a", "tool-1", "bash", "line1\nneedle\nline3")

    # context_lines=100 should be clamped to 50
    result = store.search("session-a", metadata.artifact_id, "needle", context_lines=100)

    assert "needle" in result


def test_search_max_matches_clamped(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")
    lines = "\n".join(f"line{i} needle" for i in range(200))
    metadata, _ = store.persist("session-a", "tool-1", "bash", lines)

    # max_matches=200 should be clamped to 100
    result = store.search("session-a", metadata.artifact_id, "needle", max_matches=200)

    match_count = result.count("Match at line")
    assert match_count <= 100


# ── _load_metadata mismatch ──────────────────────────────────────────────

def test_load_metadata_session_mismatch(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")
    meta, _ = store.persist("session-a", "tool-1", "bash", "content")

    # Create a metadata file that references a different session
    path = store._metadata_path("session-a", meta.artifact_id)
    import json
    from dataclasses import asdict
    current = json.loads(path.read_text(encoding="utf-8"))
    current["session_id"] = "session-b"
    path.write_text(json.dumps(current), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        store._load_metadata("session-a", meta.artifact_id)


def test_load_metadata_not_found(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")

    with pytest.raises(FileNotFoundError, match="not found"):
        store._load_metadata("session-a", "artifact_" + "a" * 20)
