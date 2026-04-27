from __future__ import annotations

from copy import deepcopy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.events import new_event_id, utc_now
from decide_me.lifecycle import build_close_summary, close_session, create_session
from decide_me.protocol import accept_proposal, discover_decision, issue_proposal, record_reply_artifacts, resolve_by_evidence
from decide_me.store import (
    bootstrap_runtime,
    load_runtime,
    read_event_log,
    rebuild_and_persist,
    runtime_paths,
    transact,
    validate_runtime,
)


class ObjectBasedCloseSummaryIntegrationTests(unittest.TestCase):
    def test_close_session_records_action_object_and_addresses_link(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _accepted_decision_runtime(ai_dir)

            closed = close_session(str(ai_dir), session_id)

            close_summary = closed["close_summary"]
            action_ids = close_summary["object_ids"]["actions"]
            self.assertEqual(1, len(action_ids))
            self.assertNotIn("candidate_action_slices", close_summary)

            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            links = {link["id"]: link for link in bundle["project_state"]["links"]}
            action_id = action_ids[0]
            link_id = f"L-{action_id}-addresses-D-auth"

            self.assertEqual("action", objects[action_id]["type"])
            self.assertIn(link_id, close_summary["link_ids"])
            self.assertEqual("addresses", links[link_id]["relation"])
            self.assertEqual("D-auth", links[link_id]["target_object_id"])

            events = read_event_log(runtime_paths(ai_dir))
            action_event_index = next(
                index
                for index, event in enumerate(events)
                if event["event_type"] == "object_recorded"
                and event["payload"]["object"]["id"] == action_id
            )
            close_summary_index = next(
                index for index, event in enumerate(events) if event["event_type"] == "close_summary_generated"
            )
            self.assertLess(action_event_index, close_summary_index)
            self.assertEqual([], validate_runtime(ai_dir))

            rebuilt = rebuild_and_persist(ai_dir)
            self.assertEqual(close_summary, rebuilt["sessions"][session_id]["close_summary"])

    def test_close_summary_traverses_from_evidence_action_and_risk_seeds(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _runtime_with_connected_objects(ai_dir)
            closed = close_session(str(ai_dir), session_id)
            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            evidence_id = next(obj_id for obj_id, obj in objects.items() if obj.get("type") == "evidence")
            risk_id = next(obj_id for obj_id, obj in objects.items() if obj.get("type") == "risk")
            action_id = closed["close_summary"]["object_ids"]["actions"][0]

            for seed_id, expected_section in (
                (evidence_id, "evidence"),
                (action_id, "actions"),
                (risk_id, "risks"),
            ):
                seeded_session = deepcopy(bundle["sessions"][session_id])
                seeded_session["session"]["related_object_ids"] = [seed_id]

                close_summary = build_close_summary(bundle["project_state"], seeded_session)

                self.assertIn("D-auth", close_summary["object_ids"]["decisions"])
                self.assertIn(seed_id, close_summary["object_ids"][expected_section])
                self.assertTrue(
                    any(
                        "D-auth" in (
                            link.get("source_object_id"),
                            link.get("target_object_id"),
                        )
                        for link in bundle["project_state"]["links"]
                        if link["id"] in close_summary["link_ids"]
                    )
                )

    def test_close_summary_traverses_multi_hop_from_option_seed(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            session_id = _accepted_decision_runtime(ai_dir)
            closed = close_session(str(ai_dir), session_id)
            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            option_id = next(obj_id for obj_id, obj in objects.items() if obj.get("type") == "option")
            seeded_session = deepcopy(bundle["sessions"][session_id])
            seeded_session["session"]["related_object_ids"] = [option_id]

            close_summary = build_close_summary(bundle["project_state"], seeded_session)

            self.assertIn("D-auth", close_summary["object_ids"]["accepted_decisions"])
            self.assertEqual(closed["close_summary"]["object_ids"]["actions"], close_summary["object_ids"]["actions"])

    def test_dependency_reachable_external_decision_does_not_get_session_action(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Plan object-native close summaries.",
                current_milestone="Phase 5-5",
            )
            session_a = _accepted_decision_session(
                ai_dir,
                context="External",
                decision_id="D-external",
                title="External platform choice",
            )
            close_session(str(ai_dir), session_a)
            session_b = _accepted_decision_session(
                ai_dir,
                context="Local",
                decision_id="D-local",
                title="Local implementation choice",
            )
            _link_dependency(ai_dir, session_b, source_id="D-local", target_id="D-external")

            closed_b = close_session(str(ai_dir), session_b)
            bundle = load_runtime(runtime_paths(ai_dir))
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            links = bundle["project_state"]["links"]
            action_decision_ids = [
                objects[action_id]["metadata"]["decision_id"]
                for action_id in closed_b["close_summary"]["object_ids"]["actions"]
            ]

            self.assertEqual(["D-local"], action_decision_ids)
            self.assertNotIn("D-external", closed_b["close_summary"]["object_ids"]["accepted_decisions"])
            self.assertEqual(
                [],
                [
                    obj["id"]
                    for obj in objects.values()
                    if obj.get("type") == "action"
                    and obj.get("metadata", {}).get("origin_session_id") == session_b
                    and obj.get("metadata", {}).get("decision_id") == "D-external"
                ],
            )
            self.assertEqual(
                [],
                [
                    link["id"]
                    for link in links
                    if link.get("relation") == "addresses"
                    and link.get("target_object_id") == "D-external"
                    and objects.get(link.get("source_object_id"), {}).get("metadata", {}).get("origin_session_id")
                    == session_b
                ],
            )
            self.assertEqual([], validate_runtime(ai_dir))


def _accepted_decision_runtime(ai_dir: Path) -> str:
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Plan object-native close summaries.",
        current_milestone="Phase 5-5",
    )
    session_id = create_session(str(ai_dir), context="Auth")["session"]["id"]
    discover_decision(
        str(ai_dir),
        session_id,
        {
            "id": "D-auth",
            "title": "Auth mode",
            "priority": "P0",
            "frontier": "now",
            "domain": "technical",
            "resolvable_by": "codebase",
            "question": "How should users sign in?",
        },
    )
    issue_proposal(
        str(ai_dir),
        session_id,
        decision_id="D-auth",
        question="Use magic links?",
        recommendation="Use magic links.",
        why="Smallest viable auth scope.",
        if_not="Passwords add reset flows.",
    )
    accept_proposal(str(ai_dir), session_id)
    return session_id


def _accepted_decision_session(ai_dir: Path, *, context: str, decision_id: str, title: str) -> str:
    session_id = create_session(str(ai_dir), context=context)["session"]["id"]
    discover_decision(
        str(ai_dir),
        session_id,
        {
            "id": decision_id,
            "title": title,
            "priority": "P0",
            "frontier": "now",
            "domain": "technical",
            "resolvable_by": "codebase",
            "question": f"What should we do for {title}?",
        },
    )
    issue_proposal(
        str(ai_dir),
        session_id,
        decision_id=decision_id,
        question=f"Use the recommended path for {title}?",
        recommendation=f"Use recommended path for {title}.",
        why="It is the smallest viable scope.",
        if_not="A broader choice adds coordination cost.",
    )
    accept_proposal(str(ai_dir), session_id)
    return session_id


def _link_dependency(ai_dir: Path, session_id: str, *, source_id: str, target_id: str) -> None:
    event_id = new_event_id()
    created_at = utc_now()

    def builder(_: dict) -> list[dict]:
        return [
            {
                "event_id": event_id,
                "session_id": session_id,
                "event_type": "object_linked",
                "payload": {
                    "link": {
                        "id": f"L-{source_id}-depends_on-{target_id}",
                        "source_object_id": source_id,
                        "relation": "depends_on",
                        "target_object_id": target_id,
                        "rationale": "Local implementation depends on the external platform choice.",
                        "created_at": created_at,
                        "source_event_ids": [event_id],
                    }
                },
            }
        ]

    transact(ai_dir, builder)


def _runtime_with_connected_objects(ai_dir: Path) -> str:
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Plan object-native close summaries.",
        current_milestone="Phase 5-5",
    )
    session_id = create_session(str(ai_dir), context="Auth")["session"]["id"]
    discover_decision(
        str(ai_dir),
        session_id,
        {
            "id": "D-auth",
            "title": "Auth mode",
            "priority": "P0",
            "frontier": "now",
            "domain": "technical",
            "resolvable_by": "codebase",
            "question": "How should users sign in?",
        },
    )
    record_reply_artifacts(
        str(ai_dir),
        session_id,
        decision_id="D-auth",
        constraints=["risk: password resets add operational overhead"],
    )
    resolve_by_evidence(
        str(ai_dir),
        session_id,
        decision_id="D-auth",
        source="docs",
        summary="Magic links are already supported by the current architecture.",
        evidence_refs=["docs/auth.md"],
    )
    return session_id


if __name__ == "__main__":
    unittest.main()
