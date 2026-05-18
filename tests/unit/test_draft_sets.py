from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.draft_sets import (
    DraftSetError,
    DraftSetHeadMismatchError,
    create_draft_set,
    list_draft_sets,
    load_draft_set,
    show_draft_set,
    validate_draft_set,
)
from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, load_runtime, runtime_paths
from tests.unit.test_draft_set_schema import minimal_valid_draft_set


class DraftSetTests(unittest.TestCase):
    def test_create_writes_draft_set_sidecar(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))

            result = create_draft_set(
                ai_dir,
                _draft_input(),
                draft_set_id="DS-20260513-001",
                generated_by="test",
                now="2026-05-13T03:00:00Z",
            )

            path = ai_dir / "draft-sets" / "DS-20260513-001" / "draft-set.json"
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("created", result["status"])
            self.assertEqual("DS-20260513-001", persisted["id"])
            self.assertEqual(2, persisted["schema_version"])
            self.assertEqual("test", persisted["generated_by"])
            self.assertNotIn("convergence", persisted)
            self.assertNotIn("review_queue", persisted)
            self.assertEqual(20, persisted["exploration_contract"]["budgets"]["max_draft_decisions"])
            self.assertEqual(0, persisted["exploration_contract"]["budgets"]["max_iterations"])
            self.assertEqual({"draft_decisions": 1, "draft_assumptions": 0, "draft_risks": 0, "draft_actions": 0, "draft_verifications": 0}, result["counts"])

    def test_create_injects_current_project_head(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            current_head = _project_head(ai_dir)

            create_draft_set(ai_dir, _draft_input(), draft_set_id="DS-20260513-001")

            persisted = load_draft_set(ai_dir, "DS-20260513-001")
            self.assertEqual(current_head, persisted["source_context"]["project_head_at_generation"])

    def test_create_accepts_project_head_alias_and_normalizes_it(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            payload = _draft_input()
            payload["source_context"] = {"project_head": _project_head(ai_dir)}

            create_draft_set(ai_dir, payload, draft_set_id="DS-20260513-001")

            persisted = load_draft_set(ai_dir, "DS-20260513-001")
            self.assertNotIn("project_head", persisted["source_context"])
            self.assertEqual(_project_head(ai_dir), persisted["source_context"]["project_head_at_generation"])

    def test_create_injects_default_exploration_contract_when_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            payload = _draft_input()
            payload.pop("exploration_contract", None)

            create_draft_set(ai_dir, payload, draft_set_id="DS-20260513-001")

            persisted = load_draft_set(ai_dir, "DS-20260513-001")
            contract = persisted["exploration_contract"]
            self.assertEqual(persisted["goal"]["desired_outcome"], contract["objective"])
            self.assertEqual(["project-state.json"], contract["read_first_sources"])
            self.assertEqual(20, contract["budgets"]["max_draft_decisions"])
            self.assertEqual(0, contract["budgets"]["max_iterations"])
            self.assertEqual(
                [
                    "core.layer.purpose",
                    "core.layer.principle",
                    "core.layer.constraint",
                    "core.layer.strategy",
                    "core.layer.design",
                    "core.layer.execution",
                    "core.layer.verification",
                    "core.layer.review",
                ],
                [target["axis_id"] for target in contract["coverage_targets"]],
            )

    def test_create_preserves_explicit_exploration_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            payload = _draft_input()
            payload["exploration_contract"] = minimal_valid_draft_set()["exploration_contract"]
            payload["exploration_contract"]["objective"] = "Explicit exploration objective"
            payload["exploration_contract"]["budgets"] = {
                "max_draft_decisions": 7,
                "max_iterations": 2,
            }

            create_draft_set(ai_dir, payload, draft_set_id="DS-20260513-001")

            persisted = load_draft_set(ai_dir, "DS-20260513-001")
            self.assertEqual("Explicit exploration objective", persisted["exploration_contract"]["objective"])
            self.assertEqual({"max_draft_decisions": 7, "max_iterations": 2}, persisted["exploration_contract"]["budgets"])

    def test_create_rejects_partial_exploration_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            payload = _draft_input()
            payload["exploration_contract"] = {"objective": "Partial contract"}

            with self.assertRaisesRegex(ValueError, "exploration_contract"):
                create_draft_set(ai_dir, payload, draft_set_id="DS-20260513-001")

    def test_create_rejects_duplicate_coverage_target_axis_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            payload = _draft_input()
            payload["exploration_contract"] = minimal_valid_draft_set()["exploration_contract"]
            payload["exploration_contract"]["coverage_targets"].extend(
                [
                    {
                        "axis_id": "custom.layer.strategy",
                        "axis_type": "decision_stack_layer",
                        "value": "strategy",
                        "priority": "P3",
                        "required": False,
                    },
                    {
                        "axis_id": "custom.layer.strategy",
                        "axis_type": "decision_stack_layer",
                        "value": "strategy",
                        "priority": "P1",
                        "required": True,
                    },
                ]
            )

            with self.assertRaisesRegex(DraftSetError, "coverage_targets\\[9\\]\\.axis_id duplicates custom\\.layer\\.strategy"):
                create_draft_set(ai_dir, payload, draft_set_id="DS-20260513-001")

    def test_create_rejects_project_head_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            payload = _draft_input()
            payload["source_context"] = {"project_head_at_generation": "wrong-head"}

            with self.assertRaisesRegex(
                DraftSetHeadMismatchError,
                "draft payload project_head_at_generation does not match current project_head",
            ):
                create_draft_set(ai_dir, payload, draft_set_id="DS-20260513-001")

    def test_create_rejects_duplicate_draft_set_id(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            create_draft_set(ai_dir, _draft_input(), draft_set_id="DS-20260513-001")

            with self.assertRaisesRegex(DraftSetError, "draft set already exists: DS-20260513-001"):
                create_draft_set(ai_dir, _draft_input(), draft_set_id="DS-20260513-001")

    def test_create_generates_incrementing_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))

            first = create_draft_set(ai_dir, _draft_input(), now="2026-05-13T03:00:00Z")
            second = create_draft_set(ai_dir, _draft_input(), now="2026-05-13T04:00:00Z")

            self.assertEqual("DS-20260513-001", first["draft_set_id"])
            self.assertEqual("DS-20260513-002", second["draft_set_id"])

    def test_create_normalizes_created_at_to_now_and_ids_from_now(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            payload = _draft_input()
            payload["created_at"] = "2026-05-14T00:00:00Z"

            result = create_draft_set(ai_dir, payload, now="2026-05-13T03:00:00Z")

            persisted = load_draft_set(ai_dir, result["draft_set_id"])
            self.assertEqual("DS-20260513-001", result["draft_set_id"])
            self.assertEqual("2026-05-13T03:00:00Z", persisted["created_at"])

    def test_load_rejects_path_traversal_id(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))

            with self.assertRaisesRegex(DraftSetError, "invalid draft set id"):
                load_draft_set(ai_dir, "../DS-20260513-001")

    def test_show_reports_not_stale_for_current_head(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            create_draft_set(ai_dir, _draft_input(), draft_set_id="DS-20260513-001")

            result = show_draft_set(ai_dir, "DS-20260513-001")

            self.assertFalse(result["runtime_status"]["is_stale"])
            self.assertIsNone(result["runtime_status"]["reason"])

    def test_show_reports_stale_after_runtime_head_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            create_draft_set(ai_dir, _draft_input(), draft_set_id="DS-20260513-001")
            create_session(str(ai_dir), context="Change the runtime head")

            result = show_draft_set(ai_dir, "DS-20260513-001")

            self.assertTrue(result["runtime_status"]["is_stale"])
            self.assertEqual("project-head-changed", result["runtime_status"]["reason"])

    def test_list_sorts_newest_first(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(Path(tmp))
            create_draft_set(
                ai_dir,
                _draft_input("Older"),
                draft_set_id="DS-20260513-001",
                now="2026-05-13T03:00:00Z",
            )
            create_draft_set(
                ai_dir,
                _draft_input("Newer"),
                draft_set_id="DS-20260513-002",
                now="2026-05-13T04:00:00Z",
            )

            result = list_draft_sets(ai_dir)

            self.assertEqual(["DS-20260513-002", "DS-20260513-001"], [item["id"] for item in result["draft_sets"]])
            self.assertEqual(["Newer", "Older"], [item["goal_title"] for item in result["draft_sets"]])

    def test_validate_rejects_accepted_draft_decision(self) -> None:
        payload = minimal_valid_draft_set()
        payload["draft_decisions"][0]["status"] = "accepted"

        with self.assertRaisesRegex(
            ValueError,
            "draft_decisions\\[0\\].status must be one of: draft, recommended",
        ):
            validate_draft_set(payload)


def _bootstrap(tmp: Path) -> Path:
    ai_dir = tmp / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise draft set sidecars.",
        current_milestone="PR1",
    )
    return ai_dir


def _project_head(ai_dir: Path) -> str:
    return load_runtime(runtime_paths(ai_dir))["project_state"]["state"]["project_head"]


def _draft_input(goal_title: str = "Add draft decision sets") -> dict:
    payload = minimal_valid_draft_set()
    for field in (
        "schema_version",
        "id",
        "status",
        "mode",
        "created_at",
        "generated_by",
        "source_context",
        "exploration_contract",
        "draft_assumptions",
        "draft_risks",
        "draft_actions",
        "draft_verifications",
        "conflicts",
        "promotion",
    ):
        payload.pop(field, None)
    payload["goal"]["title"] = goal_title
    return deepcopy(payload)


if __name__ == "__main__":
    unittest.main()
