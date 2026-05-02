from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from decide_me.domains import domain_pack_digest, load_builtin_packs
from decide_me.events import utc_now
from decide_me.store import bootstrap_runtime, transact
from tests.helpers.cli import CliResult, run_cli


REPO_ROOT = Path(__file__).resolve().parents[2]


class DomainPackCliTests(unittest.TestCase):
    def test_list_and_show_domain_packs(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(tmp)

            listed = _run_json("list-domain-packs", "--ai-dir", str(ai_dir))
            shown = _run_json("show-domain-pack", "--ai-dir", str(ai_dir), "--pack-id", "research")

        self.assertEqual("ok", listed["status"])
        self.assertEqual(
            {
                "generic",
                "software",
                "research",
                "procurement",
                "operations",
                "personal_planning",
                "writing",
            },
            _pack_ids(listed["packs"]),
        )
        research_entry = next(item for item in listed["packs"] if item["pack_id"] == "research")
        research_pack = load_builtin_packs()["research"]
        self.assertEqual(domain_pack_digest(research_pack), research_entry["digest"])
        self.assertEqual("ok", shown["status"])
        self.assertEqual(domain_pack_digest(research_pack), shown["digest"])
        self.assertEqual("research", shown["pack"]["pack_id"])

    def test_create_session_persists_explicit_and_inferred_domain_pack_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(tmp)
            explicit = _run_json(
                "create-session",
                "--ai-dir",
                str(ai_dir),
                "--context",
                "Plan a retrospective cohort study",
                "--domain-pack",
                "research",
            )
            inferred_cases = (
                ("primary endpoint and missing data", "research", "data"),
                ("vendor, contract, budget, comparison", "procurement", "ops"),
                ("API/auth endpoint database", "software", "technical"),
                ("escalation handoff", "operations", "ops"),
                ("career role schedule", "personal_planning", "other"),
                ("article outline and reviewer", "writing", "other"),
                ("general planning note", "generic", "other"),
                ("planning session", "generic", "other"),
                ("support plan", "generic", "other"),
                ("data report", "generic", "other"),
            )
            inferred = [
                _run_json("create-session", "--ai-dir", str(ai_dir), "--context", context)
                for context, _pack_id, _domain in inferred_cases
            ]

        research_pack = load_builtin_packs()["research"]
        explicit_classification = explicit["classification"]
        self.assertEqual("research", explicit_classification["domain_pack_id"])
        self.assertEqual("0.1.0", explicit_classification["domain_pack_version"])
        self.assertEqual(domain_pack_digest(research_pack), explicit_classification["domain_pack_digest"])
        self.assertEqual("data", explicit_classification["domain"])

        for session, (_context, pack_id, domain) in zip(inferred, inferred_cases, strict=True):
            with self.subTest(pack_id=pack_id):
                self.assertEqual(pack_id, session["classification"]["domain_pack_id"])
                self.assertEqual(domain, session["classification"]["domain"])
                self.assertTrue(session["classification"]["domain_pack_digest"].startswith("DP-"))

    def test_list_sessions_filters_by_domain_pack_and_treats_missing_metadata_as_generic(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(tmp)
            research = _run_json(
                "create-session",
                "--ai-dir",
                str(ai_dir),
                "--context",
                "primary endpoint and missing data",
            )
            _run_json(
                "create-session",
                "--ai-dir",
                str(ai_dir),
                "--context",
                "vendor, contract, budget, comparison",
            )
            legacy_id = _create_legacy_session_without_pack(ai_dir)

            research_list = _run_json("list-sessions", "--ai-dir", str(ai_dir), "--domain-pack", "research")
            generic_list = _run_json("list-sessions", "--ai-dir", str(ai_dir), "--domain-pack", "generic")

        self.assertEqual([research["session"]["id"]], [item["session_id"] for item in research_list["sessions"]])
        self.assertEqual([legacy_id], [item["session_id"] for item in generic_list["sessions"]])
        self.assertEqual("generic", generic_list["sessions"][0]["domain_pack_id"])

    def test_invalid_domain_pack_fails_for_create_show_and_export_document(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(tmp)
            output = ai_dir / "exports" / "documents" / "out.md"

            cases = (
                ("show-domain-pack", "--ai-dir", str(ai_dir), "--pack-id", "missing"),
                ("list-sessions", "--ai-dir", str(ai_dir), "--domain-pack", "missing"),
                ("list-sessions", "--ai-dir", str(ai_dir), "--domain-pack", ""),
                (
                    "create-session",
                    "--ai-dir",
                    str(ai_dir),
                    "--context",
                    "anything",
                    "--domain-pack",
                    "missing",
                ),
                (
                    "create-session",
                    "--ai-dir",
                    str(ai_dir),
                    "--context",
                    "anything",
                    "--domain-pack",
                    "",
                ),
                (
                    "export-document",
                    "--ai-dir",
                    str(ai_dir),
                    "--type",
                    "decision-brief",
                    "--format",
                    "markdown",
                    "--output",
                    str(output),
                    "--domain-pack",
                    "missing",
                ),
            )
            for args in cases:
                with self.subTest(command=args[0]):
                    result = _run_cli(*args, check=False)
                    self.assertNotEqual(0, result.returncode)
                    self.assertRegex(
                        result.stderr,
                        "unknown domain pack: missing|domain pack must be a non-empty string",
                    )

    def test_export_document_domain_pack_reports_applied_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = _bootstrap(tmp)
            output = ai_dir / "exports" / "documents" / "risk-register.md"

            exported = _run_json(
                "export-document",
                "--ai-dir",
                str(ai_dir),
                "--type",
                "risk-register",
                "--format",
                "markdown",
                "--output",
                str(output),
                "--domain-pack",
                "research",
            )

        self.assertEqual(str(output), exported["path"])
        self.assertEqual("research", exported["domain_pack_id"])
        self.assertEqual("research_risk_register", exported["document_profile_id"])
        self.assertEqual("explicit", exported["domain_pack_selection"])
        self.assertTrue(exported["domain_pack_applied"])


def _bootstrap(tmp: str) -> Path:
    ai_dir = Path(tmp) / ".ai" / "decide-me"
    bootstrap_runtime(
        ai_dir,
        project_name="Demo",
        objective="Exercise domain pack CLI.",
        current_milestone="Phase 9 Step 4",
    )
    return ai_dir


def _create_legacy_session_without_pack(ai_dir: Path) -> str:
    session_id = "S-legacy-domain-pack"
    now = utc_now()

    def builder(_bundle: dict) -> list[dict]:
        return [
            {
                "session_id": session_id,
                "event_type": "session_created",
                "payload": {
                    "session": {
                        "id": session_id,
                        "started_at": now,
                        "last_seen_at": now,
                        "bound_context_hint": "Legacy session",
                    }
                },
            }
        ]

    transact(ai_dir, builder)
    return session_id


def _pack_ids(items: list[dict]) -> set[str]:
    return {item["pack_id"] for item in items}


def _run_json(*args: str) -> dict:
    result = _run_cli(*args)
    return json.loads(result.stdout)


def _run_cli(*args: str, check: bool = True) -> CliResult:
    return run_cli(*args, check=check, cwd=REPO_ROOT)


if __name__ == "__main__":
    unittest.main()
