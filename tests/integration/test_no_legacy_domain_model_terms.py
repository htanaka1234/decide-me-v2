from __future__ import annotations

import unittest

from tests.helpers.legacy_term_policy import (
    cli_help_legacy_term_findings,
    format_findings,
    source_legacy_term_findings,
)


class NoLegacyDomainModelTermsTests(unittest.TestCase):
    def test_public_source_surfaces_do_not_expose_legacy_terms(self) -> None:
        self.assertEqual([], format_findings(source_legacy_term_findings()))

    def test_cli_help_does_not_expose_legacy_terms(self) -> None:
        self.assertEqual([], format_findings(cli_help_legacy_term_findings()))


if __name__ == "__main__":
    unittest.main()
