from __future__ import annotations

import unittest

from tests.helpers.snapshot_normalization import (
    normalize_csv_snapshot,
    normalize_json_snapshot,
    normalize_markdown_snapshot,
    stable_json,
)


class SnapshotNormalizationTests(unittest.TestCase):
    def test_normalize_json_snapshot_drops_only_volatile_keys(self) -> None:
        payload = {
            "generated_at": "2026-04-29T00:00:00Z",
            "project_head": "PH-1",
            "last_event_id": "E-1",
            "tx_id": "T-1",
            "scenario_id": "research_protocol",
            "nested": {
                "tx_id": "T-2",
                "kept": True,
            },
            "items": [
                {
                    "generated_at": "2026-04-29T00:01:00Z",
                    "value": 3,
                }
            ],
        }

        self.assertEqual(
            {
                "items": [{"value": 3}],
                "nested": {"kept": True},
                "scenario_id": "research_protocol",
            },
            normalize_json_snapshot(payload),
        )

    def test_stable_json_renders_sorted_normalized_json(self) -> None:
        self.assertEqual('{\n  "a": 1,\n  "z": 2\n}\n', stable_json({"z": 2, "tx_id": "T-1", "a": 1}))

    def test_normalize_markdown_snapshot_extracts_generated_region(self) -> None:
        first = """preface
<!-- decide-me:generated:start document_type=review-memo project_head=PH-1 -->
# Review

Generated at: 2026-04-29T00:00:00Z
<!-- decide-me:generated:end -->
## Human Notes

keep this outside snapshots
"""
        second = first.replace("project_head=PH-1", "project_head=PH-2").replace(
            "keep this outside snapshots",
            "changed human note",
        )

        self.assertEqual(normalize_markdown_snapshot(first), normalize_markdown_snapshot(second))
        self.assertEqual(
            "# Review\n\nGenerated at: 2026-04-29T00:00:00Z\n",
            normalize_markdown_snapshot(first),
        )

    def test_normalize_csv_snapshot_preserves_header_and_sorts_rows(self) -> None:
        self.assertEqual(
            "id,value\nA,1\nB,2\n",
            normalize_csv_snapshot("id,value\r\nB,2\r\nA,1\r\n"),
        )


if __name__ == "__main__":
    unittest.main()
