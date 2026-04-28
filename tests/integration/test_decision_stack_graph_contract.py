from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, transact, validate_runtime
from tests.helpers.typed_metadata import evidence_metadata


class DecisionStackGraphContractTests(unittest.TestCase):
    def test_validate_state_rejects_unknown_object_layer(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            project_state = _load_project_state(ai_dir)
            project_state["objects"][0]["metadata"]["layer"] = "unknown"
            _write_project_state_and_refresh_index(ai_dir, project_state)

            issues = validate_runtime(ai_dir, full=False)

            self.assertTrue(any("metadata.layer" in issue for issue in issues))

    def test_validate_state_rejects_graph_node_referencing_missing_object(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            project_state = _load_project_state(ai_dir)
            project_state["graph"]["nodes"][0]["object_id"] = "O-missing"
            _write_project_state_and_refresh_index(ai_dir, project_state)

            issues = validate_runtime(ai_dir, full=False)

            self.assertTrue(any("graph node O-missing references missing object" in issue for issue in issues))

    def test_validate_state_rejects_graph_edge_referencing_missing_link(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _runtime_with_link(Path(tmp))
            project_state = _load_project_state(ai_dir)
            project_state["graph"]["edges"][0]["link_id"] = "L-missing"
            _write_project_state_and_refresh_index(ai_dir, project_state)

            issues = validate_runtime(ai_dir, full=False)

            self.assertTrue(any("graph edge L-missing references missing link" in issue for issue in issues))

    def test_validate_state_rejects_graph_edge_endpoint_referencing_missing_object(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _runtime_with_link(Path(tmp))
            project_state = _load_project_state(ai_dir)
            project_state["graph"]["edges"][0]["source_object_id"] = "O-missing"
            _write_project_state_and_refresh_index(ai_dir, project_state)

            issues = validate_runtime(ai_dir, full=False)

            self.assertTrue(any("source_object_id references missing object" in issue for issue in issues))

    def test_validate_state_rejects_graph_edge_relation_outside_link_relations(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _runtime_with_link(Path(tmp))
            project_state = _load_project_state(ai_dir)
            project_state["graph"]["edges"][0]["relation"] = "duplicates"
            _write_project_state_and_refresh_index(ai_dir, project_state)

            issues = validate_runtime(ai_dir, full=False)

            self.assertTrue(any("project_state.graph.edges[].relation" in issue for issue in issues))


def _bootstrap(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Plan Phase 6-1.",
        current_milestone="Phase 6-1",
    )
    return ai_dir


def _runtime_with_link(tmp: Path) -> Path:
    ai_dir = _bootstrap(tmp)
    session = create_session(str(ai_dir), context="Decision stack graph contract")
    session_id = session["session"]["id"]
    transact(
        ai_dir,
        lambda _bundle: [
            {
                "event_id": "E-evidence",
                "session_id": session_id,
                "event_type": "object_recorded",
                "payload": {"object": _evidence_object()},
            },
            {
                "event_id": "E-link",
                "session_id": session_id,
                "event_type": "object_linked",
                "payload": {"link": _support_link()},
            },
        ],
    )
    return ai_dir


def _evidence_object() -> dict:
    return {
        "id": "O-evidence",
        "type": "evidence",
        "title": "Existing evidence",
        "body": "Evidence supports the project objective.",
        "status": "active",
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": ["E-evidence"],
        "metadata": evidence_metadata(summary="Evidence supports the project objective."),
    }


def _support_link() -> dict:
    return {
        "id": "L-evidence-supports-objective",
        "source_object_id": "O-evidence",
        "relation": "supports",
        "target_object_id": "O-project-objective",
        "rationale": "Evidence supports the project objective.",
        "created_at": "2026-04-23T12:00:00Z",
        "source_event_ids": ["E-link"],
    }


def _load_project_state(ai_dir: Path) -> dict:
    return json.loads((ai_dir / "project-state.json").read_text(encoding="utf-8"))


def _write_project_state_and_refresh_index(ai_dir: Path, project_state: dict) -> None:
    project_state_path = ai_dir / "project-state.json"
    project_state_path.write_text(json.dumps(project_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runtime_index_path = ai_dir / "runtime-index.json"
    runtime_index = json.loads(runtime_index_path.read_text(encoding="utf-8"))
    body = project_state_path.read_bytes()
    runtime_index["projection_files"]["project-state.json"] = {
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }
    runtime_index_path.write_text(json.dumps(runtime_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
