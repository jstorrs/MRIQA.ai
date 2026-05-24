"""Common types for QA tests.

Every test's `run(...)` returns a `TestResult`. The Streamlit UI and the
report layer never need to know what a specific test did internally.

A test can also surface *confidence* and *warnings*. Confidence is a quick
high/medium/low chip the user sees; warnings are specific text strings
explaining why confidence is anything other than 'high'. These exist so
the user can validate detector quality, not just pass/fail.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Literal, Optional

from PIL import Image


logger = logging.getLogger(__name__)

Confidence = Literal["high", "medium", "low"]

_CONFIDENCE_ORDER: dict[Confidence, int] = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Measurement:
    label: str
    value: Optional[float]      # None when the user/detector hasn't recorded one
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
        return self.confidence.upper()

    def add_warning(self, message: str, degrade_to: Confidence = "medium") -> None:
        """Record a warning and degrade confidence to ``degrade_to``.

        ``degrade_to`` names the confidence the warning would *set* —
        passing ``"low"`` is the most damaging (drops to LOW), passing
        ``"high"`` records the message without lowering confidence.
        Confidence only ratchets *down*: a 'low' followed by a 'medium'
        stays 'low'.
        """
        self.warnings.append(message)
        if _CONFIDENCE_ORDER[degrade_to] > _CONFIDENCE_ORDER[self.confidence]:
            self.confidence = degrade_to

    @contextmanager
    def capture_failures(self) -> Iterator[None]:
        """Catch any exception raised inside the block, mark the result as
        errored, and log the traceback. Tests use this to keep the UI from
        crashing on a single bad detector while still surfacing the full
        traceback in the logs.
        """
        try:
            yield
        except Exception as exc:
            logger.exception("QA test %r failed", self.test_id)
            self.passed = None
            self.error = f"{type(exc).__name__}: {exc}"

    def finalize_pass(self) -> None:
        """Set ``self.passed`` from the verdicts of all measurements that
        have a non-None ``passed``. ``None`` means no measurement had a
        definite verdict (e.g. user-confirmation test without input)."""
        verdicts = [m.passed for m in self.measurements if m.passed is not None]
        self.passed = all(verdicts) if verdicts else None

    def flag_if_implausible(
        self,
        label: str,
        value: float,
        *,
        plausible: tuple[float, float],
        unit: str = "",
        nominal: Optional[float] = None,
        big_deviation: Optional[float] = None,
        context: str = "",
    ) -> None:
        """Emit standard detection-quality warnings for a numeric measurement.

        * Outside ``plausible`` → degrades confidence to ``low`` (likely
          detector failure).
        * Within range but ``|value - nominal| > big_deviation`` →
          degrades to ``medium`` (real-looking but worth a human eyeball).

        ``context`` is a short hint appended to the warning text — usually a
        cue like "Check the overlay."
        """
        lo, hi = plausible
        unit_str = f" {unit}" if unit else ""
        suffix = f" {context}" if context else ""
        if value < lo or value > hi:
            self.add_warning(
                f"{label}: measured {value}{unit_str} is far outside the expected "
                f"range ({lo}–{hi}{unit_str}) — likely a detector error rather "
                f"than a real failure.{suffix}",
                degrade_to="low",
            )
            return
        if (
            nominal is not None
            and big_deviation is not None
            and abs(value - nominal) > big_deviation
        ):
            self.add_warning(
                f"{label}: deviation from nominal ({value} vs {nominal}{unit_str}) "
                f"exceeds {big_deviation}{unit_str}.{suffix}",
                degrade_to="medium",
            )


def verdict_of(results: Iterable[TestResult]) -> tuple[str, dict[str, int]]:
    """Roll a collection of TestResults up into an overall verdict + counts.

    Priority order is FAIL > ERROR > REVIEW > PASS; an empty collection
    returns the em-dash sentinel used by the UI and PDF report.
    """
    counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0, "ERROR": 0}
    for r in results:
        counts[r.status_text()] += 1
    if counts["FAIL"]:
        return "FAIL", counts
    if counts["ERROR"]:
        return "ERROR", counts
    if counts["REVIEW"]:
        return "REVIEW", counts
    if counts["PASS"]:
        return "PASS", counts
    return "—", counts
