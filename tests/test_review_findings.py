from __future__ import annotations

import unittest

from codeproof.review_findings import ReviewFinding


class ReviewFindingTest(unittest.TestCase):
    def test_finding_id_is_stable_for_normalized_message(self) -> None:
        first = ReviewFinding(
            path="app/review.py",
            line=12,
            category="security",
            severity="critical",
            message="Hardcoded  credential",
            rule_id="security.hardcoded-secret",
        )
        second = ReviewFinding(
            path="app/review.py",
            line=12,
            category="security",
            severity="critical",
            message="Hardcoded credential",
            rule_id="security.hardcoded-secret",
        )
        self.assertEqual(first.finding_id, second.finding_id)
        self.assertEqual(len(first.finding_id), 16)

    def test_finding_id_changes_with_location(self) -> None:
        common = dict(
            category="quality",
            severity="warning",
            message="Debug output remains",
            rule_id="quality.debug-print",
        )
        first = ReviewFinding(path="a.py", line=3, **common)
        second = ReviewFinding(path="a.py", line=4, **common)
        self.assertNotEqual(first.finding_id, second.finding_id)

    def test_invalid_severity_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ReviewFinding(
                path="a.py",
                line=1,
                category="quality",
                severity="blocker",
                message="bad input",
                rule_id="quality.demo",
            )


if __name__ == "__main__":
    unittest.main()
