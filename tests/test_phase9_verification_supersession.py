"""Tests that verification doc supersession notices exist and 09-VERIFICATION.md is complete.

These tests replace the overstated claims in prior verification docs with a
programmatic check that the corrections have been documented.
"""

from __future__ import annotations

from pathlib import Path

PLANNING_ROOT = Path(__file__).parent.parent / ".planning" / "phases"

V02_FILE = PLANNING_ROOT / "02-safe-lexical-mvp" / "02-VERIFICATION.md"
V03_FILE = PLANNING_ROOT / "03-turn-by-turn-adaptive" / "03-VERIFICATION.md"
V04_FILE = PLANNING_ROOT / "04-rollout-hardening" / "04-VERIFICATION.md"
V09_FILE = PLANNING_ROOT / "09-rollout-activation" / "09-VERIFICATION.md"

SUPERSESSION_MARKER = "SUPERSEDED (Phase 9 gap closure)"


class TestSupersessionNoticesExist:
    """Verify that all three prior verification docs have the supersession notice."""

    def test_02_verification_has_supersession_notice(self):
        assert V02_FILE.exists(), f"Missing {V02_FILE}"
        content = V02_FILE.read_text(encoding="utf-8")
        assert SUPERSESSION_MARKER in content, (
            f"02-VERIFICATION.md missing supersession notice: {SUPERSESSION_MARKER!r}"
        )

    def test_03_verification_has_supersession_notice(self):
        assert V03_FILE.exists(), f"Missing {V03_FILE}"
        content = V03_FILE.read_text(encoding="utf-8")
        assert SUPERSESSION_MARKER in content, (
            f"03-VERIFICATION.md missing supersession notice: {SUPERSESSION_MARKER!r}"
        )

    def test_04_verification_has_supersession_notice(self):
        assert V04_FILE.exists(), f"Missing {V04_FILE}"
        content = V04_FILE.read_text(encoding="utf-8")
        assert SUPERSESSION_MARKER in content, (
            f"04-VERIFICATION.md missing supersession notice: {SUPERSESSION_MARKER!r}"
        )

    def test_02_verification_has_v02_annotation(self):
        content = V02_FILE.read_text(encoding="utf-8")
        assert "V-02 CORRECTED" in content, "02-VERIFICATION.md missing V-02 inline annotation"

    def test_02_verification_has_v04_annotation(self):
        content = V02_FILE.read_text(encoding="utf-8")
        assert "V-04 CORRECTED" in content, "02-VERIFICATION.md missing V-04 inline annotation"

    def test_03_verification_has_v01_annotation(self):
        content = V03_FILE.read_text(encoding="utf-8")
        assert "V-01 CORRECTED" in content, "03-VERIFICATION.md missing V-01 inline annotation"

    def test_03_verification_has_v03_annotation(self):
        content = V03_FILE.read_text(encoding="utf-8")
        assert "V-03 CORRECTED" in content, "03-VERIFICATION.md missing V-03 inline annotation"

    def test_03_verification_has_v05_annotation(self):
        content = V03_FILE.read_text(encoding="utf-8")
        assert "V-05 CORRECTED" in content, "03-VERIFICATION.md missing V-05 inline annotation"

    def test_04_verification_has_v06_annotation(self):
        content = V04_FILE.read_text(encoding="utf-8")
        assert "V-06 CORRECTED" in content, "04-VERIFICATION.md missing V-06 inline annotation"


class TestV09VerificationExists:
    """Verify that 09-VERIFICATION.md exists and references V-01 through V-06."""

    def test_09_verification_exists(self):
        assert V09_FILE.exists(), f"Missing 09-VERIFICATION.md at {V09_FILE}"

    def test_09_verification_references_v01(self):
        content = V09_FILE.read_text(encoding="utf-8")
        assert "V-01" in content, "09-VERIFICATION.md missing V-01 reference"

    def test_09_verification_references_v02(self):
        content = V09_FILE.read_text(encoding="utf-8")
        assert "V-02" in content, "09-VERIFICATION.md missing V-02 reference"

    def test_09_verification_references_v03(self):
        content = V09_FILE.read_text(encoding="utf-8")
        assert "V-03" in content, "09-VERIFICATION.md missing V-03 reference"

    def test_09_verification_references_v04(self):
        content = V09_FILE.read_text(encoding="utf-8")
        assert "V-04" in content, "09-VERIFICATION.md missing V-04 reference"

    def test_09_verification_references_v05(self):
        content = V09_FILE.read_text(encoding="utf-8")
        assert "V-05" in content, "09-VERIFICATION.md missing V-05 reference"

    def test_09_verification_references_v06(self):
        content = V09_FILE.read_text(encoding="utf-8")
        assert "V-06" in content, "09-VERIFICATION.md missing V-06 reference"

    def test_09_verification_references_replacement_tests(self):
        """09-VERIFICATION.md should reference the replacement test files."""
        content = V09_FILE.read_text(encoding="utf-8")
        assert "test_alert_rescore_rate" in content, (
            "09-VERIFICATION.md missing test_alert_rescore_rate test reference"
        )
        assert "test_e2e_alert_rescore" in content, (
            "09-VERIFICATION.md missing test_e2e_alert_rescore test reference"
        )
        assert "test_replay_cutover_gates" in content, (
            "09-VERIFICATION.md missing test_replay_cutover_gates test reference"
        )
