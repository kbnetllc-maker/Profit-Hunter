"""Mock provider: no network, no cost, obviously fake answers.

It never looks at the image. It exists to develop and test the workflow.
Put one of these tags in the seller text to rehearse other outcomes:
[mock:more] [mock:unable] [mock:refuse] [mock:truncate] [mock:fail] [mock:timeout]
"""

from __future__ import annotations

from .provider import (EMPTY, OK, REFUSED, TRUNCATED, ProviderError, ProviderResult, Usage,
                       VisionRequest)
from .schema import Finding, IdentificationOutput, Variation

_NOTE = "MOCK RESPONSE. No image was examined."


def _unknown() -> Finding:
    return Finding(value=None, basis="unknown", evidence_source=None, evidence="")


def mock_output(*, review_model: bool = False, status: str = "ready_for_review") -> IdentificationOutput:
    known = status == "ready_for_review"
    seen = lambda v: Finding(value=v, basis="observed", evidence_source="image_1", evidence=_NOTE)  # noqa: E731
    return IdentificationOutput(
        status=status, summary=_NOTE,
        category=seen("jacket (MOCK)") if status != "unable_to_identify" else _unknown(),
        brand=seen("MOCKBRAND") if known else _unknown(),
        # The mock second look disagrees on style, to exercise the comparison.
        style=(Finding(value="Mock Trucker II" if review_model else "Mock Trucker", basis="inferred",
                       evidence_source="image_1", evidence=_NOTE) if known else _unknown()),
        size=_unknown(), color=seen("blue (MOCK)") if known else _unknown(),
        pattern=_unknown(), material=_unknown(),
        label_text=["MOCKBRAND"] if known else [], visible_defects=[],
        possible_variations=([Variation(name="Mock Trucker", distinguishing_evidence="MOCK: care-label code"),
                              Variation(name="Mock Trucker II", distinguishing_evidence="MOCK: care-label code")]
                             if known else []),
        conflicts=[], missing_information=["size (no size tag photographed)"] if known else ["a clear label photo"],
        suggested_search_terms=["MOCKBRAND jacket"] if known else [],
        another_photo_needed=not known,
        photo_request=None if known else "MOCK: add a close, sharp photo of the neck label.")


class MockProvider:
    name = "mock"
    bills = False

    def __init__(self, review_model: str = ""):
        self.review_model = review_model

    def identify(self, request: VisionRequest) -> ProviderResult:
        text = request.user_text
        usage = Usage(input_tokens=1000 * len(request.images) + 800, output_tokens=600, reasoning_tokens=100)
        if "[mock:timeout]" in text:
            raise ProviderError("MOCK timeout: the request did not finish in time.", transient=True, may_have_billed=True)
        if "[mock:fail]" in text:
            raise ProviderError("MOCK failure: the provider is temporarily unavailable.", transient=True, may_have_billed=False)
        if "[mock:refuse]" in text:
            return ProviderResult(REFUSED, None, usage, request.model, "MOCK refusal.")
        if "[mock:truncate]" in text:
            return ProviderResult(TRUNCATED, None, usage, request.model, "MOCK: output limit reached.")
        if "[mock:empty]" in text:
            return ProviderResult(EMPTY, None, usage, request.model, "MOCK: empty answer.")
        status = ("unable_to_identify" if "[mock:unable]" in text
                  else "more_evidence_needed" if "[mock:more]" in text else "ready_for_review")
        output = mock_output(review_model=request.model == self.review_model, status=status)
        return ProviderResult(OK, output, usage, request.model)
