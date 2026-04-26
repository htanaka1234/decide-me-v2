from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    import yaml
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - exercised only in incomplete dev environments.
    raise ImportError(
        "Structured export schema tests require PyYAML and jsonschema. "
        "Install development dependencies with: python3 -m pip install -r requirements-dev.txt"
    ) from exc

from decide_me.classification import classify_session
from decide_me.conflicts import detect_merge_conflicts, resolve_merge_conflict
from decide_me.exports import export_adr, export_decision_register, export_structured_adr
from decide_me.events import build_event, utc_now
from decide_me.interview import advance_session, handle_reply
from decide_me.lifecycle import close_session, create_session, list_sessions, resume_session, show_session
from decide_me.planner import generate_plan
from decide_me.protocol import (
    accept_proposal,
    answer_proposal,
    defer_decision,
    discover_decision,
    enrich_decision,
    invalidate_decision,
    issue_proposal,
    reject_proposal,
    resolve_by_evidence,
    update_classification,
)
from decide_me.session_graph import (
    detect_session_conflicts,
    link_session,
    resolve_session_conflict,
    show_session_graph,
)
from decide_me.store import (
    compact_runtime,
    bootstrap_runtime,
    load_runtime,
    read_raw_event_log,
    read_event_log,
    rebuild_and_persist,
    runtime_paths,
    transact,
    validate_runtime,
)
from decide_me.validate import StateValidationError


def _raw_event_log_text(ai_dir: str | Path) -> str:
    events_dir = Path(ai_dir) / "events"
    return "".join(path.read_text(encoding="utf-8") for path in sorted(events_dir.rglob("*.jsonl")))


def _write_event_file(ai_dir: str | Path, session_id: str, tx_id: str, events: list[dict]) -> None:
    root = Path(ai_dir) / "events"
    directory = root / "system" if session_id == "SYSTEM" else root / "sessions" / session_id
    directory.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events)
    (directory / f"{tx_id}.jsonl").write_text(body, encoding="utf-8")


def _load_yaml_with_schema(text: str, schema_name: str) -> dict:
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    payload = yaml.safe_load(text)
    Draft202012Validator(schema).validate(payload)
    return payload


def _extract_frontmatter(markdown: str) -> str:
    lines = markdown.splitlines()
    if not lines or lines[0] != "---":
        raise AssertionError("markdown does not start with YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise AssertionError("markdown frontmatter is not closed") from exc
    return "\n".join(lines[1:end])


def _create_parallel_proposal_conflict(
    ai_dir: str | Path, *, include_other_session: bool = False
) -> dict[str, str]:
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Reject semantic conflicts",
        current_milestone="MVP",
    )
    session_id = create_session(str(ai_dir), context="Decision thread")["session"]["id"]
    other_tx_id = ""
    if include_other_session:
        other_session_id = create_session(str(ai_dir), context="Other thread")["session"]["id"]
        discover_decision(
            str(ai_dir),
            other_session_id,
            {"id": "D-other", "title": "Other decision", "priority": "P0", "frontier": "now"},
        )
        other_tx_id = next(
            event["tx_id"]
            for event in read_event_log(runtime_paths(ai_dir))
            if event["event_type"] == "decision_discovered"
            and event["payload"]["decision"]["id"] == "D-other"
        )

    for decision_id, title in (("D-conflict-a", "Auth mode"), ("D-conflict-b", "Audit sink")):
        discover_decision(
            str(ai_dir),
            session_id,
            {
                "id": decision_id,
                "title": title,
                "priority": "P0",
                "frontier": "now",
                "domain": "technical",
                "question": f"Resolve {title}?",
            },
        )
    first_proposal = issue_proposal(
        str(ai_dir),
        session_id,
        decision_id="D-conflict-a",
        question="Use magic links?",
        recommendation="Use magic links.",
        why="Smaller MVP surface area.",
        if_not="Passwords expand auth scope.",
    )
    first_tx_id = next(
        event["tx_id"]
        for event in read_event_log(runtime_paths(ai_dir))
        if event["event_type"] == "proposal_issued"
        and event["payload"]["proposal"]["proposal_id"] == first_proposal["proposal_id"]
    )

    conflict_tx_id = "T-20990101T000000000000Z-conflict"
    question = build_event(
        tx_id=conflict_tx_id,
        tx_index=1,
        tx_size=2,
        event_id="E-conflict-1",
        session_id=session_id,
        event_type="question_asked",
        payload={
            "decision_id": "D-conflict-b",
            "question_id": "Q-conflict",
            "question": "Use product database?",
        },
        timestamp="2099-01-01T00:00:00Z",
    )
    proposal = build_event(
        tx_id=conflict_tx_id,
        tx_index=2,
        tx_size=2,
        event_id="E-conflict-2",
        session_id=session_id,
        event_type="proposal_issued",
        payload={
            "proposal": {
                "proposal_id": "P-conflict",
                "origin_session_id": session_id,
                "target_type": "decision",
                "target_id": "D-conflict-b",
                "recommendation_version": 1,
                "based_on_project_head": "H-conflict",
                "question_id": "Q-conflict",
                "question": "Use product database?",
                "recommendation": "Use the product database.",
                "why": "Cheaper for the milestone.",
                "if_not": "A separate sink becomes in scope now.",
                "is_active": True,
                "activated_at": "2099-01-01T00:00:00Z",
                "inactive_reason": None,
            }
        },
        timestamp="2099-01-01T00:00:00Z",
    )
    _write_event_file(ai_dir, session_id, conflict_tx_id, [question, proposal])
    return {
        "session_id": session_id,
        "first_tx_id": first_tx_id,
        "conflict_tx_id": conflict_tx_id,
        "other_tx_id": other_tx_id,
    }


def _accept_runtime_decision(
    ai_dir: str,
    session_id: str,
    *,
    decision_id: str,
    title: str,
    domain: str,
    recommendation: str,
) -> None:
    discover_decision(
        ai_dir,
        session_id,
        {
            "id": decision_id,
            "title": title,
            "priority": "P0",
            "frontier": "now",
            "domain": domain,
            "question": f"Resolve {title}?",
        },
    )
    issue_proposal(
        ai_dir,
        session_id,
        decision_id=decision_id,
        question=f"Use {title}?",
        recommendation=recommendation,
        why="This keeps the milestone scoped.",
        if_not="The implementation plan changes.",
    )
    accept_proposal(ai_dir, session_id)


def _create_linked_session_action_conflict(ai_dir: str | Path) -> dict[str, str]:
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Resolve linked session conflicts",
        current_milestone="MVP",
    )
    parent_id = create_session(str(ai_dir), context="Parent thread")["session"]["id"]
    child_id = create_session(str(ai_dir), context="Child thread")["session"]["id"]
    _accept_runtime_decision(
        str(ai_dir),
        parent_id,
        decision_id="D-parent-shared",
        title="Shared implementation slice",
        domain="technical",
        recommendation="Keep this in technical ownership.",
    )
    _accept_runtime_decision(
        str(ai_dir),
        child_id,
        decision_id="D-child-shared",
        title="Shared implementation slice",
        domain="ops",
        recommendation="Move this to ops ownership.",
    )
    classify_session(
        str(ai_dir),
        child_id,
        candidate_terms=["Move this to ops ownership."],
        source_refs=["accepted_decisions"],
    )
    _accept_runtime_decision(
        str(ai_dir),
        child_id,
        decision_id="D-child-extra",
        title="Child-only implementation slice",
        domain="product",
        recommendation="Keep the child-only work.",
    )
    close_session(str(ai_dir), parent_id)
    close_session(str(ai_dir), child_id)
    link_session(
        str(ai_dir),
        parent_session_id=parent_id,
        child_session_id=child_id,
        relationship="refines",
        reason="Child refines the parent thread.",
    )
    return {"parent_id": parent_id, "child_id": child_id}


class RuntimeFlowTests(unittest.TestCase):
    def test_parallel_sessions_do_not_accept_stale_plain_ok(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Exercise stale proposal handling",
                current_milestone="MVP",
            )
            s1 = create_session(ai_dir, context="Auth thread")["session"]["id"]
            s2 = create_session(ai_dir, context="Audit thread")["session"]["id"]

            discover_decision(
                ai_dir,
                s1,
                {
                    "id": "D-001",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            discover_decision(
                ai_dir,
                s2,
                {
                    "id": "D-002",
                    "title": "Audit sink",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should audit logs work?",
                },
            )

            proposal = issue_proposal(
                ai_dir,
                s1,
                decision_id="D-001",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )
            issue_proposal(
                ai_dir,
                s2,
                decision_id="D-002",
                question="Use the product database?",
                recommendation="Use the product database.",
                why="Cheaper for the milestone.",
                if_not="A separate sink becomes in scope now.",
            )
            accept_proposal(ai_dir, s2)

            with self.assertRaisesRegex(ValueError, "stale"):
                accept_proposal(ai_dir, s1)

            accepted = accept_proposal(ai_dir, s1, proposal_id=proposal["proposal_id"])
            self.assertEqual("accepted", accepted["status"])

            rebuild_and_persist(ai_dir)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_runtime_writes_split_transaction_event_files(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Write split transaction logs",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Auth thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-split",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )

            root = Path(ai_dir) / "events"
            self.assertTrue(list((root / "system").glob("*.jsonl")))
            self.assertTrue(list((root / "sessions" / session_id).glob("*.jsonl")))
            self.assertFalse((Path(ai_dir) / "event-log.jsonl").exists())
            self.assertEqual([], validate_runtime(ai_dir))

    def test_shell_event_discovery_reads_jsonl_files_with_spaces_in_path(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / "runtime with spaces" / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Discover events through find",
                current_milestone="MVP",
            )
            create_session(str(ai_dir), context="Shell discovery")
            paths = runtime_paths(ai_dir)
            discovered = sorted(paths.events_dir.rglob("*.jsonl"))
            stdout = b"\0".join(str(path).encode("utf-8") for path in discovered) + b"\0"
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=stdout,
                stderr=b"",
            )

            with mock.patch.dict(os.environ, {"DECIDE_ME_EVENT_DISCOVERY": "shell"}), mock.patch(
                "decide_me.store.subprocess.run",
                return_value=completed,
            ) as run:
                events = read_raw_event_log(paths)

            self.assertEqual(["project_initialized", "session_created"], [event["event_type"] for event in events])
            run.assert_called_once()
            self.assertEqual(
                ["find", str(paths.events_dir), "-type", "f", "-name", "*.jsonl", "-print0"],
                run.call_args.args[0],
            )

    def test_python_event_discovery_skips_shell(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Discover events through Python",
                current_milestone="MVP",
            )
            paths = runtime_paths(ai_dir)

            with mock.patch.dict(os.environ, {"DECIDE_ME_EVENT_DISCOVERY": "python"}), mock.patch(
                "decide_me.store.subprocess.run",
            ) as run:
                events = read_raw_event_log(paths)

            self.assertEqual(["project_initialized"], [event["event_type"] for event in events])
            run.assert_not_called()

    def test_auto_event_discovery_falls_back_to_python_when_shell_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Fallback event discovery",
                current_milestone="MVP",
            )
            paths = runtime_paths(ai_dir)

            with mock.patch.dict(os.environ, {"DECIDE_ME_EVENT_DISCOVERY": "auto"}), mock.patch(
                "decide_me.store.subprocess.run",
                side_effect=FileNotFoundError("find"),
            ):
                events = read_raw_event_log(paths)

            self.assertEqual(["project_initialized"], [event["event_type"] for event in events])

    def test_shell_event_discovery_reports_required_shell_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Required shell discovery",
                current_milestone="MVP",
            )
            paths = runtime_paths(ai_dir)

            with mock.patch.dict(os.environ, {"DECIDE_ME_EVENT_DISCOVERY": "shell"}), mock.patch(
                "decide_me.store.subprocess.run",
                side_effect=FileNotFoundError("find"),
            ):
                with self.assertRaisesRegex(StateValidationError, "shell event discovery failed"):
                    read_raw_event_log(paths)

    def test_shell_event_discovery_rejects_paths_outside_events_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject unsafe shell paths",
                current_milestone="MVP",
            )
            outside = Path(tmp) / "outside.jsonl"
            outside.write_text("", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=str(outside).encode("utf-8") + b"\0",
                stderr=b"",
            )

            with mock.patch.dict(os.environ, {"DECIDE_ME_EVENT_DISCOVERY": "auto"}), mock.patch(
                "decide_me.store.subprocess.run",
                return_value=completed,
            ):
                with self.assertRaisesRegex(StateValidationError, "outside events"):
                    read_raw_event_log(runtime_paths(ai_dir))

    def test_load_runtime_uses_projection_cache_without_reading_event_log(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Use projection cache",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Cached session")["session"]["id"]
            bad_dir = Path(ai_dir) / "events" / "system"
            bad_dir.mkdir(parents=True, exist_ok=True)
            (bad_dir / "T-bad.jsonl").write_text("{bad json\n", encoding="utf-8")

            bundle = load_runtime(runtime_paths(ai_dir))
            self.assertIn(session_id, bundle["sessions"])
            self.assertEqual([], validate_runtime(ai_dir, full=False))
            self.assertIn("malformed JSON", validate_runtime(ai_dir)[0])

    def test_incremental_transact_updates_runtime_index(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Update checkpoint",
                current_milestone="MVP",
            )
            paths = runtime_paths(ai_dir)
            before = json.loads(paths.runtime_index.read_text(encoding="utf-8"))

            create_session(ai_dir, context="Index update")

            after = json.loads(paths.runtime_index.read_text(encoding="utf-8"))
            self.assertEqual(before["event_count"] + 1, after["event_count"])
            self.assertNotEqual(before["project_head"], after["project_head"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_compact_runtime_refreshes_projection_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Refresh checkpoint",
                current_milestone="MVP",
            )
            paths = runtime_paths(ai_dir)
            index = json.loads(paths.runtime_index.read_text(encoding="utf-8"))
            index["projection_files"] = {}
            paths.runtime_index.write_text(json.dumps(index), encoding="utf-8")

            refreshed = compact_runtime(ai_dir)

            self.assertTrue(refreshed["projection_files"])
            self.assertEqual([], validate_runtime(ai_dir, full=False))

    def test_compact_runtime_rejects_projection_divergence_without_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject divergent cache",
                current_milestone="MVP",
            )
            paths = runtime_paths(ai_dir)
            project_state = json.loads(paths.project_state.read_text(encoding="utf-8"))
            project_state["project"]["objective"] = "Diverged cache"
            paths.project_state.write_text(json.dumps(project_state), encoding="utf-8")
            index_before = paths.runtime_index.read_text(encoding="utf-8")

            with self.assertRaisesRegex(
                StateValidationError,
                "cannot compact invalid runtime: project-state.json does not match the event log",
            ):
                compact_runtime(ai_dir)

            self.assertEqual(index_before, paths.runtime_index.read_text(encoding="utf-8"))
            persisted = json.loads(paths.project_state.read_text(encoding="utf-8"))
            self.assertEqual("Diverged cache", persisted["project"]["objective"])

            rebuilt = rebuild_and_persist(ai_dir)
            self.assertEqual("Reject divergent cache", rebuilt["project_state"]["project"]["objective"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_later_merged_session_transaction_files_rebuild_cleanly(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Merge independent session logs",
                current_milestone="MVP",
            )
            first_session_id = create_session(ai_dir, context="Auth thread")["session"]["id"]
            second_session_id = create_session(ai_dir, context="Audit thread")["session"]["id"]
            discover_decision(
                ai_dir,
                first_session_id,
                {"id": "D-merge-a", "title": "Auth mode", "domain": "technical"},
            )
            discover_decision(
                ai_dir,
                second_session_id,
                {"id": "D-merge-b", "title": "Audit sink", "domain": "ops"},
            )

            second_session_events = Path(ai_dir) / "events" / "sessions" / second_session_id
            stash = Path(tmp) / "stashed-events"
            second_session_events.rename(stash)
            without_second = rebuild_and_persist(ai_dir)
            self.assertNotIn(second_session_id, without_second["sessions"])
            self.assertEqual([], validate_runtime(ai_dir))

            stash.rename(second_session_events)
            merged = rebuild_and_persist(ai_dir)
            self.assertIn(first_session_id, merged["sessions"])
            self.assertIn(second_session_id, merged["sessions"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_session_graph_rebuilds_parent_child_grandchild_projection(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Graph session lineage",
                current_milestone="MVP",
            )
            parent_id = create_session(ai_dir, context="Parent")["session"]["id"]
            child_id = create_session(ai_dir, context="Child")["session"]["id"]
            grandchild_id = create_session(ai_dir, context="Grandchild")["session"]["id"]

            link_session(
                ai_dir,
                parent_session_id=parent_id,
                child_session_id=child_id,
                relationship="refines",
                reason="Child refines parent.",
            )
            link_session(
                ai_dir,
                parent_session_id=child_id,
                child_session_id=grandchild_id,
                relationship="derived_from",
                reason="Grandchild follows child.",
            )

            bundle = rebuild_and_persist(ai_dir)
            graph = bundle["project_state"]["session_graph"]
            self.assertEqual(3, len(graph["nodes"]))
            self.assertEqual(2, len(graph["edges"]))
            related = show_session_graph(ai_dir, session_id=parent_id)["related_sessions"]
            self.assertEqual(
                [parent_id, child_id, grandchild_id],
                [item["session_id"] for item in related],
            )
            self.assertEqual([], validate_runtime(ai_dir))

    def test_link_session_rejects_duplicate_relationship_before_write(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject duplicate links before write",
                current_milestone="MVP",
            )
            parent_id = create_session(ai_dir, context="Parent")["session"]["id"]
            child_id = create_session(ai_dir, context="Child")["session"]["id"]
            before = _raw_event_log_text(ai_dir)
            link_session(
                ai_dir,
                parent_session_id=parent_id,
                child_session_id=child_id,
                relationship="refines",
                reason="Child refines parent.",
            )
            linked = _raw_event_log_text(ai_dir)

            with self.assertRaisesRegex(ValueError, "duplicate session_linked relationship"):
                link_session(
                    ai_dir,
                    parent_session_id=parent_id,
                    child_session_id=child_id,
                    relationship="refines",
                    reason="Duplicate link.",
                )

            self.assertNotEqual(before, linked)
            self.assertEqual(linked, _raw_event_log_text(ai_dir))
            self.assertEqual([], validate_runtime(ai_dir))

    def test_link_session_allows_same_pair_with_different_relationship(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Typed session graph links",
                current_milestone="MVP",
            )
            parent_id = create_session(ai_dir, context="Parent")["session"]["id"]
            child_id = create_session(ai_dir, context="Child")["session"]["id"]

            link_session(
                ai_dir,
                parent_session_id=parent_id,
                child_session_id=child_id,
                relationship="refines",
                reason="Child refines parent.",
            )
            link_session(
                ai_dir,
                parent_session_id=parent_id,
                child_session_id=child_id,
                relationship="depends_on",
                reason="Child also depends on parent.",
            )

            graph = show_session_graph(ai_dir)["session_graph"]
            relationships = sorted(
                edge["relationship"]
                for edge in graph["edges"]
                if edge["parent_session_id"] == parent_id and edge["child_session_id"] == child_id
            )
            self.assertEqual(["depends_on", "refines"], relationships)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_link_session_rejects_cycle_before_write_but_allows_contradicts(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject cyclic links before write",
                current_milestone="MVP",
            )
            first_id = create_session(ai_dir, context="First")["session"]["id"]
            second_id = create_session(ai_dir, context="Second")["session"]["id"]
            link_session(
                ai_dir,
                parent_session_id=first_id,
                child_session_id=second_id,
                relationship="refines",
                reason="Second refines first.",
            )
            linked = _raw_event_log_text(ai_dir)

            with self.assertRaisesRegex(ValueError, "session_linked would create a session graph cycle"):
                link_session(
                    ai_dir,
                    parent_session_id=second_id,
                    child_session_id=first_id,
                    relationship="depends_on",
                    reason="This would create a cycle.",
                )

            self.assertEqual(linked, _raw_event_log_text(ai_dir))
            contradiction = link_session(
                ai_dir,
                parent_session_id=second_id,
                child_session_id=first_id,
                relationship="contradicts",
                reason="Contradiction links are allowed to be cyclic.",
            )
            self.assertEqual("ok", contradiction["status"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_detects_and_resolves_parent_child_session_conflict(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            ids = _create_linked_session_action_conflict(ai_dir)

            detected = detect_session_conflicts(
                ai_dir,
                session_ids=[ids["parent_id"]],
                include_related=True,
            )
            self.assertEqual([ids["parent_id"], ids["child_id"]], [item["session_id"] for item in detected["related_sessions"]])
            unresolved = [item for item in detected["semantic_conflicts"] if item["requires_resolution"]]
            self.assertEqual(1, len(unresolved))
            self.assertEqual("action-slice-responsibility-mismatch", unresolved[0]["kind"])
            conflict_id = unresolved[0]["conflict_id"]

            resolve_session_conflict(
                ai_dir,
                conflict_id=conflict_id,
                winning_session_id=ids["parent_id"],
                rejected_session_ids=[ids["child_id"]],
                reason="Keep parent ownership for the shared slice.",
            )

            after = detect_session_conflicts(
                ai_dir,
                session_ids=[ids["parent_id"]],
                include_related=True,
            )
            self.assertEqual([], after["semantic_conflicts"])
            self.assertEqual([conflict_id], [item["conflict_id"] for item in after["resolved_conflicts"]])
            resolved_context = after["resolved_conflicts"][0]["suppressed_context"]
            self.assertEqual([ids["child_id"]], resolved_context["session_ids"])
            self.assertEqual(["D-child-shared"], resolved_context["decision_ids"])
            self.assertEqual(["Shared implementation slice"], resolved_context["action_slice_names"])

            child = show_session(ai_dir, ids["child_id"])["session"]
            self.assertNotIn("D-child-shared", child["session"]["decision_ids"])
            self.assertNotIn("Move this to ops ownership.", child["classification"]["search_terms"])
            self.assertEqual([], child["classification"]["assigned_tags"])
            child_close_summary = child["close_summary"]
            self.assertEqual(
                ["D-child-extra"],
                [item["id"] for item in child_close_summary["accepted_decisions"]],
            )
            self.assertEqual(
                ["Child-only implementation slice"],
                [item["name"] for item in child_close_summary["candidate_action_slices"]],
            )
            self.assertEqual(["D-child-extra"], child_close_summary["candidate_workstreams"][0]["scope"])

            graph = show_session_graph(ai_dir, include_inferred=True)["session_graph"]
            child_node = next(item for item in graph["nodes"] if item["session_id"] == ids["child_id"])
            self.assertNotIn("D-child-shared", child_node["decision_ids"])
            inferred_blob = json.dumps(graph["inferred_candidates"], sort_keys=True)
            self.assertNotIn("D-child-shared", inferred_blob)

            query_listing = list_sessions(ai_dir, query="Move this to ops ownership.")
            tag_listing = list_sessions(ai_dir, tag_terms=["Move this to ops ownership."])
            self.assertNotIn(ids["child_id"], [item["session_id"] for item in query_listing["sessions"]])
            self.assertNotIn(ids["child_id"], [item["session_id"] for item in tag_listing["sessions"]])

            plan = generate_plan(ai_dir, [ids["parent_id"], ids["child_id"]])
            self.assertEqual("action-plan", plan["status"])
            action_names = [item["name"] for item in plan["action_plan"]["action_slices"]]
            self.assertEqual(1, action_names.count("Shared implementation slice"))
            self.assertIn("Child-only implementation slice", action_names)

            future_id = create_session(ai_dir, context="Future shared slice reuse")["session"]["id"]
            discover_decision(
                ai_dir,
                future_id,
                {
                    "id": "D-future-shared",
                    "title": "Shared implementation slice",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "Reuse the shared slice decision?",
                },
            )
            advanced = advance_session(ai_dir, future_id, repo_root=tmp)
            self.assertEqual("complete", advanced["status"])
            self.assertEqual(
                "Keep this in technical ownership.",
                advanced["auto_resolved"][0]["summary"],
            )
            self.assertIn("Move this to ops ownership.", _raw_event_log_text(ai_dir))
            self.assertEqual([], validate_runtime(ai_dir))

    def test_session_scope_resolution_suppresses_session_search_surface(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Suppress session scoped conflict context",
                current_milestone="MVP",
            )
            winner_id = create_session(ai_dir, context="Winner session")["session"]["id"]
            loser_id = create_session(ai_dir, context="Loser-only Session Title")["session"]["id"]
            close_session(ai_dir, winner_id)
            _accept_runtime_decision(
                ai_dir,
                loser_id,
                decision_id="D-loser-session",
                title="Loser-only Session Marker",
                domain="technical",
                recommendation="Keep the loser-only session marker.",
            )
            classify_session(
                ai_dir,
                loser_id,
                candidate_terms=["Loser-only Session Marker"],
                source_refs=["accepted_decisions"],
            )
            close_session(ai_dir, loser_id)

            now = utc_now()

            def builder(_: dict[str, object]) -> list[dict[str, object]]:
                return [
                    {
                        "session_id": winner_id,
                        "event_type": "semantic_conflict_resolved",
                        "payload": {
                            "conflict_id": "C-session-scope",
                            "winning_session_id": winner_id,
                            "rejected_session_ids": [loser_id],
                            "scope": {
                                "kind": "session",
                                "session_ids": [winner_id, loser_id],
                            },
                            "reason": "Suppress the losing session scope.",
                            "resolved_at": now,
                        },
                    }
                ]

            transact(ai_dir, builder)

            loser = show_session(ai_dir, loser_id)["session"]
            self.assertNotIn("D-loser-session", loser["session"]["decision_ids"])
            self.assertNotEqual("Loser-only Session Title", loser["close_summary"]["work_item_title"])
            self.assertNotEqual("Loser-only Session Marker", loser["close_summary"]["work_item_statement"])
            self.assertEqual([], loser["classification"]["search_terms"])
            self.assertEqual([], loser["classification"]["assigned_tags"])
            self.assertEqual(0, list_sessions(ai_dir, query="Loser-only Session Title")["count"])
            self.assertEqual(0, list_sessions(ai_dir, query="Loser-only Session Marker")["count"])
            self.assertEqual(0, list_sessions(ai_dir, tag_terms=["Loser-only Session Marker"])["count"])
            self.assertIn("Loser-only Session Marker", _raw_event_log_text(ai_dir))
            self.assertEqual([], validate_runtime(ai_dir))

    def test_generate_plan_uses_resolved_view_for_three_session_conflict_detection(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Avoid resolved false positives",
                current_milestone="MVP",
            )
            first_id = create_session(ai_dir, context="First thread")["session"]["id"]
            second_id = create_session(ai_dir, context="Second thread")["session"]["id"]
            third_id = create_session(ai_dir, context="Third thread")["session"]["id"]
            _accept_runtime_decision(
                ai_dir,
                first_id,
                decision_id="D-first-shared",
                title="Shared implementation slice",
                domain="technical",
                recommendation="Keep technical ownership.",
            )
            _accept_runtime_decision(
                ai_dir,
                first_id,
                decision_id="D-first-extra",
                title="First-only implementation slice",
                domain="product",
                recommendation="Keep the first-only work.",
            )
            _accept_runtime_decision(
                ai_dir,
                second_id,
                decision_id="D-second-shared",
                title="Shared implementation slice",
                domain="ops",
                recommendation="Move to ops ownership.",
            )
            _accept_runtime_decision(
                ai_dir,
                third_id,
                decision_id="D-third-shared",
                title="Shared implementation slice",
                domain="ops",
                recommendation="Move to ops ownership.",
            )
            close_session(ai_dir, first_id)
            close_session(ai_dir, second_id)
            close_session(ai_dir, third_id)
            link_session(
                ai_dir,
                parent_session_id=first_id,
                child_session_id=second_id,
                relationship="refines",
                reason="Second refines first.",
            )

            detected = detect_session_conflicts(ai_dir, session_ids=[first_id], include_related=True)
            conflict_id = detected["semantic_conflicts"][0]["conflict_id"]
            resolve_session_conflict(
                ai_dir,
                conflict_id=conflict_id,
                winning_session_id=second_id,
                rejected_session_ids=[first_id],
                reason="Keep the ops ownership from the second thread.",
            )

            plan = generate_plan(ai_dir, [first_id, second_id, third_id])
            self.assertEqual("action-plan", plan["status"])
            action_slices = plan["action_plan"]["action_slices"]
            action_names = [item["name"] for item in action_slices]
            shared_slices = [item for item in action_slices if item["name"] == "Shared implementation slice"]
            self.assertEqual(2, len(shared_slices))
            self.assertEqual({"ops"}, {item["responsibility"] for item in shared_slices})
            self.assertIn("First-only implementation slice", action_names)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_cli_links_detects_and_resolves_session_conflict(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="CLI graph conflict resolution",
                current_milestone="MVP",
            )
            parent_id = create_session(ai_dir, context="Parent")["session"]["id"]
            child_id = create_session(ai_dir, context="Child")["session"]["id"]
            _accept_runtime_decision(
                ai_dir,
                parent_id,
                decision_id="D-cli-parent",
                title="CLI shared slice",
                domain="technical",
                recommendation="Keep technical ownership.",
            )
            _accept_runtime_decision(
                ai_dir,
                child_id,
                decision_id="D-cli-child",
                title="CLI shared slice",
                domain="ops",
                recommendation="Move to ops ownership.",
            )
            close_session(ai_dir, parent_id)
            close_session(ai_dir, child_id)

            linked = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "link-session",
                    "--ai-dir",
                    ai_dir,
                    "--parent-session-id",
                    parent_id,
                    "--child-session-id",
                    child_id,
                    "--relationship",
                    "refines",
                    "--reason",
                    "Child refines parent.",
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, linked.returncode, linked.stderr)

            detected = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "detect-session-conflicts",
                    "--ai-dir",
                    ai_dir,
                    "--session-id",
                    parent_id,
                    "--include-related",
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, detected.returncode, detected.stderr)
            payload = json.loads(detected.stdout)
            conflict_id = payload["semantic_conflicts"][0]["conflict_id"]

            resolved = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "resolve-session-conflict",
                    "--ai-dir",
                    ai_dir,
                    "--conflict-id",
                    conflict_id,
                    "--winning-session-id",
                    parent_id,
                    "--reject-session-id",
                    child_id,
                    "--reason",
                    "Keep parent ownership.",
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, resolved.returncode, resolved.stderr)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_inferred_only_relationship_does_not_expand_resolution_scope(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Infer session relationships",
                current_milestone="MVP",
            )
            first_id = create_session(ai_dir, context="First")["session"]["id"]
            second_id = create_session(ai_dir, context="Second")["session"]["id"]
            _accept_runtime_decision(
                ai_dir,
                first_id,
                decision_id="D-first",
                title="Shared implementation slice",
                domain="technical",
                recommendation="Keep technical ownership.",
            )
            _accept_runtime_decision(
                ai_dir,
                second_id,
                decision_id="D-second",
                title="Shared implementation slice",
                domain="ops",
                recommendation="Move to ops ownership.",
            )
            close_session(ai_dir, first_id)
            close_session(ai_dir, second_id)

            graph = show_session_graph(ai_dir, session_id=first_id, include_inferred=True)
            self.assertTrue(graph["session_graph"]["inferred_candidates"])
            detected = detect_session_conflicts(ai_dir, session_ids=[first_id], include_related=True)
            self.assertEqual([first_id], [item["session_id"] for item in detected["related_sessions"]])
            self.assertEqual([], detected["semantic_conflicts"])

    def test_inferred_session_candidates_are_on_demand_only(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Infer on demand",
                current_milestone="MVP",
            )
            first_id = create_session(ai_dir, context="First")["session"]["id"]
            second_id = create_session(ai_dir, context="Second")["session"]["id"]
            _accept_runtime_decision(
                ai_dir,
                first_id,
                decision_id="D-first-shared",
                title="Shared decision",
                domain="technical",
                recommendation="Keep technical ownership.",
            )
            _accept_runtime_decision(
                ai_dir,
                second_id,
                decision_id="D-second-shared",
                title="Shared decision",
                domain="ops",
                recommendation="Move to ops ownership.",
            )
            close_session(ai_dir, first_id)
            close_session(ai_dir, second_id)

            persisted = json.loads((Path(ai_dir) / "project-state.json").read_text(encoding="utf-8"))
            self.assertEqual([], persisted["session_graph"]["inferred_candidates"])
            without_inferred = show_session_graph(ai_dir, include_inferred=False)
            self.assertEqual([], without_inferred["session_graph"]["inferred_candidates"])
            with_inferred = show_session_graph(ai_dir, session_id=first_id, include_inferred=True)
            self.assertTrue(with_inferred["session_graph"]["inferred_candidates"])

    def test_same_session_conflicting_parallel_proposal_transactions_fail_validation(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            _create_parallel_proposal_conflict(ai_dir)

            issues = validate_runtime(ai_dir)
            self.assertGreaterEqual(len(issues), 1)
            self.assertIn("proposal_issued while proposal", issues[0])

    def test_detects_same_session_merge_conflict_candidates(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            ids = _create_parallel_proposal_conflict(ai_dir)

            conflicts = detect_merge_conflicts(ai_dir)

            self.assertEqual(1, len(conflicts))
            self.assertEqual(ids["session_id"], conflicts[0]["session_id"])
            self.assertEqual("competing-active-proposals", conflicts[0]["kind"])
            candidate_tx_ids = {item["tx_id"] for item in conflicts[0]["candidate_transactions"]}
            self.assertEqual({ids["first_tx_id"], ids["conflict_tx_id"]}, candidate_tx_ids)
            for option in conflicts[0]["resolution_options"]:
                self.assertIn("surviving_tx_ids", option)
                self.assertEqual(option["surviving_tx_ids"], option["keep_tx_ids"])
                self.assertTrue(set(option["surviving_tx_ids"]) <= candidate_tx_ids)

    def test_cli_detects_and_resolves_same_session_merge_conflict(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            ids = _create_parallel_proposal_conflict(ai_dir)

            detected = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "detect-merge-conflicts",
                    "--ai-dir",
                    ai_dir,
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, detected.returncode, detected.stderr)
            payload = json.loads(detected.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(1, len(payload["conflicts"]))

            resolved = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "resolve-merge-conflict",
                    "--ai-dir",
                    ai_dir,
                    "--session-id",
                    ids["session_id"],
                    "--keep-tx-id",
                    ids["first_tx_id"],
                    "--reject-tx-id",
                    ids["conflict_tx_id"],
                    "--reason",
                    "Keep the earlier branch.",
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, resolved.returncode, resolved.stderr)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_resolves_same_session_conflict_by_rejecting_later_transaction(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            ids = _create_parallel_proposal_conflict(ai_dir)

            result = resolve_merge_conflict(
                ai_dir,
                session_id=ids["session_id"],
                keep_tx_id=ids["first_tx_id"],
                reject_tx_ids=[ids["conflict_tx_id"]],
                reason="Keep the earlier proposal branch.",
            )

            self.assertEqual(ids["first_tx_id"], result["kept_tx_id"])
            self.assertEqual([ids["conflict_tx_id"]], result["rejected_tx_ids"])
            self.assertEqual([], validate_runtime(ai_dir))
            raw_tx_ids = {event["tx_id"] for event in read_raw_event_log(runtime_paths(ai_dir))}
            effective_events = read_event_log(runtime_paths(ai_dir))
            effective_tx_ids = {event["tx_id"] for event in effective_events}
            self.assertIn(ids["conflict_tx_id"], raw_tx_ids)
            self.assertNotIn(ids["conflict_tx_id"], effective_tx_ids)
            self.assertIn(result["resolution_event"]["tx_id"], effective_tx_ids)

    def test_resolves_same_session_conflict_by_rejecting_earlier_transaction(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            ids = _create_parallel_proposal_conflict(ai_dir)

            resolve_merge_conflict(
                ai_dir,
                session_id=ids["session_id"],
                keep_tx_id=ids["conflict_tx_id"],
                reject_tx_ids=[ids["first_tx_id"]],
                reason="Keep the merged-in proposal branch.",
            )

            bundle = rebuild_and_persist(ai_dir)
            active = bundle["sessions"][ids["session_id"]]["working_state"]["active_proposal"]
            self.assertEqual("P-conflict", active["proposal_id"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_resolves_accept_reject_response_conflict(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Resolve response conflicts",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {"id": "D-response", "title": "Response decision", "priority": "P0", "frontier": "now"},
            )
            proposal = issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-response",
                question="Use the recommendation?",
                recommendation="Use the recommendation.",
                why="It is enough for the milestone.",
                if_not="The scope expands.",
            )
            accept_proposal(ai_dir, session_id)
            accept_tx_id = next(
                event["tx_id"]
                for event in read_event_log(runtime_paths(ai_dir))
                if event["event_type"] == "proposal_accepted"
                and event["payload"]["proposal_id"] == proposal["proposal_id"]
            )
            reject_tx_id = "T-20990101T000001000000Z-reject"
            rejection = build_event(
                tx_id=reject_tx_id,
                tx_index=1,
                tx_size=1,
                event_id="E-response-reject",
                session_id=session_id,
                event_type="proposal_rejected",
                payload={
                    "proposal_id": proposal["proposal_id"],
                    "origin_session_id": session_id,
                    "target_type": "decision",
                    "target_id": "D-response",
                    "reason": "Reject from the parallel branch.",
                },
                timestamp="2099-01-01T00:00:01Z",
            )
            _write_event_file(ai_dir, session_id, reject_tx_id, [rejection])

            conflicts = detect_merge_conflicts(ai_dir)
            self.assertEqual(1, len(conflicts))
            self.assertEqual("proposal-response-conflict", conflicts[0]["kind"])

            resolve_merge_conflict(
                ai_dir,
                session_id=session_id,
                keep_tx_id=accept_tx_id,
                reject_tx_ids=[reject_tx_id],
                reason="Keep the accepted response.",
            )

            self.assertEqual([], validate_runtime(ai_dir))

    def test_rejects_invalid_merge_resolution_targets(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            ids = _create_parallel_proposal_conflict(ai_dir, include_other_session=True)
            system_tx_id = next(
                event["tx_id"]
                for event in read_raw_event_log(runtime_paths(ai_dir))
                if event["event_type"] == "project_initialized"
            )

            with self.assertRaisesRegex(ValueError, "unknown transaction"):
                resolve_merge_conflict(
                    ai_dir,
                    session_id=ids["session_id"],
                    keep_tx_id=ids["first_tx_id"],
                    reject_tx_ids=["T-missing"],
                    reason="Invalid target.",
                )
            with self.assertRaisesRegex(ValueError, "does not belong"):
                resolve_merge_conflict(
                    ai_dir,
                    session_id=ids["session_id"],
                    keep_tx_id=ids["first_tx_id"],
                    reject_tx_ids=[ids["other_tx_id"]],
                    reason="Invalid target.",
                )
            with self.assertRaisesRegex(ValueError, "cannot be selected"):
                resolve_merge_conflict(
                    ai_dir,
                    session_id=ids["session_id"],
                    keep_tx_id=ids["first_tx_id"],
                    reject_tx_ids=[system_tx_id],
                    reason="Invalid target.",
                )
            unrelated_same_session_tx_id = next(
                event["tx_id"]
                for event in read_raw_event_log(runtime_paths(ai_dir))
                if event["event_type"] == "decision_discovered"
                and event["payload"]["decision"]["id"] == "D-conflict-b"
            )
            with self.assertRaisesRegex(ValueError, "not part of the unresolved merge conflict"):
                resolve_merge_conflict(
                    ai_dir,
                    session_id=ids["session_id"],
                    keep_tx_id=unrelated_same_session_tx_id,
                    reject_tx_ids=[ids["conflict_tx_id"]],
                    reason="Invalid target.",
                )

    def test_lifecycle_merge_conflict_candidates_exclude_unrelated_keep_transaction(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Resolve lifecycle conflicts",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Lifecycle thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-lifecycle",
                    "title": "Lifecycle decision",
                    "priority": "P0",
                    "frontier": "now",
                },
            )
            unrelated_tx_id = next(
                event["tx_id"]
                for event in read_event_log(runtime_paths(ai_dir))
                if event["event_type"] == "decision_discovered"
                and event["payload"]["decision"]["id"] == "D-lifecycle"
            )
            close_session(ai_dir, session_id)
            close_tx_id = next(
                event["tx_id"]
                for event in read_event_log(runtime_paths(ai_dir))
                if event["event_type"] == "session_closed"
            )
            late_tx_id = "T-20990101T000004000000Z-late-classification"
            late_event = build_event(
                tx_id=late_tx_id,
                tx_index=1,
                tx_size=1,
                event_id="E-late-classification",
                session_id=session_id,
                event_type="classification_updated",
                payload={
                    "classification": {
                        "domain": "technical",
                        "abstraction_level": "architecture",
                        "assigned_tags": [],
                        "compatibility_tags": [],
                        "search_terms": ["lifecycle"],
                        "source_refs": [],
                        "updated_at": "2099-01-01T00:00:04Z",
                    }
                },
                timestamp="2099-01-01T00:00:04Z",
            )
            _write_event_file(ai_dir, session_id, late_tx_id, [late_event])

            conflicts = detect_merge_conflicts(ai_dir)
            self.assertEqual(1, len(conflicts))
            self.assertEqual("session-lifecycle-conflict", conflicts[0]["kind"])
            candidate_tx_ids = {item["tx_id"] for item in conflicts[0]["candidate_transactions"]}
            self.assertEqual({close_tx_id, late_tx_id}, candidate_tx_ids)
            reject_late_option = next(
                option for option in conflicts[0]["resolution_options"] if option["reject_tx_ids"] == [late_tx_id]
            )
            self.assertEqual([close_tx_id], reject_late_option["surviving_tx_ids"])
            self.assertNotIn(unrelated_tx_id, reject_late_option["surviving_tx_ids"])

            with self.assertRaisesRegex(ValueError, "not part of the unresolved merge conflict"):
                resolve_merge_conflict(
                    ai_dir,
                    session_id=session_id,
                    keep_tx_id=unrelated_tx_id,
                    reject_tx_ids=[late_tx_id],
                    reason="Invalid keep target.",
                )

            resolve_merge_conflict(
                ai_dir,
                session_id=session_id,
                keep_tx_id=close_tx_id,
                reject_tx_ids=[late_tx_id],
                reason="Keep the session close and reject the late mutation.",
            )
            self.assertEqual([], validate_runtime(ai_dir))

    def test_transaction_rejection_does_not_hide_raw_structure_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            ids = _create_parallel_proposal_conflict(ai_dir)
            bad_tx_id = "T-20990101T000002000000Z-bad"
            bad_event = build_event(
                tx_id=bad_tx_id,
                tx_index=1,
                tx_size=1,
                event_id="E-bad-structure",
                session_id=ids["session_id"],
                event_type="decision_enriched",
                payload={"decision_id": "D-conflict-a", "notes_append": ["bad branch"]},
                timestamp="2099-01-01T00:00:02Z",
            )
            bad_event["tx_size"] = 2
            _write_event_file(ai_dir, ids["session_id"], bad_tx_id, [bad_event])
            resolution_tx_id = "T-20990101T000003000000Z-resolution"
            resolution = build_event(
                tx_id=resolution_tx_id,
                tx_index=1,
                tx_size=1,
                event_id="E-resolution-bad-structure",
                session_id=ids["session_id"],
                event_type="transaction_rejected",
                payload={
                    "kept_tx_id": ids["first_tx_id"],
                    "rejected_tx_ids": [bad_tx_id],
                    "reason": "Try to hide malformed transaction.",
                    "resolved_at": "2099-01-01T00:00:03Z",
                    "conflict_kind": "same-session-semantic-conflict",
                    "conflict_summary": "bad structure",
                },
                timestamp="2099-01-01T00:00:03Z",
            )
            _write_event_file(ai_dir, ids["session_id"], resolution_tx_id, [resolution])

            issues = validate_runtime(ai_dir)
            self.assertEqual(1, len(issues))
            self.assertIn("tx_size does not match event count", issues[0])

    def test_cross_session_explicit_proposal_acceptance_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Keep proposal ownership session scoped",
                current_milestone="MVP",
            )
            owning_session_id = create_session(ai_dir, context="Auth thread")["session"]["id"]
            other_session_id = create_session(ai_dir, context="Audit thread")["session"]["id"]

            discover_decision(
                ai_dir,
                owning_session_id,
                {
                    "id": "D-ownership",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            proposal = issue_proposal(
                ai_dir,
                owning_session_id,
                decision_id="D-ownership",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )

            with self.assertRaisesRegex(ValueError, "belongs to session"):
                accept_proposal(ai_dir, other_session_id, proposal_id=proposal["proposal_id"])

            shown = show_session(ai_dir, owning_session_id)
            active = shown["session"]["working_state"]["active_proposal"]
            self.assertEqual(proposal["proposal_id"], active["proposal_id"])
            self.assertTrue(active["is_active"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_inactive_proposal_cannot_be_reused_after_accept_or_reject(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject inactive proposal reuse",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Auth thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-reuse-accept",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            proposal = issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-reuse-accept",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )
            accept_proposal(ai_dir, session_id)

            with self.assertRaisesRegex(ValueError, "inactive"):
                accept_proposal(ai_dir, session_id, proposal_id=proposal["proposal_id"])
            with self.assertRaisesRegex(ValueError, "inactive"):
                reject_proposal(ai_dir, session_id, proposal_id=proposal["proposal_id"], reason="No")

            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-reuse-reject",
                    "title": "Audit sink",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "question": "Where should audit logs land?",
                },
            )
            rejected = issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-reuse-reject",
                question="Use the product database?",
                recommendation="Use the product database.",
                why="Cheaper for the milestone.",
                if_not="A separate sink becomes in scope now.",
            )
            reject_proposal(ai_dir, session_id, reason="No")

            with self.assertRaisesRegex(ValueError, "inactive"):
                accept_proposal(ai_dir, session_id, proposal_id=rejected["proposal_id"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_resume_session_makes_previous_proposal_unusable(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject proposal reuse after resume",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Auth thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-resume",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            proposal = issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-resume",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )

            resume_session(ai_dir, session_id)

            with self.assertRaisesRegex(ValueError, "inactive"):
                accept_proposal(ai_dir, session_id, proposal_id=proposal["proposal_id"])
            with self.assertRaisesRegex(ValueError, "inactive"):
                reject_proposal(ai_dir, session_id, reason="No")
            with self.assertRaisesRegex(ValueError, "inactive"):
                answer_proposal(ai_dir, session_id, answer_summary="Use passwords.")

            turn = advance_session(ai_dir, session_id, repo_root=tmp)
            self.assertEqual("question", turn["status"])
            self.assertEqual("D-resume", turn["decision_id"])
            self.assertNotEqual(proposal["proposal_id"], turn["proposal_id"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_closed_session_rejects_proposal_replies(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Keep closed sessions read-only",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Retention thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-closed",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "question": "How long should audit logs be retained?",
                },
            )
            proposal = issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-closed",
                question="Use 30 days?",
                recommendation="Use 30 days.",
                why="Keeps MVP scope small.",
                if_not="Longer retention expands compliance scope.",
            )
            close_session(ai_dir, session_id)

            with self.assertRaisesRegex(ValueError, "closed"):
                accept_proposal(ai_dir, session_id, proposal_id=proposal["proposal_id"])
            with self.assertRaisesRegex(ValueError, "closed"):
                reject_proposal(ai_dir, session_id, proposal_id=proposal["proposal_id"], reason="No")
            with self.assertRaisesRegex(ValueError, "closed"):
                handle_reply(ai_dir, session_id, "Use 90 days.", repo_root=tmp)
            close_summary = show_session(ai_dir, session_id)["session"]["close_summary"]
            self.assertEqual("unresolved", close_summary["unresolved_blockers"][0]["status"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_empty_session_does_not_claim_project_open_decisions(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Keep empty sessions unbound",
                current_milestone="MVP",
            )
            owning_session_id = create_session(ai_dir, context="Auth thread")["session"]["id"]
            empty_session_id = create_session(ai_dir, context="New thread")["session"]["id"]
            discover_decision(
                ai_dir,
                owning_session_id,
                {
                    "id": "D-open",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )

            turn = advance_session(ai_dir, empty_session_id, repo_root=tmp)
            self.assertEqual("unbound", turn["status"])
            self.assertIn("No decisions are bound", turn["message"])
            self.assertEqual([], show_session(ai_dir, empty_session_id)["session"]["session"]["decision_ids"])
            self.assertEqual(["D-open"], show_session(ai_dir, owning_session_id)["session"]["session"]["decision_ids"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_advance_session_returns_stale_prompt_for_active_stale_proposal(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Handle active stale proposals",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Auth thread")["session"]["id"]
            other_session_id = create_session(ai_dir, context="Other thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-stale",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            proposal = issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-stale",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )
            discover_decision(
                ai_dir,
                other_session_id,
                {
                    "id": "D-unrelated",
                    "title": "Unrelated decision",
                    "priority": "P2",
                    "frontier": "later",
                    "domain": "ops",
                    "question": "Should this make the proposal stale?",
                },
            )

            turn = advance_session(ai_dir, session_id, repo_root=tmp)

            self.assertEqual("stale-proposal", turn["status"])
            self.assertEqual(proposal["proposal_id"], turn["proposal_id"])
            self.assertEqual("project-head-changed", turn["stale_reason"])
            self.assertIn("Accept P-", turn["message"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_terminal_decisions_cannot_be_deferred(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Protect terminal decisions",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-accepted-terminal",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-accepted-terminal",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )
            accept_proposal(ai_dir, session_id)

            with self.assertRaisesRegex(ValueError, "accepted"):
                defer_decision(
                    ai_dir,
                    session_id,
                    decision_id="D-accepted-terminal",
                    reason="Move it later.",
                )

            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-evidence-terminal",
                    "title": "Existing auth flow",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "Which auth flow already exists?",
                    "resolvable_by": "codebase",
                },
            )
            resolve_by_evidence(
                ai_dir,
                session_id,
                decision_id="D-evidence-terminal",
                source="codebase",
                summary="Use the existing magic-link flow.",
                evidence_refs=["app/auth.py"],
            )

            with self.assertRaisesRegex(ValueError, "resolved-by-evidence"):
                defer_decision(
                    ai_dir,
                    session_id,
                    decision_id="D-evidence-terminal",
                    reason="Move it later.",
                )
            self.assertEqual([], validate_runtime(ai_dir))

    def test_active_proposal_blocks_other_decision_mutations(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Protect active proposal state",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-active",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-other",
                    "title": "Existing auth flow",
                    "priority": "P1",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "Which auth flow already exists?",
                    "resolvable_by": "codebase",
                },
            )
            proposal = issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-active",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )

            with self.assertRaisesRegex(ValueError, "active proposal"):
                issue_proposal(
                    ai_dir,
                    session_id,
                    decision_id="D-other",
                    question="Use the existing flow?",
                    recommendation="Use the existing flow.",
                    why="It is already implemented.",
                    if_not="A new flow expands scope.",
                )
            with self.assertRaisesRegex(ValueError, "proposed"):
                issue_proposal(
                    ai_dir,
                    session_id,
                    decision_id="D-active",
                    question="Use passwords?",
                    recommendation="Use passwords.",
                    why="Enterprise users expect it.",
                    if_not="Magic links may be unfamiliar.",
                )
            with self.assertRaisesRegex(ValueError, "active proposal"):
                defer_decision(ai_dir, session_id, decision_id="D-other", reason="Move it later.")
            with self.assertRaisesRegex(ValueError, "active proposal"):
                resolve_by_evidence(
                    ai_dir,
                    session_id,
                    decision_id="D-other",
                    source="codebase",
                    summary="Use the existing magic-link flow.",
                    evidence_refs=["app/auth.py"],
                )

            shown = show_session(ai_dir, session_id)["session"]
            active = shown["working_state"]["active_proposal"]
            self.assertEqual(proposal["proposal_id"], active["proposal_id"])
            self.assertTrue(active["is_active"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_defer_active_proposal_allows_next_decision_proposal(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Continue after deferring an active proposal",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            for decision_id, title in (("D-first", "Auth mode"), ("D-next", "Audit sink")):
                discover_decision(
                    ai_dir,
                    session_id,
                    {
                        "id": decision_id,
                        "title": title,
                        "priority": "P0",
                        "frontier": "now",
                        "domain": "technical",
                        "question": f"What should we do about {title.lower()}?",
                    },
                )

            issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-first",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )
            defer_decision(ai_dir, session_id, decision_id="D-first", reason="Move it later.")
            proposal = issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-next",
                question="Use the product database?",
                recommendation="Use the product database.",
                why="Lowest operational overhead.",
                if_not="A separate sink becomes in scope now.",
            )

            self.assertEqual("D-next", proposal["target_id"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_evidence_resolve_active_proposal_allows_next_decision_proposal(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Continue after resolving an active proposal",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            for decision_id, title in (("D-first", "Auth mode"), ("D-next", "Audit sink")):
                discover_decision(
                    ai_dir,
                    session_id,
                    {
                        "id": decision_id,
                        "title": title,
                        "priority": "P0",
                        "frontier": "now",
                        "domain": "technical",
                        "question": f"What should we do about {title.lower()}?",
                    },
                )

            issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-first",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )
            resolve_by_evidence(
                ai_dir,
                session_id,
                decision_id="D-first",
                source="codebase",
                summary="Use the existing magic-link flow.",
                evidence_refs=["app/auth.py"],
            )
            proposal = issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-next",
                question="Use the product database?",
                recommendation="Use the product database.",
                why="Lowest operational overhead.",
                if_not="A separate sink becomes in scope now.",
            )

            self.assertEqual("D-next", proposal["target_id"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_issue_proposal_rejects_empty_text_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject empty proposal text",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-empty-proposal",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            kwargs = {
                "decision_id": "D-empty-proposal",
                "question": "Use magic links?",
                "recommendation": "Use magic links.",
                "why": "Smaller MVP surface area.",
                "if_not": "Passwords expand auth scope.",
            }

            for field in ("question", "recommendation", "why", "if_not"):
                with self.subTest(field=field):
                    candidate = dict(kwargs)
                    candidate[field] = " "
                    with self.assertRaisesRegex(ValueError, field):
                        issue_proposal(ai_dir, session_id, **candidate)

            self.assertEqual([], validate_runtime(ai_dir))

    def test_reason_commands_require_non_empty_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject empty reasons",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-empty-reason",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )

            with self.assertRaisesRegex(ValueError, "reason"):
                defer_decision(ai_dir, session_id, decision_id="D-empty-reason", reason="")

            issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-empty-reason",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )
            with self.assertRaisesRegex(ValueError, "reason"):
                reject_proposal(ai_dir, session_id, reason=" ")

            self.assertEqual([], validate_runtime(ai_dir))

    def test_answer_proposal_normalizes_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Normalize answer reasons",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-default-reason",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-default-reason",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )
            answer_proposal(ai_dir, session_id, answer_summary="Use passwords.", reason="   ")

            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-custom-reason",
                    "title": "Audit sink",
                    "priority": "P1",
                    "frontier": "later",
                    "domain": "ops",
                    "question": "Where should audit logs land?",
                },
            )
            issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-custom-reason",
                question="Use the product database?",
                recommendation="Use the product database.",
                why="Cheaper for the milestone.",
                if_not="A separate sink becomes in scope now.",
            )
            answer_proposal(
                ai_dir,
                session_id,
                answer_summary="Use a separate audit sink.",
                reason="custom reason",
            )

            rejected_reasons = [
                event["payload"]["reason"]
                for event in read_event_log(runtime_paths(ai_dir))
                if event["event_type"] == "proposal_rejected"
            ]
            self.assertEqual(
                ["User supplied an alternative answer.", "custom reason"],
                rejected_reasons,
            )
            self.assertEqual([], validate_runtime(ai_dir))

    def test_enrich_decision_accepts_individual_append_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Enrich decisions incrementally",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-enrich",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )

            enriched = enrich_decision(ai_dir, session_id, decision_id="D-enrich", notes_append=["note"])
            self.assertIn("note", enriched["notes"])
            enriched = enrich_decision(
                ai_dir,
                session_id,
                decision_id="D-enrich",
                revisit_triggers_append=["when enterprise launches"],
            )
            self.assertIn("when enterprise launches", enriched["revisit_triggers"])
            enriched = enrich_decision(
                ai_dir,
                session_id,
                decision_id="D-enrich",
                context_append="Extra context.",
            )
            self.assertEqual("Extra context.", enriched["context"])

            event_log = _raw_event_log_text(ai_dir)
            self.assertNotIn('"context_append": null', event_log)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_noop_enrich_decision_still_validates_session_binding(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Validate no-op enrich calls",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-noop-enrich",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )

            decision = enrich_decision(ai_dir, session_id, decision_id="D-noop-enrich")
            self.assertEqual("D-noop-enrich", decision["id"])
            with self.assertRaisesRegex(ValueError, "unknown session"):
                enrich_decision(ai_dir, "S-missing", decision_id="D-noop-enrich")
            with self.assertRaisesRegex(ValueError, "not bound"):
                enrich_decision(ai_dir, session_id, decision_id="D-missing")

            close_session(ai_dir, session_id)
            with self.assertRaisesRegex(ValueError, "closed"):
                enrich_decision(ai_dir, session_id, decision_id="D-noop-enrich")

            self.assertEqual([], validate_runtime(ai_dir))

    def test_resolve_by_evidence_rejects_unknown_source(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Keep evidence sources typed",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Evidence thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-evidence-source",
                    "title": "Existing auth flow",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "Which auth flow already exists?",
                    "resolvable_by": "codebase",
                },
            )

            with self.assertRaisesRegex(ValueError, "invalid evidence source"):
                resolve_by_evidence(
                    ai_dir,
                    session_id,
                    decision_id="D-evidence-source",
                    source="aliens",
                    summary="Found elsewhere.",
                    evidence_refs=[],
                )
            self.assertEqual([], validate_runtime(ai_dir))

    def test_decision_level_commands_are_session_bound(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Keep decision commands session scoped",
                current_milestone="MVP",
            )
            owning_session_id = create_session(ai_dir, context="Auth thread")["session"]["id"]
            other_session_id = create_session(ai_dir, context="Other thread")["session"]["id"]
            discover_decision(
                ai_dir,
                owning_session_id,
                {
                    "id": "D-bound",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )

            with self.assertRaisesRegex(ValueError, "not bound"):
                defer_decision(
                    ai_dir,
                    other_session_id,
                    decision_id="D-bound",
                    reason="Move it later.",
                )
            self.assertEqual(["D-bound"], show_session(ai_dir, owning_session_id)["session"]["session"]["decision_ids"])
            self.assertEqual([], show_session(ai_dir, other_session_id)["session"]["session"]["decision_ids"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_discover_decision_rejects_existing_decision_id(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject duplicate decisions",
                current_milestone="MVP",
            )
            first_session_id = create_session(ai_dir, context="Auth thread")["session"]["id"]
            second_session_id = create_session(ai_dir, context="Other thread")["session"]["id"]
            discover_decision(
                ai_dir,
                first_session_id,
                {
                    "id": "D-duplicate",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )

            with self.assertRaisesRegex(ValueError, "already exists"):
                discover_decision(
                    ai_dir,
                    second_session_id,
                    {
                        "id": "D-duplicate",
                        "title": "Overwrite auth mode",
                        "status": "unresolved",
                        "question": "Can this overwrite the first decision?",
                    },
                )
            self.assertEqual([], show_session(ai_dir, second_session_id)["session"]["session"]["decision_ids"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_discover_decision_rejects_terminal_or_runtime_payloads(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Keep discovery from bypassing state transitions",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Discovery thread")["session"]["id"]

            with self.assertRaisesRegex(ValueError, "statuses"):
                discover_decision(
                    ai_dir,
                    session_id,
                    {
                        "id": "D-injected-accepted",
                        "title": "Injected accepted",
                        "status": "accepted",
                    },
                )
            with self.assertRaisesRegex(ValueError, "statuses"):
                discover_decision(
                    ai_dir,
                    session_id,
                    {
                        "id": "D-injected-evidence",
                        "title": "Injected evidence",
                        "status": "resolved-by-evidence",
                    },
                )
            with self.assertRaisesRegex(ValueError, "accepted_answer"):
                discover_decision(
                    ai_dir,
                    session_id,
                    {
                        "id": "D-injected-answer",
                        "title": "Injected answer",
                        "accepted_answer": {"summary": "Already decided."},
                    },
                )
            with self.assertRaisesRegex(ValueError, "invalidated_by"):
                discover_decision(
                    ai_dir,
                    session_id,
                    {
                        "id": "D-injected-invalidated",
                        "title": "Injected invalidation",
                        "invalidated_by": {"decision_id": "D-other"},
                    },
                )
            self.assertEqual([], show_session(ai_dir, session_id)["session"]["session"]["decision_ids"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_closed_session_rejects_low_level_mutations(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Keep closed sessions read-only",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Closed thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-closed-low-level",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            close_session(ai_dir, session_id)

            with self.assertRaisesRegex(ValueError, "closed"):
                discover_decision(
                    ai_dir,
                    session_id,
                    {
                        "id": "D-after-close",
                        "title": "Late decision",
                        "question": "Should this be allowed?",
                    },
                )
            with self.assertRaisesRegex(ValueError, "closed"):
                resolve_by_evidence(
                    ai_dir,
                    session_id,
                    decision_id="D-closed-low-level",
                    source="codebase",
                    summary="Resolved late.",
                    evidence_refs=["app/auth.py"],
                )
            with self.assertRaisesRegex(ValueError, "closed"):
                defer_decision(
                    ai_dir,
                    session_id,
                    decision_id="D-closed-low-level",
                    reason="Move it later.",
                )
            with self.assertRaisesRegex(ValueError, "closed"):
                update_classification(
                    ai_dir,
                    session_id,
                    domain="technical",
                    abstraction_level="architecture",
                )
            self.assertEqual([], validate_runtime(ai_dir))

    def test_generate_plan_requires_at_least_one_session(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject empty plan inputs",
                current_milestone="MVP",
            )

            with self.assertRaisesRegex(ValueError, "at least one closed session"):
                generate_plan(ai_dir, [])

            self.assertEqual([], validate_runtime(ai_dir))

    def test_close_sessions_generate_plan_and_adr(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Generate an action plan",
                current_milestone="MVP",
            )

            s1 = create_session(ai_dir, context="Auth decisions")["session"]["id"]
            discover_decision(
                ai_dir,
                s1,
                {
                    "id": "D-001",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "kind": "choice",
                    "question": "How should auth work?",
                },
            )
            update_classification(
                ai_dir,
                s1,
                domain="technical",
                abstraction_level="architecture",
                search_terms=["auth"],
            )
            resolve_by_evidence(
                ai_dir,
                s1,
                decision_id="D-001",
                source="codebase",
                summary="Use the existing magic-link flow.",
                evidence_refs=["app/auth.py"],
            )
            close_session(ai_dir, s1)

            s2 = create_session(ai_dir, context="Audit decisions")["session"]["id"]
            discover_decision(
                ai_dir,
                s2,
                {
                    "id": "D-002",
                    "title": "Audit sink",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "kind": "choice",
                    "question": "Where should audit logs land?",
                },
            )
            issue_proposal(
                ai_dir,
                s2,
                decision_id="D-002",
                question="Use the product database?",
                recommendation="Use the product database.",
                why="Lowest operational overhead.",
                if_not="A separate sink becomes in scope now.",
            )
            accept_proposal(ai_dir, s2)
            close_session(ai_dir, s2)

            plan = generate_plan(ai_dir, [s1, s2])
            self.assertEqual("action-plan", plan["status"])
            self.assertEqual("ready", plan["action_plan"]["readiness"])
            self.assertEqual("D-001", plan["action_plan"]["implementation_ready_slices"][0]["decision_id"])
            self.assertEqual("codebase", plan["action_plan"]["implementation_ready_slices"][0]["evidence_source"])
            self.assertTrue(Path(plan["export_path"]).exists())

            adr_path = export_adr(ai_dir, "D-001")
            self.assertTrue(adr_path.exists())
            self.assertEqual([], validate_runtime(ai_dir))

    def test_structured_adr_exports_accepted_and_evidence_decisions_across_domains(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Export structured ADRs",
                current_milestone="MVP",
            )

            ops_session_id = create_session(ai_dir, context="Ops decision")["session"]["id"]
            _accept_runtime_decision(
                ai_dir,
                ops_session_id,
                decision_id="D-ops",
                title="Audit sink",
                domain="ops",
                recommendation="Use the product database.",
            )

            ops_adr_path = export_structured_adr(ai_dir, "D-ops")
            self.assertEqual("structured", ops_adr_path.parent.name)
            ops_adr = ops_adr_path.read_text(encoding="utf-8")
            self.assertIn("# ADR D-ops: Audit sink", ops_adr)
            self.assertIn('domain: "ops"', ops_adr)
            self.assertIn('accepted_via: "ok"', ops_adr)
            self.assertIn("## Alternatives\n\n- none recorded", ops_adr)
            ops_frontmatter = _load_yaml_with_schema(
                _extract_frontmatter(ops_adr),
                "structured-adr-frontmatter.schema.json",
            )
            self.assertEqual([], ops_frontmatter["depends_on"])
            self.assertEqual([], ops_frontmatter["supersedes"])

            data_session_id = create_session(ai_dir, context="Data evidence")["session"]["id"]
            discover_decision(
                ai_dir,
                data_session_id,
                {
                    "id": "D-data",
                    "title": "Warehouse source",
                    "priority": "P1",
                    "frontier": "later",
                    "domain": "data",
                    "kind": "choice",
                    "question": "Where should warehouse facts come from?",
                },
            )
            resolve_by_evidence(
                ai_dir,
                data_session_id,
                decision_id="D-data",
                source="docs",
                summary="Use the existing warehouse extract.",
                evidence_refs=["docs/warehouse.md"],
            )

            data_adr = export_structured_adr(ai_dir, "D-data").read_text(encoding="utf-8")
            self.assertIn('status: "resolved-by-evidence"', data_adr)
            self.assertIn('accepted_via: "evidence"', data_adr)
            self.assertIn("- docs/warehouse.md", data_adr)
            _load_yaml_with_schema(
                _extract_frontmatter(data_adr),
                "structured-adr-frontmatter.schema.json",
            )
            self.assertEqual([], validate_runtime(ai_dir))

    def test_structured_adr_frontmatter_schema_handles_yaml_edge_cases(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Validate structured ADR frontmatter",
                current_milestone="MVP",
            )

            session_id = create_session(ai_dir, context="Structured ADR schema")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-prereq",
                    "title": "前提: config [base]",
                    "priority": "P2",
                    "frontier": "later",
                    "domain": "technical",
                    "kind": "dependency",
                    "question": "What prerequisite is needed?",
                },
            )
            defer_decision(
                ai_dir,
                session_id,
                decision_id="D-prereq",
                reason="Track the prerequisite in the register.",
            )
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-old",
                    "title": "Old ADR",
                    "priority": "P1",
                    "frontier": "later",
                    "domain": "technical",
                    "kind": "choice",
                    "question": "What old ADR should be replaced?",
                },
            )
            resolve_by_evidence(
                ai_dir,
                session_id,
                decision_id="D-old",
                source="docs",
                summary="Use the old ADR shape.",
                evidence_refs=["docs/old.md"],
            )

            title = "構造化: ADR #1 \"quote\" 'single' [array] | pipe"
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-weird",
                    "title": title,
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "kind": "choice",
                    "question": "How should structured ADR YAML render?",
                    "context": "First line of context.\nSecond line with 日本語 and : # [ ] |.",
                    "depends_on": ["D-prereq"],
                },
            )
            resolve_by_evidence(
                ai_dir,
                session_id,
                decision_id="D-weird",
                source="docs",
                summary="Use structured ADR.\nKeep YAML machine readable.",
                evidence_refs=["docs/adr.md", "docs/adr:edge#case.md"],
            )
            invalidate_decision(
                ai_dir,
                session_id,
                decision_id="D-old",
                invalidated_by_decision_id="D-weird",
                reason="Structured ADR supersedes the old ADR.",
            )

            adr_path = export_structured_adr(ai_dir, "D-weird")
            adr_text = adr_path.read_text(encoding="utf-8")
            frontmatter = _load_yaml_with_schema(
                _extract_frontmatter(adr_text),
                "structured-adr-frontmatter.schema.json",
            )
            self.assertEqual(title, frontmatter["title"])
            self.assertEqual(["D-prereq"], frontmatter["depends_on"])
            self.assertEqual(["D-old"], frontmatter["supersedes"])
            self.assertEqual(["docs/adr.md", "docs/adr:edge#case.md"], frontmatter["evidence_refs"])
            self.assertIsNone(frontmatter["risk"]["technical"])
            self.assertIsNone(frontmatter["risk"]["operational"])
            self.assertEqual("decide-me", frontmatter["audit"]["source"])
            self.assertIn("Use structured ADR.\nKeep YAML machine readable.", adr_text)

            register_path = export_decision_register(ai_dir)
            register_payload = _load_yaml_with_schema(
                register_path.read_text(encoding="utf-8"),
                "decision-register.schema.json",
            )
            by_id = {decision["id"]: decision for decision in register_payload["decisions"]}
            self.assertEqual(
                "Use structured ADR.\nKeep YAML machine readable.",
                by_id["D-weird"]["summary"],
            )

            before_validate = adr_path.read_text(encoding="utf-8")
            repo_root = Path(__file__).resolve().parents[2]
            validate_cli = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "validate-state",
                    "--ai-dir",
                    ai_dir,
                    "--full",
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, validate_cli.returncode, validate_cli.stderr)
            after_validate = export_structured_adr(ai_dir, "D-weird").read_text(encoding="utf-8")
            self.assertEqual(before_validate, after_validate)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_decision_register_and_structured_adr_handle_invalidated_and_stable_output(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Export decision register",
                current_milestone="MVP",
            )

            accepted_session_id = create_session(ai_dir, context="Accepted product decision")[
                "session"
            ]["id"]
            _accept_runtime_decision(
                ai_dir,
                accepted_session_id,
                decision_id="D-001",
                title="Release shape",
                domain="product",
                recommendation="Ship the planner-only release first.",
            )

            deferred_session_id = create_session(ai_dir, context="Deferred UX decision")["session"][
                "id"
            ]
            discover_decision(
                ai_dir,
                deferred_session_id,
                {
                    "id": "D-050",
                    "title": "Visual theme",
                    "priority": "P2",
                    "frontier": "later",
                    "domain": "ux",
                    "kind": "choice",
                    "question": "Which visual theme should exports use?",
                },
            )
            defer_decision(
                ai_dir,
                deferred_session_id,
                decision_id="D-050",
                reason="Defer visual polish until export contracts settle.",
            )

            old_session_id = create_session(ai_dir, context="Old technical decision")["session"]["id"]
            _accept_runtime_decision(
                ai_dir,
                old_session_id,
                decision_id="D-200",
                title="Legacy ADR shape",
                domain="technical",
                recommendation="Use the legacy ADR shape.",
            )

            replacement_session_id = create_session(ai_dir, context="Replacement decision")[
                "session"
            ]["id"]
            _accept_runtime_decision(
                ai_dir,
                replacement_session_id,
                decision_id="D-100",
                title="Structured ADR shape",
                domain="technical",
                recommendation="Use the structured ADR shape.",
            )
            invalidate_decision(
                ai_dir,
                replacement_session_id,
                decision_id="D-200",
                invalidated_by_decision_id="D-100",
                reason="Structured ADR supersedes the legacy ADR shape.",
            )

            with self.assertRaisesRegex(ValueError, "invalidated"):
                export_structured_adr(ai_dir, "D-200")

            invalidated_adr = export_structured_adr(
                ai_dir, "D-200", include_invalidated=True
            ).read_text(encoding="utf-8")
            self.assertIn('status: "invalidated"', invalidated_adr)
            self.assertIn('superseded_by: "D-100"', invalidated_adr)
            self.assertIn("Use the legacy ADR shape.", invalidated_adr)

            register_path = export_decision_register(ai_dir)
            register_text = register_path.read_text(encoding="utf-8")
            self.assertNotIn('id: "D-200"', register_text)
            self.assertLess(register_text.index('id: "D-001"'), register_text.index('id: "D-050"'))
            self.assertLess(register_text.index('id: "D-050"'), register_text.index('id: "D-100"'))

            repo_root = Path(__file__).resolve().parents[2]
            validate_cli = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "validate-state",
                    "--ai-dir",
                    ai_dir,
                    "--full",
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, validate_cli.returncode, validate_cli.stderr)

            rerendered_register = export_decision_register(ai_dir).read_text(encoding="utf-8")
            self.assertEqual(register_text, rerendered_register)

            register_with_invalidated = export_decision_register(
                ai_dir, include_invalidated=True
            ).read_text(encoding="utf-8")
            self.assertIn('id: "D-200"', register_with_invalidated)
            self.assertIn('superseded_by: "D-100"', register_with_invalidated)

            cli_markdown = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "export-decision-register",
                    "--ai-dir",
                    ai_dir,
                    "--format",
                    "markdown",
                    "--include-invalidated",
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, cli_markdown.returncode, cli_markdown.stderr)
            markdown_payload = json.loads(cli_markdown.stdout)
            markdown_path = Path(markdown_payload["path"])
            self.assertTrue(markdown_path.exists())
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("| D-200 | invalidated | technical |", markdown)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_project_wide_invalidation_hides_closed_decision_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Hide invalidated decisions from normal outputs",
                current_milestone="MVP",
            )

            old_session_id = create_session(ai_dir, context="Legacy auth decision")["session"]["id"]
            discover_decision(
                ai_dir,
                old_session_id,
                {
                    "id": "D-100",
                    "title": "Legacy auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "kind": "choice",
                    "question": "Should the MVP use magic links?",
                    "resolvable_by": "codebase",
                },
            )
            resolve_by_evidence(
                ai_dir,
                old_session_id,
                decision_id="D-100",
                source="codebase",
                summary="Use the existing magic-link flow.",
                evidence_refs=["app/auth.py"],
            )
            close_session(ai_dir, old_session_id)

            replacement_session_id = create_session(ai_dir, context="Replacement auth decision")["session"]["id"]
            discover_decision(
                ai_dir,
                replacement_session_id,
                {
                    "id": "D-101",
                    "title": "Replacement auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "kind": "choice",
                    "question": "Should the MVP use passwords?",
                    "resolvable_by": "codebase",
                },
            )
            resolve_by_evidence(
                ai_dir,
                replacement_session_id,
                decision_id="D-101",
                source="codebase",
                summary="Use the password flow.",
                evidence_refs=["app/password_auth.py"],
            )
            close_session(ai_dir, replacement_session_id)

            repo_root = Path(__file__).resolve().parents[2]
            cli_help = subprocess.run(
                [sys.executable, "scripts/decide_me.py", "-h"],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, cli_help.returncode, cli_help.stderr)
            self.assertIn("resolve-decision-supersession", cli_help.stdout)
            self.assertNotIn("invalidate-decision", cli_help.stdout)

            resolved = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "resolve-decision-supersession",
                    "--ai-dir",
                    ai_dir,
                    "--session-id",
                    replacement_session_id,
                    "--superseded-decision-id",
                    "D-100",
                    "--superseding-decision-id",
                    "D-101",
                    "--reason",
                    "Superseded by the later auth decision.",
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, resolved.returncode, resolved.stderr)
            resolution_payload = json.loads(resolved.stdout)
            self.assertEqual("ok", resolution_payload["status"])
            self.assertEqual("decision-supersession", resolution_payload["resolution"]["kind"])
            self.assertEqual("D-101", resolution_payload["resolution"]["winning_decision_id"])

            rebuild_and_persist(ai_dir)

            shown = show_session(ai_dir, old_session_id)
            self.assertEqual([], shown["session"]["session"]["decision_ids"])
            self.assertEqual([], shown["session"]["close_summary"]["accepted_decisions"])

            plan = generate_plan(ai_dir, [old_session_id, replacement_session_id])
            self.assertEqual("action-plan", plan["status"])
            self.assertEqual(["D-101"], [item["decision_id"] for item in plan["action_plan"]["action_slices"]])
            self.assertEqual(
                ["D-101"],
                [item["decision_id"] for item in plan["action_plan"]["implementation_ready_slices"]],
            )

            with self.assertRaisesRegex(ValueError, "not accepted"):
                export_adr(ai_dir, "D-100")

            event_log = _raw_event_log_text(ai_dir)
            self.assertIn('"event_type": "decision_invalidated"', event_log)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_invalidation_recomputes_close_summary_readiness(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Recompute stale close summary readiness",
                current_milestone="MVP",
            )

            blocker_session_id = create_session(ai_dir, context="Blocked work")["session"]["id"]
            discover_decision(
                ai_dir,
                blocker_session_id,
                {
                    "id": "D-blocker",
                    "title": "Blocking decision",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "What blocks the MVP?",
                },
            )
            closed_blocker = close_session(ai_dir, blocker_session_id)
            self.assertEqual("blocked", closed_blocker["close_summary"]["readiness"])

            replacement_session_id = create_session(ai_dir, context="Replacement")["session"]["id"]
            discover_decision(
                ai_dir,
                replacement_session_id,
                {
                    "id": "D-replacement",
                    "title": "Replacement decision",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "What supersedes the blocker?",
                    "resolvable_by": "codebase",
                },
            )
            resolve_by_evidence(
                ai_dir,
                replacement_session_id,
                decision_id="D-replacement",
                source="codebase",
                summary="Use the replacement.",
                evidence_refs=["app/replacement.py"],
            )
            invalidate_decision(
                ai_dir,
                replacement_session_id,
                decision_id="D-blocker",
                invalidated_by_decision_id="D-replacement",
                reason="Superseded by a replacement decision.",
            )

            shown = show_session(ai_dir, blocker_session_id)["session"]
            self.assertEqual("ready", shown["close_summary"]["readiness"])
            self.assertEqual([], shown["close_summary"]["unresolved_blockers"])
            self.assertEqual([], validate_runtime(ai_dir))

            risk_session_id = create_session(ai_dir, context="Risk work")["session"]["id"]
            discover_decision(
                ai_dir,
                risk_session_id,
                {
                    "id": "D-risk",
                    "title": "Risk decision",
                    "kind": "risk",
                    "priority": "P1",
                    "frontier": "now",
                    "domain": "ops",
                    "question": "What risk remains?",
                },
            )
            closed_risk = close_session(ai_dir, risk_session_id)
            self.assertEqual("conditional", closed_risk["close_summary"]["readiness"])
            invalidate_decision(
                ai_dir,
                replacement_session_id,
                decision_id="D-risk",
                invalidated_by_decision_id="D-replacement",
                reason="Superseded by a replacement decision.",
            )

            shown_risk = show_session(ai_dir, risk_session_id)["session"]
            self.assertEqual("ready", shown_risk["close_summary"]["readiness"])
            self.assertEqual([], shown_risk["close_summary"]["unresolved_risks"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_invalidation_does_not_bind_invalidating_decision_to_unrelated_session(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Keep invalidation project-wide",
                current_milestone="MVP",
            )
            old_session_id = create_session(ai_dir, context="Old decision")["session"]["id"]
            discover_decision(
                ai_dir,
                old_session_id,
                {
                    "id": "D-old",
                    "title": "Old auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "Should the MVP use magic links?",
                },
            )
            close_session(ai_dir, old_session_id)

            new_session_id = create_session(ai_dir, context="New decision")["session"]["id"]
            discover_decision(
                ai_dir,
                new_session_id,
                {
                    "id": "D-new",
                    "title": "New auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "Should the MVP use passwords?",
                    "resolvable_by": "codebase",
                },
            )
            resolve_by_evidence(
                ai_dir,
                new_session_id,
                decision_id="D-new",
                source="codebase",
                summary="Use the password flow.",
                evidence_refs=["app/password_auth.py"],
            )

            with self.assertRaisesRegex(ValueError, "not bound"):
                invalidate_decision(
                    ai_dir,
                    old_session_id,
                    decision_id="D-old",
                    invalidated_by_decision_id="D-new",
                    reason="Superseded by the password decision.",
                )

            invalidate_decision(
                ai_dir,
                new_session_id,
                decision_id="D-old",
                invalidated_by_decision_id="D-new",
                reason="Superseded by the password decision.",
            )

            old_session = show_session(ai_dir, old_session_id)["session"]
            self.assertEqual([], old_session["session"]["decision_ids"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_invalidation_chain_remains_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Allow chained replacement decisions",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Replacement chain")["session"]["id"]
            for decision_id in ("D-old", "D-replacement", "D-final"):
                discover_decision(
                    ai_dir,
                    session_id,
                    {
                        "id": decision_id,
                        "title": decision_id,
                        "priority": "P0",
                        "frontier": "now",
                        "domain": "technical",
                        "question": f"What should {decision_id} decide?",
                    },
                )
                issue_proposal(
                    ai_dir,
                    session_id,
                    decision_id=decision_id,
                    question=f"Use {decision_id}?",
                    recommendation=f"Use {decision_id}.",
                    why="It is the current replacement.",
                    if_not="Keep the earlier decision.",
                )
                accept_proposal(ai_dir, session_id)

            invalidate_decision(
                ai_dir,
                session_id,
                decision_id="D-old",
                invalidated_by_decision_id="D-replacement",
                reason="Superseded by the replacement.",
            )
            invalidate_decision(
                ai_dir,
                session_id,
                decision_id="D-replacement",
                invalidated_by_decision_id="D-final",
                reason="Superseded by the final replacement.",
            )

            shown = show_session(ai_dir, session_id)["session"]
            self.assertEqual(["D-final"], shown["session"]["decision_ids"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_advance_session_skips_invalidated_active_proposal(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Skip invalidated active proposals",
                current_milestone="MVP",
            )

            questioned_session_id = create_session(ai_dir, context="Auth thread")["session"]["id"]
            discover_decision(
                ai_dir,
                questioned_session_id,
                {
                    "id": "D-110",
                    "title": "Old auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "kind": "choice",
                    "question": "Should the MVP use magic links?",
                },
            )
            discover_decision(
                ai_dir,
                questioned_session_id,
                {
                    "id": "D-111",
                    "title": "Audit sink",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "kind": "choice",
                    "question": "Where should audit logs land?",
                },
            )
            proposal = issue_proposal(
                ai_dir,
                questioned_session_id,
                decision_id="D-110",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP scope.",
                if_not="Passwords expand scope now.",
            )

            replacement_session_id = create_session(ai_dir, context="Replacement auth thread")["session"]["id"]
            discover_decision(
                ai_dir,
                replacement_session_id,
                {
                    "id": "D-112",
                    "title": "Replacement auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "kind": "choice",
                    "question": "Should the MVP use passwords?",
                    "resolvable_by": "codebase",
                },
            )
            resolve_by_evidence(
                ai_dir,
                replacement_session_id,
                decision_id="D-112",
                source="codebase",
                summary="Use the password flow.",
                evidence_refs=["app/password_auth.py"],
            )

            invalidate_decision(
                ai_dir,
                replacement_session_id,
                decision_id="D-110",
                invalidated_by_decision_id="D-112",
                reason="Superseded by the accepted password auth decision.",
            )

            turn = advance_session(ai_dir, questioned_session_id, repo_root=tmp)
            self.assertEqual("question", turn["status"])
            self.assertEqual("D-111", turn["decision_id"])

            shown = show_session(ai_dir, questioned_session_id)
            self.assertEqual(["D-111"], shown["session"]["session"]["decision_ids"])
            self.assertEqual("D-111", shown["display"]["active_decision_id"])

            with self.assertRaisesRegex(ValueError, "invalidated"):
                accept_proposal(ai_dir, questioned_session_id, proposal_id=proposal["proposal_id"])

            self.assertEqual([], validate_runtime(ai_dir))

    def test_classification_search_and_lazy_compatibility_backfill(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Exercise taxonomy-aware search",
                current_milestone="MVP",
            )

            session = create_session(ai_dir, context="Authentication choices")
            session_id = session["session"]["id"]
            classification = classify_session(
                ai_dir,
                session_id,
                domain="technical",
                abstraction_level="architecture",
                candidate_terms=["email link"],
                source_refs=["latest_summary"],
            )
            self.assertEqual("technical", classification["classification"]["domain"])
            self.assertIn("latest_summary", classification["classification"]["source_refs"])

            listing = list_sessions(
                ai_dir,
                domains=["technical"],
                abstraction_levels=["architecture"],
                tag_terms=["email link"],
            )
            self.assertEqual(1, listing["count"])
            self.assertEqual(session_id, listing["sessions"][0]["session_id"])

            close_session(ai_dir, session_id)

            now = utc_now()

            def builder(bundle: dict[str, object]) -> list[dict[str, object]]:
                return [
                    {
                        "session_id": session_id,
                        "event_type": "taxonomy_extended",
                        "payload": {
                            "nodes": [
                                {
                                    "id": "tag:magic-links",
                                    "axis": "tag",
                                    "label": "magic links",
                                    "aliases": ["authentication"],
                                    "parent_id": None,
                                    "replaced_by": [],
                                    "status": "active",
                                    "created_at": now,
                                    "updated_at": now,
                                },
                                {
                                    "id": "tag:email-link",
                                    "axis": "tag",
                                    "label": "email link",
                                    "aliases": [],
                                    "parent_id": None,
                                    "replaced_by": ["tag:magic-links"],
                                    "status": "replaced",
                                    "created_at": bundle["taxonomy_state"]["nodes"][-1]["created_at"],
                                    "updated_at": now,
                                },
                            ]
                        },
                    }
                ]

            transact(ai_dir, builder)
            events_before_read = len(read_event_log(runtime_paths(ai_dir)))

            display = show_session(ai_dir, session_id)
            self.assertIn("tag:magic-links", display["session"]["classification"]["compatibility_tags"])
            self.assertIn("tag:magic-links", display["compatibility_tag_refs_added"])

            listing = list_sessions(ai_dir, tag_terms=["authentication"])
            self.assertEqual(1, listing["count"])
            self.assertGreaterEqual(len(listing["backfilled"]), 0)
            self.assertEqual(events_before_read, len(read_event_log(runtime_paths(ai_dir))))
            self.assertEqual([], validate_runtime(ai_dir))

    def test_read_only_compatibility_backfill_does_not_stale_active_proposal(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Keep reads side-effect free",
                current_milestone="MVP",
            )
            closed_session_id = create_session(ai_dir, context="Closed tagged work")["session"]["id"]
            classify_session(
                ai_dir,
                closed_session_id,
                domain="technical",
                abstraction_level="architecture",
                candidate_terms=["email link"],
                source_refs=["latest_summary"],
            )
            close_session(ai_dir, closed_session_id)
            now = utc_now()

            def builder(bundle: dict[str, object]) -> list[dict[str, object]]:
                return [
                    {
                        "session_id": closed_session_id,
                        "event_type": "taxonomy_extended",
                        "payload": {
                            "nodes": [
                                {
                                    "id": "tag:magic-links",
                                    "axis": "tag",
                                    "label": "magic links",
                                    "aliases": ["authentication"],
                                    "parent_id": None,
                                    "replaced_by": [],
                                    "status": "active",
                                    "created_at": now,
                                    "updated_at": now,
                                },
                                {
                                    "id": "tag:email-link",
                                    "axis": "tag",
                                    "label": "email link",
                                    "aliases": [],
                                    "parent_id": None,
                                    "replaced_by": ["tag:magic-links"],
                                    "status": "replaced",
                                    "created_at": bundle["taxonomy_state"]["nodes"][-1]["created_at"],
                                    "updated_at": now,
                                },
                            ]
                        },
                    }
                ]

            transact(ai_dir, builder)
            active_session_id = create_session(ai_dir, context="Active work")["session"]["id"]
            discover_decision(
                ai_dir,
                active_session_id,
                {
                    "id": "D-active",
                    "title": "Auth mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "question": "How should auth work?",
                },
            )
            issue_proposal(
                ai_dir,
                active_session_id,
                decision_id="D-active",
                question="Use magic links?",
                recommendation="Use magic links.",
                why="Smaller MVP surface area.",
                if_not="Passwords expand auth scope.",
            )
            event_count = len(read_event_log(runtime_paths(ai_dir)))
            show_session(ai_dir, closed_session_id)
            list_sessions(ai_dir, tag_terms=["authentication"])

            self.assertEqual(event_count, len(read_event_log(runtime_paths(ai_dir))))
            accepted = accept_proposal(ai_dir, active_session_id)
            self.assertEqual("accepted", accepted["status"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_advance_session_returns_repo_evidence_candidates_then_handles_ok_reply(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            (root / "app" / "nested").mkdir()
            (root / "app" / "auth.py").write_text(
                "def login():\n    return 'magic link auth flow'\n",
                encoding="utf-8",
            )
            (root / "app" / "z_auth.py").write_text(
                "def login_backup():\n    return 'magic link auth flow'\n",
                encoding="utf-8",
            )
            (root / "app" / "nested" / "magic.py").write_text(
                "def nested_login():\n    return 'magic link auth flow'\n",
                encoding="utf-8",
            )
            (root / "app" / "other.py").write_text(
                "def other_login():\n    return 'magic link auth flow'\n",
                encoding="utf-8",
            )
            ai_dir = str(root / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Advance interview turns",
                current_milestone="MVP",
            )

            session_id = create_session(ai_dir, context="MVP decisions")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-001",
                    "title": "Magic link auth",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "resolvable_by": "codebase",
                    "question": "Should the MVP use the existing magic-link flow?",
                    "context": "Use the current auth implementation if possible.",
                    "options": [{"summary": "Use the existing magic-link flow."}],
                },
            )
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-002",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "resolvable_by": "human",
                    "question": "How long should audit logs be retained?",
                    "context": "Retention affects compliance scope.",
                    "options": [{"summary": "Start with 30 days."}],
                },
            )

            turn = advance_session(ai_dir, session_id, repo_root=root)
            self.assertEqual("question", turn["status"])
            self.assertEqual("D-001", turn["decision_id"])
            self.assertEqual([], turn["auto_resolved"])
            self.assertEqual(1, len(turn["evidence_candidates"]))
            self.assertEqual("D-001", turn["evidence_candidates"][0]["decision_id"])
            self.assertEqual("codebase", turn["evidence_candidates"][0]["source"])
            self.assertEqual(
                ["app/auth.py", "app/nested/magic.py", "app/other.py"],
                turn["evidence_candidates"][0]["evidence_refs"],
            )
            self.assertIn("Evidence candidates (not applied automatically):", turn["message"])
            self.assertIn("candidate answer:", turn["message"])
            self.assertNotIn("Resolved by evidence: D-001", turn["message"])

            event_count = len(read_event_log(runtime_paths(ai_dir)))
            repeated_turn = advance_session(ai_dir, session_id, repo_root=root)
            self.assertTrue(repeated_turn["reused_active_proposal"])
            self.assertEqual(turn["evidence_candidates"], repeated_turn["evidence_candidates"])
            self.assertEqual(event_count, len(read_event_log(runtime_paths(ai_dir))))

            reply = handle_reply(ai_dir, session_id, "OK", repo_root=root)
            self.assertEqual("accepted", reply["status"])
            self.assertEqual("question", reply["next_turn"]["status"])
            self.assertEqual("D-002", reply["next_turn"]["decision_id"])
            self.assertIn("Accepted: D-001", reply["message"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_codebase_evidence_ignores_single_keyword_hits(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            (root / "app" / "auth.py").write_text(
                "def login():\n    return 'auth enabled'\n",
                encoding="utf-8",
            )
            ai_dir = str(root / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Avoid weak evidence hits",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Auth decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-auth",
                    "title": "Auth",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "resolvable_by": "codebase",
                    "question": "Should auth be enabled?",
                    "options": [{"summary": "Use auth."}],
                },
            )

            turn = advance_session(ai_dir, session_id, repo_root=root)

            self.assertEqual("question", turn["status"])
            self.assertEqual("D-auth", turn["decision_id"])
            self.assertEqual([], turn["auto_resolved"])
            self.assertEqual([], turn["evidence_candidates"])
            self.assertEqual("proposed", turn["decision"]["status"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_project_state_schema_covers_runtime_projection_shape(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "project-state.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        project_properties = schema["properties"]["project"]["properties"]
        for key in ("name", "objective", "current_milestone", "stop_rule"):
            self.assertEqual("string", project_properties[key]["type"])
            self.assertEqual(1, project_properties[key]["minLength"])

        state_properties = schema["properties"]["state"]["properties"]
        self.assertEqual("string", state_properties["project_head"]["type"])
        self.assertEqual(1, state_properties["project_head"]["minLength"])
        self.assertEqual("string", state_properties["updated_at"]["type"])
        self.assertEqual("date-time", state_properties["updated_at"]["format"])

        decision_items = schema["properties"]["decisions"]["items"]
        decision_properties = decision_items["properties"]
        self.assertEqual(
            ["choice", "constraint", "risk", "dependency"],
            decision_properties["kind"]["enum"],
        )
        self.assertIn("technical", decision_properties["domain"]["enum"])
        self.assertIn("codebase", decision_properties["resolvable_by"]["enum"])
        self.assertIn("hard-to-reverse", decision_properties["reversibility"]["enum"])
        self.assertEqual("string", decision_properties["depends_on"]["items"]["type"])
        self.assertEqual("string", decision_properties["resolved_by_evidence"]["properties"]["evidence_refs"]["items"]["type"])

        all_of = decision_items["allOf"]
        accepted_branch = next(
            branch
            for branch in all_of
            if branch["if"]["properties"]["status"].get("const") == "accepted"
        )
        accepted = accepted_branch["then"]["properties"]["accepted_answer"]["properties"]
        self.assertEqual({"type": "string", "minLength": 1}, accepted["summary"])
        self.assertEqual({"type": "string", "format": "date-time"}, accepted["accepted_at"])
        self.assertEqual(["ok", "explicit"], accepted["accepted_via"]["enum"])
        self.assertEqual({"type": "string", "minLength": 1}, accepted["proposal_id"])

        evidence_branch = next(
            branch
            for branch in all_of
            if branch["if"]["properties"]["status"].get("const") == "resolved-by-evidence"
        )
        evidence_accepted = evidence_branch["then"]["properties"]["accepted_answer"]["properties"]
        evidence_payload = evidence_branch["then"]["properties"]["resolved_by_evidence"]["properties"]
        self.assertEqual("evidence", evidence_accepted["accepted_via"]["const"])
        self.assertEqual({"type": "string", "minLength": 1}, evidence_payload["summary"])
        self.assertEqual({"type": "string", "format": "date-time"}, evidence_payload["resolved_at"])
        self.assertIn("existing-decisions", evidence_payload["source"]["enum"])
        self.assertNotIn(None, evidence_payload["source"]["enum"])

        open_branch = next(
            branch
            for branch in all_of
            if "unresolved" in branch["if"]["properties"]["status"].get("enum", [])
        )
        open_then = open_branch["then"]["properties"]
        self.assertEqual("null", open_then["accepted_answer"]["properties"]["summary"]["type"])
        self.assertEqual("null", open_then["resolved_by_evidence"]["properties"]["summary"]["type"])
        # Cross-field equality constraints are enforced by validate_project_state().

    def test_cli_bootstrap_works_with_pythonpath_repo_root(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            env = dict(os.environ)
            env["PYTHONPATH"] = "."

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "bootstrap",
                    "--ai-dir",
                    ai_dir,
                    "--project-name",
                    "Demo",
                    "--objective",
                    "Exercise CLI bootstrap",
                    "--current-milestone",
                    "MVP",
                ],
                cwd=repo_root,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_validate_runtime_reports_malformed_event_log(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            event_dir = ai_dir / "events" / "system"
            event_dir.mkdir(parents=True)
            (event_dir / "T-bad.jsonl").write_text("{bad json\n", encoding="utf-8")

            issues = validate_runtime(str(ai_dir))
            self.assertEqual(1, len(issues))
            self.assertIn("events/system/T-bad.jsonl line 1 contains malformed JSON", issues[0])

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/decide_me.py",
                    "validate-state",
                    "--ai-dir",
                    str(ai_dir),
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(1, completed.returncode)
            payload = json.loads(completed.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("events/system/T-bad.jsonl line 1 contains malformed JSON", payload["issues"][0])

    def test_cli_validate_state_cached_is_explicit_opt_in(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                str(ai_dir),
                project_name="Demo",
                objective="Validate default mode",
                current_milestone="MVP",
            )
            event_dir = ai_dir / "events" / "system"
            (event_dir / "T-bad.jsonl").write_text("{bad json\n", encoding="utf-8")

            def run_validate(*mode: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        sys.executable,
                        "scripts/decide_me.py",
                        "validate-state",
                        "--ai-dir",
                        str(ai_dir),
                        *mode,
                    ],
                    cwd=repo_root,
                    check=False,
                    capture_output=True,
                    text=True,
                )

            for mode in ((), ("--full",)):
                with self.subTest(mode=mode):
                    completed = run_validate(*mode)
                    self.assertEqual(1, completed.returncode)
                    payload = json.loads(completed.stdout)
                    self.assertFalse(payload["ok"])
                    self.assertIn("events/system/T-bad.jsonl line 1 contains malformed JSON", payload["issues"][0])

            for mode in (("--cached",), ("--fast",)):
                with self.subTest(mode=mode):
                    completed = run_validate(*mode)
                    self.assertEqual(0, completed.returncode, completed.stderr)
                    payload = json.loads(completed.stdout)
                    self.assertTrue(payload["ok"])
                    self.assertEqual([], payload["issues"])

    def test_validate_runtime_rejects_legacy_event_log(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            ai_dir.mkdir(parents=True)
            (ai_dir / "event-log.jsonl").write_text("", encoding="utf-8")

            issues = validate_runtime(str(ai_dir))
            self.assertEqual(1, len(issues))
            self.assertIn("legacy event-log.jsonl is unsupported in this runtime layout", issues[0])
            self.assertIn("automatic migration is not available", issues[0])

    def test_load_runtime_rejects_legacy_event_log_even_with_valid_cache(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                str(ai_dir),
                project_name="Demo",
                objective="Reject legacy source",
                current_milestone="MVP",
            )
            (ai_dir / "event-log.jsonl").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(
                StateValidationError,
                "legacy event-log.jsonl is unsupported in this runtime layout",
            ):
                load_runtime(runtime_paths(ai_dir))

    def test_auto_project_head_proposal_is_not_immediately_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Keep proposal heads stable",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Decision thread")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {"id": "D-head", "title": "Head decision", "priority": "P0", "frontier": "now"},
            )
            issue_proposal(
                ai_dir,
                session_id,
                decision_id="D-head",
                question="Use the current head?",
                recommendation="Use the current head.",
                why="It validates project_head hashing.",
                if_not="The proposal becomes stale immediately.",
            )

            bundle = rebuild_and_persist(ai_dir)
            proposal = bundle["sessions"][session_id]["working_state"]["active_proposal"]
            self.assertEqual(bundle["project_state"]["state"]["project_head"], proposal["based_on_project_head"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_concurrent_cli_bootstrap_leaves_one_valid_runtime(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            command = [
                sys.executable,
                "scripts/decide_me.py",
                "bootstrap",
                "--ai-dir",
                ai_dir,
                "--project-name",
                "Demo",
                "--objective",
                "Exercise bootstrap locking",
                "--current-milestone",
                "MVP",
            ]
            first = subprocess.Popen(
                command,
                cwd=repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            second = subprocess.Popen(
                command,
                cwd=repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            first_stdout, first_stderr = first.communicate(timeout=15)
            second_stdout, second_stderr = second.communicate(timeout=15)

            self.assertEqual([0, 1], sorted([first.returncode, second.returncode]))
            combined = "\n".join([first_stdout, first_stderr, second_stdout, second_stderr])
            self.assertIn("runtime already exists", combined)
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_accepts_freeform_alternative_answer(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Capture free-form answers",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Retention decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-010",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "resolvable_by": "human",
                    "question": "How long should audit logs be retained?",
                    "context": "Retention affects compliance scope.",
                    "options": [{"summary": "Start with 30 days."}],
                },
            )

            turn = advance_session(ai_dir, session_id, repo_root=tmp)
            self.assertEqual("question", turn["status"])

            reply = handle_reply(
                ai_dir,
                session_id,
                "Use 90 days because enterprise customers will expect it.",
                repo_root=tmp,
            )
            self.assertEqual("accepted", reply["status"])
            self.assertEqual(
                "Use 90 days because enterprise customers will expect it.",
                reply["decision"]["accepted_answer"]["summary"],
            )
            self.assertEqual("complete", reply["next_turn"]["status"])
            self.assertIn(
                "Accepted answer overrides the last recommendation.",
                reply["decision"]["notes"],
            )
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_rejects_negative_only_reply(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Reject proposal with free-form no",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Retention decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-011",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "resolvable_by": "human",
                    "question": "How long should audit logs be retained?",
                    "context": "Retention affects compliance scope.",
                    "options": [{"summary": "Start with 30 days."}],
                },
            )

            advance_session(ai_dir, session_id, repo_root=tmp)
            reply = handle_reply(ai_dir, session_id, "No", repo_root=tmp)
            self.assertEqual("rejected", reply["status"])
            self.assertIn("Rejected: D-011", reply["message"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_accepts_affirming_freeform_phrase(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Accept affirming phrase",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Retention decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-012",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "resolvable_by": "human",
                    "question": "How long should audit logs be retained?",
                    "context": "Retention affects compliance scope.",
                    "options": [{"summary": "Start with 30 days."}],
                },
            )

            advance_session(ai_dir, session_id, repo_root=tmp)
            reply = handle_reply(ai_dir, session_id, "Sounds good", repo_root=tmp)
            self.assertEqual("accepted", reply["status"])
            self.assertEqual("Start with 30 days.", reply["decision"]["accepted_answer"]["summary"])
            self.assertEqual("explicit", reply["decision"]["accepted_answer"]["accepted_via"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_extracts_constraints_and_follow_up_decisions(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Extract constraints and follow-up decisions",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Auth decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-020",
                    "title": "Authentication mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "resolvable_by": "human",
                    "question": "Should the MVP use magic links?",
                    "context": "Choose the initial authentication mode.",
                    "options": [{"summary": "Use magic links for the MVP."}],
                },
            )

            advance_session(ai_dir, session_id, repo_root=tmp)
            reply = handle_reply(
                ai_dir,
                session_id,
                "Sounds good, but only for enterprise tenants, and we also need password reset before launch.",
                repo_root=tmp,
            )
            self.assertEqual("accepted", reply["status"])
            self.assertEqual(
                "Use magic links for the MVP.",
                reply["decision"]["accepted_answer"]["summary"],
            )
            self.assertEqual(["only for enterprise tenants"], reply["captured_constraints"])
            self.assertEqual(1, len(reply["discovered_decisions"]))
            discovered = reply["discovered_decisions"][0]
            self.assertEqual("technical", discovered["domain"])
            self.assertEqual("choice", discovered["kind"])
            self.assertEqual("P0", discovered["priority"])
            self.assertEqual("now", discovered["frontier"])
            self.assertEqual("codebase", discovered["resolvable_by"])
            self.assertEqual("reversible", discovered["reversibility"])
            self.assertEqual(
                "How should we implement password reset before launch?",
                discovered["question"],
            )
            self.assertIn("Constraint: only for enterprise tenants", reply["decision"]["notes"])
            self.assertEqual("question", reply["next_turn"]["status"])
            self.assertEqual(discovered["id"], reply["next_turn"]["decision_id"])
            self.assertIn("Captured constraints:", reply["message"])
            self.assertIn("Discovered decisions:", reply["message"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_returns_candidates_for_discovered_codebase_decision(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app").mkdir()
            (root / "app" / "auth.py").write_text(
                "def send_password_reset(email):\n    return f'password reset sent to {email}'\n",
                encoding="utf-8",
            )
            ai_dir = str(root / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Immediately resolve discovered codebase decisions",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Auth decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-023",
                    "title": "Authentication mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "resolvable_by": "human",
                    "question": "Should the MVP use magic links?",
                    "context": "Choose the initial authentication mode.",
                    "options": [{"summary": "Use magic links for the MVP."}],
                },
            )

            advance_session(ai_dir, session_id, repo_root=root)
            reply = handle_reply(
                ai_dir,
                session_id,
                "Sounds good, and we also need password reset before launch.",
                repo_root=root,
            )
            self.assertEqual("accepted", reply["status"])
            self.assertEqual(1, len(reply["discovered_decisions"]))
            discovered = reply["discovered_decisions"][0]
            self.assertEqual("unresolved", discovered["status"])
            self.assertEqual([], reply["auto_resolved"])
            self.assertEqual("question", reply["next_turn"]["status"])
            self.assertEqual(discovered["id"], reply["next_turn"]["decision_id"])
            self.assertEqual(1, len(reply["next_turn"]["evidence_candidates"]))
            self.assertEqual(discovered["id"], reply["next_turn"]["evidence_candidates"][0]["decision_id"])
            self.assertEqual("codebase", reply["next_turn"]["evidence_candidates"][0]["source"])
            self.assertIn("app/auth.py", reply["next_turn"]["evidence_candidates"][0]["evidence_refs"])
            self.assertIn("Evidence candidates (not applied automatically):", reply["message"])
            self.assertIn("candidate answer:", reply["message"])
            self.assertNotIn("Resolved by evidence:", reply["message"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_extracts_multiple_constraints_and_decisions(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Extract multiple constraints and follow-up decisions",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Retention decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-021",
                    "title": "Audit retention",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "ops",
                    "resolvable_by": "human",
                    "question": "How long should audit logs be retained?",
                    "context": "Retention affects compliance scope.",
                    "options": [{"summary": "Start with 30 days."}],
                },
            )

            advance_session(ai_dir, session_id, repo_root=tmp)
            reply = handle_reply(
                ai_dir,
                session_id,
                (
                    "Use 90 days, but only for enterprise tenants, and it must stay in the US, "
                    "and we also need S3 export before launch, and we need retention to be configurable later."
                ),
                repo_root=tmp,
            )
            self.assertEqual("accepted", reply["status"])
            self.assertEqual("Use 90 days", reply["decision"]["accepted_answer"]["summary"])
            self.assertEqual(
                ["only for enterprise tenants", "it must stay in the US"],
                reply["captured_constraints"],
            )
            self.assertEqual(2, len(reply["discovered_decisions"]))
            by_title = {item["title"]: item for item in reply["discovered_decisions"]}
            self.assertEqual("technical", by_title["S3 export before launch"]["domain"])
            self.assertEqual("dependency", by_title["S3 export before launch"]["kind"])
            self.assertEqual("codebase", by_title["S3 export before launch"]["resolvable_by"])
            self.assertEqual("reversible", by_title["S3 export before launch"]["reversibility"])
            self.assertEqual(
                "What implementation do we need for S3 export before launch?",
                by_title["S3 export before launch"]["question"],
            )
            self.assertEqual("ops", by_title["Retention to be configurable later"]["domain"])
            self.assertEqual("choice", by_title["Retention to be configurable later"]["kind"])
            self.assertEqual("human", by_title["Retention to be configurable later"]["resolvable_by"])
            self.assertEqual("reversible", by_title["Retention to be configurable later"]["reversibility"])
            self.assertEqual(
                "How should we handle retention to be configurable later?",
                by_title["Retention to be configurable later"]["question"],
            )
            priorities = {(item["priority"], item["frontier"]) for item in reply["discovered_decisions"]}
            self.assertIn(("P0", "now"), priorities)
            self.assertIn(("P2", "later"), priorities)
            self.assertEqual("question", reply["next_turn"]["status"])
            self.assertEqual([], validate_runtime(ai_dir))

    def test_handle_reply_discovers_legal_constraint_from_follow_up_clause(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = str(Path(tmp) / ".ai" / "decide-me")
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Infer legal follow-up decisions",
                current_milestone="MVP",
            )
            session_id = create_session(ai_dir, context="Auth decision")["session"]["id"]
            discover_decision(
                ai_dir,
                session_id,
                {
                    "id": "D-022",
                    "title": "Authentication mode",
                    "priority": "P0",
                    "frontier": "now",
                    "domain": "technical",
                    "resolvable_by": "human",
                    "question": "Should the MVP use magic links?",
                    "context": "Choose the initial authentication mode.",
                    "options": [{"summary": "Use magic links for the MVP."}],
                },
            )

            advance_session(ai_dir, session_id, repo_root=tmp)
            reply = handle_reply(
                ai_dir,
                session_id,
                "Use magic links, and we also need EU data residency before launch.",
                repo_root=tmp,
            )
            self.assertEqual("accepted", reply["status"])
            self.assertEqual(1, len(reply["discovered_decisions"]))
            discovered = reply["discovered_decisions"][0]
            self.assertEqual("legal", discovered["domain"])
            self.assertEqual("constraint", discovered["kind"])
            self.assertEqual("P0", discovered["priority"])
            self.assertEqual("now", discovered["frontier"])
            self.assertEqual("external", discovered["resolvable_by"])
            self.assertEqual("hard-to-reverse", discovered["reversibility"])
            self.assertEqual(
                "What external requirement should apply to EU data residency before launch?",
                discovered["question"],
            )
            self.assertEqual([], validate_runtime(ai_dir))


if __name__ == "__main__":
    unittest.main()
