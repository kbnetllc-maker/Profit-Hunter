"""The evaluation ARITHMETIC, checked with synthetic records.

Nothing here is evidence about any model's real accuracy.
"""

from decimal import Decimal as Dec

from profit_hunter.vision.evaluation import Record, matches, monthly_cost, score, validate_labels


def example(id_, brand="Acme", style=None, identifiable=True, split="dev", case="clear_label", group=None):
    return {"id": id_, "split": split, "group": group, "case_type": case, "images": [{"path": "x.jpg", "role": "garment"}],
            "truth": {"identifiable": identifiable, "category": "jacket" if identifiable else None,
                      "brand": brand, "brand_aliases": ["ACME Co."], "style": style, "style_aliases": []}}


def record(ex, brand=None, basis="observed", status="ready_for_review", valid=True, style=None, cost=1000, ms=900):
    return Record(ex, valid, status, brand, basis if brand else "unknown", style, "inferred" if style else "unknown", ms, cost)


def test_matching_ignores_case_spacing_and_accepts_aliases():
    assert matches("acme", "Acme") and matches("ACME  CO", "Acme", ["ACME Co."])
    assert not matches("Acne", "Acme") and not matches(None, "Acme") and not matches("x", None)


def test_scores_on_a_small_hand_checked_set():
    records = [
        record(example("1"), "ACME"),                                                    # correct, useful
        record(example("2"), "Wrongbrand"),                                              # asserted and wrong
        record(example("3"), None, status="more_evidence_needed"),                       # missed
        record(example("4", brand=None, identifiable=False, case="unidentifiable"), None, status="unable_to_identify"),
        record(example("5", brand=None, identifiable=False, case="unidentifiable"), "Guessed", "inferred"),
        record(example("6", brand=None, identifiable=False, case="unidentifiable"), "SellerSaid", "user_supplied",
               status="more_evidence_needed"),                                           # relayed a claim, did not assert
        record(example("7"), None, status="failed", valid=False, ms=None, cost=2000),    # paid for, unusable
        record(example("8", style="Trucker"), "Acme", style="Bomber"),                   # right brand, wrong style
    ]
    s = score(records)
    assert s["examples"] == 8 and s["structured_output_validity"] == 0.875
    assert s["brand_accuracy_when_brand_is_determinable"] == 0.4          # 2 right of 5 with a known brand
    assert s["brand_precision_when_a_brand_is_asserted"] == 0.5           # 2 right of 4 asserted
    assert s["style_accuracy_when_style_is_determinable"] == 0.0
    assert s["unsupported_specific_identification_rate"] == round(3 / 7, 4)   # 2, 5 and 8
    assert s["correct_abstention_rate"] == round(2 / 3, 4)                 # 4 and 6 abstained, 5 did not
    assert s["useful_result_coverage"] == 0.125 and s["usable_identifications"] == 1
    assert s["total_cost_usd"] == 0.009 and s["cost_per_usable_identification_usd"] == 0.009
    assert s["latency_ms_p50"] == 900
    empty = score([])
    assert empty["structured_output_validity"] is None and empty["cost_per_usable_identification_usd"] is None


def test_label_file_problems_are_caught():
    good = [example("a", group="g1"), example("b", split="heldout", group="g2")]
    assert validate_labels(good) == []
    leak = [example("a", group="same"), example("b", split="heldout", group="same")]
    assert any("both splits" in p for p in validate_labels(leak))
    bad = [example("a"), example("a"), {**example("c"), "split": "test"}, {**example("d"), "case_type": "odd"},
           {**example("e"), "images": []}, {**example("f"), "truth": {"identifiable": "yes"}}]
    problems = validate_labels(bad)
    assert len(problems) == 5 and any("repeated" in p for p in problems)


def test_monthly_cost_projection_arithmetic():
    kw = dict(input_tokens=4000, output_tokens=800, primary_in=Dec("0.10"), primary_out=Dec("0.50"),
              review_in=Dec("1.00"), review_out=Dec("5.00"))
    # One primary analysis: 4000 x $0.10/M + 800 x $0.50/M = $0.0008. One second look: $0.008.
    assert monthly_cost(analyses=50_000, second_look_share=Dec("0"), failure_overhead=Dec("0"), **kw) == Dec("40.00")
    assert monthly_cost(analyses=50_000, second_look_share=Dec("0.10"), failure_overhead=Dec("0"), **kw) == Dec("80.00")
    assert monthly_cost(analyses=50_000, second_look_share=Dec("0.25"), failure_overhead=Dec("0.05"), **kw) == Dec("147.00")
