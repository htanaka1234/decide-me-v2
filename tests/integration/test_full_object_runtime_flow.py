from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers.runtime_flow import (
    advance_session_cli,
    bootstrap_cli,
    create_session_cli,
    handle_reply_cli,
    load_bundle,
    seed_p0_decision,
    validate_cli,
)


class FullObjectRuntimeFlowTests(unittest.TestCase):
    def test_free_form_answer_records_user_proposal_option_and_acceptance_link(self) -> None:
        with TemporaryDirectory() as tmp:
            ai_dir = Path(tmp) / ".ai" / "decide-me"
            bootstrap_cli(ai_dir)
            session_id = create_session_cli(ai_dir)
            seed_p0_decision(ai_dir, session_id)
            turn = advance_session_cli(ai_dir, session_id, Path(tmp))
            assistant_proposal_id = turn["proposal_id"]

            result = handle_reply_cli(
                ai_dir,
                session_id,
                "Use SSO only if legal signs off, and we also need audit export before launch.",
                Path(tmp),
            )

            self.assertEqual("accepted", result["status"])
            self.assertTrue(validate_cli(ai_dir)["ok"])
            bundle = load_bundle(ai_dir)
            objects = {obj["id"]: obj for obj in bundle["project_state"]["objects"]}
            links = bundle["project_state"]["links"]
            user_proposals = [
                obj
                for obj in objects.values()
                if obj["type"] == "proposal"
                and obj["status"] == "accepted"
                and obj["metadata"].get("author") == "user"
            ]

            self.assertEqual("rejected", objects[assistant_proposal_id]["status"])
            self.assertEqual("accepted", objects["D-auth"]["status"])
            self.assertEqual(1, len(user_proposals))
            user_proposal_id = user_proposals[0]["id"]
            self.assertTrue(
                any(
                    link["source_object_id"] == "D-auth"
                    and link["relation"] == "accepts"
                    and link["target_object_id"] == user_proposal_id
                    for link in links
                )
            )
            option_ids = [
                link["target_object_id"]
                for link in links
                if link["source_object_id"] == user_proposal_id and link["relation"] == "recommends"
            ]
            self.assertEqual(["Use SSO"], [objects[option_id]["title"] for option_id in option_ids])
            self.assertTrue(
                any(
                    obj["type"] == "constraint" and obj["title"] == "only if legal signs off"
                    for obj in objects.values()
                )
            )


if __name__ == "__main__":
    unittest.main()
