import json
from pathlib import Path

import pytest

from zcli.artifacts import ArtifactStore
from zcli.context import ContextManager
from zcli.memory import MemoryStore
from zcli.session import SessionStore
from zcli.tools import ToolRegistry


def test_large_output_is_complete_and_chunk_read_can_reconstruct_it(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data", persist_threshold=10)
    output = "HEAD\n" + ("x" * 250_000) + "\nneedle\n" + ("y" * 250_000) + "\nTAIL"

    metadata, reference = store.persist("session-a", "tool-1", "bash", output)

    assert metadata.chars == len(output)
    assert "HEAD" in reference
    assert "TAIL" in reference
    assert (tmp_path / "data" / "artifacts" / "session-a" / metadata.artifact_id / "content.txt").read_text(
        encoding="utf-8"
    ) == output

    parts = []
    offset = 0
    while True:
        response = store.read_chunk("session-a", metadata.artifact_id, offset=offset, limit=50_000)
        header_text, content = response.split("\n\n", 1)
        header = json.loads(header_text)
        parts.append(content)
        assert len(content) <= 20_000
        if not header["has_more"]:
            break
        offset = header["next_offset"]

    assert "".join(parts) == output


def test_artifact_inspect_and_search_return_bounded_evidence(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data", persist_threshold=10)
    output = "start\nbefore\nERROR database timeout\nafter\nend"
    metadata, _ = store.persist("session-a", "tool-1", "bash", output)

    inspected = json.loads(store.inspect("session-a", metadata.artifact_id))
    searched = store.search(
        "session-a",
        metadata.artifact_id,
        r"ERROR\s+database",
        regex=True,
        context_lines=1,
    )

    assert inspected["chars"] == len(output)
    assert inspected["source_tool"] == "bash"
    assert inspected["head_preview"].startswith("start")
    assert "Match at line 3" in searched
    assert "before" in searched
    assert "after" in searched


def test_artifacts_are_visible_only_to_the_owning_session(tmp_path: Path):
    data_dir = tmp_path / "external-data"
    store = ArtifactStore(data_dir, persist_threshold=10)
    metadata, _ = store.persist("session-a", "tool-1", "read_file", "secret" * 100)
    sessions = SessionStore(data_dir)
    session_a = sessions.create("session-a")
    session_b = sessions.create("session-b")
    tools = ToolRegistry(
        tmp_path,
        MemoryStore(data_dir),
        interactive=False,
        artifacts=store,
    )

    assert metadata.artifact_id in tools.execute(
        "inspect_artifact",
        {"artifact_id": metadata.artifact_id},
        session=session_a,
    )
    denied = tools.execute(
        "inspect_artifact",
        {"artifact_id": metadata.artifact_id},
        session=session_b,
    )
    assert denied == "Error: FileNotFoundError: artifact not found in current session"
    assert tools.execute(
        "inspect_artifact",
        {"artifact_id": metadata.artifact_id},
    ) == "Error: artifact access requires an active session"


def test_invalid_artifact_ids_cannot_escape_session_directory(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")

    with pytest.raises(ValueError, match="invalid artifact id"):
        store.inspect("session-a", "../session-b/artifact_deadbeef")


def test_context_budget_persists_selected_result_in_current_session(tmp_path: Path):
    store = ArtifactStore(tmp_path / "data")
    manager = ContextManager(
        tmp_path / "data",
        50_000,
        tool_result_budget_bytes=30_000,
        artifacts=store,
    )
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "small", "name": "bash", "input": {}},
                {"type": "tool_use", "id": "large", "name": "read_file", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "small", "content": "s" * 20_000},
                {"type": "tool_result", "tool_use_id": "large", "content": "L" * 20_000},
            ],
        },
    ]

    manager.tool_result_budget(messages, session_id="session-a")

    contents = [block["content"] for block in messages[-1]["content"]]
    assert any("<artifact-result>" in content for content in contents)
    artifact_dirs = list((tmp_path / "data" / "artifacts" / "session-a").glob("artifact_*"))
    assert len(artifact_dirs) == 1


def test_read_file_no_longer_truncates_before_artifact_processing(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    content = "z" * 75_000
    (workspace / "large.txt").write_text(content, encoding="utf-8")
    tools = ToolRegistry(workspace, MemoryStore(tmp_path / "data"), interactive=False)

    assert tools.read_file("large.txt") == content
