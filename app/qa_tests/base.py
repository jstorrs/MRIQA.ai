"""Common types for QA tests.

Every test's `run(...)` returns a `TestResult`. The Streamlit UI and the
report layer never need to know what a specific test did internally.

A test can also surface *confidence* and *warnings*. Confidence is a quick
high/medium/low chip the user sees; warnings are specific text strings
explaining why confidence is anything other than 'high'. These exist so
the user can validate detector quality, not just pass/fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from PIL import Image


Confidence = Literal["high", "medium", "low"]


@dataclass
class Measurement:
    label: str
    value: float
    unit: str
    spec: str = ""              # e.g. "190 +/- 2 mm"
    passed: Optional[bool] = None


@dataclass
class TestResult:
    test_id: str
    test_name: str
    automated: bool             # True = numerical; False = user-confirmation
    passed: Optional[bool]      # overall pass/fail; None if user-confirmation w/o input
    measurements: list[Measurement] = field(default_factory=list)
    annotated_images: list[tuple[str, Image.Image]] = field(default_factory=list)
    notes: str = ""
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    confidence: Confidence = "high"

    def status_text(self) -> str:
        if self.error:
            return "ERROR"
        if self.passed is True:
            return "PASS"
        if self.passed is False:
            return "FAIL"
        return "REVIEW"

    def confidence_label(self) -> str:
        return {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}[self.confidence]

    def add_warning(self, message: str, severity: Confidence = "medium") -> None:
        """Record a warning and downgrade confidence accordingly.

        Confidence only ever ratchets *down*: a 'low' followed by a
        'medium' stays 'low'.
        """
        self.warnings.append(message)
        order = {"high": 0, "medium": 1, "low": 2}
        if order[severity] > order[self.confidence]:
            self.confidence = severity
