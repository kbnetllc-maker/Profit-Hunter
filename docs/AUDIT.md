# Financial and state audit (November 2026)

Scope: bid solver, budget ledger, purchases, shipping, valuation, decision
rules, and how saved recommendations age. Method: reading the code against
the intended rules, then writing tests that try to break each rule. Passing
tests were not taken as proof on their own; four of the findings below were
bugs that the earlier 134 tests did not catch.

"Test" names refer to `backend/tests/`.

## Findings that were fixed

| # | Finding | Risk | Fix | Test |
|---|---|---|---|---|
| A1 | The decision rule accepted any confidence number of 90% or more as identification. Nothing passed one in yet, but a vision model's own "0.95" would have unlocked BUY. | Wrong BUY | A confidence figure only counts when flagged as validated against labelled examples. None is. Only a person's confirmation identifies an item. | `test_audit.py::test_a_models_own_confidence_never_unlocks_buy`, `test_vision.py::test_model_output_cannot_confirm_or_unlock_buy` |
| A2 | A lower asking price below a completed sale set the value with no asking-price discount. | Overvaluation | The 15% discount applies whenever an asking price sets the value. $30 sold / $25 asking gives $23.75 then $20.19. | `test_owner_example_lower_asking_price_below_a_completed_sale` |
| A3 | Any comparable of 80% match or more, up to 90 days old, could support BUY. | Weak evidence giving BUY | BUY needs 2 BUY-grade comparables: match 90% or more and seen within 60 days. 80 to 89% and 61 to 90 days still count toward the price (they can only lower it) but give REVIEW at most. Under 80% or over 90 days: excluded. | `test_match_between_80_and_89_supports_review_only`, `test_age_tiers_60_and_90_days`, `test_weaker_evidence_can_only_lower_the_value_never_raise_it`, `test_review_grade_comparables_give_review_not_buy_through_the_api` |
| A4 | The same listing entered twice counted as two comparables. | False evidence count | The same link counts once. Same title and price under different links raises a "may not be independent" warning. | `test_the_same_listing_entered_twice_counts_once`, `test_possible_cross_posts_are_flagged_as_not_independent` |
| A5 | Two wins recorded at the same moment were each checked against the same remaining budget, so both could be accepted. | Overspending | The budget check and the insert now run under one database write lock. | `test_concurrent_wins_cannot_overspend_the_weekly_budget` |
| A6 | A double click or a repeated request recorded the same win twice. | Double-counted spending | Each "record my win" carries a unique request id; a repeat returns the first purchase. The button is also disabled while sending. | `test_a_repeated_request_records_the_win_once`, browser test "main path" |
| A7 | Two requests arriving together at the start of a week both tried to create the week record and one failed with an error. | Failed purchase recording | The week record is created with "insert unless it exists". | `test_concurrent_wins_cannot_overspend_the_weekly_budget` (this test exposed it) |
| A8 | A weekly-budget change saved while the week record was first being created could be lost, leaving the week on the old budget. Found by the browser test: an $8.72 win was accepted against a $5 budget. | Overspending | Saving the budget now creates the current week's records itself, then sets them. | `test_budget_change_creates_the_week_record_so_it_cannot_be_lost`, browser test "inventory budget exhausted" |
| A9 | Changing the week start day or timezone mid-week began a fresh budget week and stopped counting purchases already made. | Overspending | The change is refused while the current week has purchases that are not canceled. | `test_week_boundary_cannot_move_while_this_week_has_purchases` |
| A10 | A saved BUY kept looking current after the budget, settings, comparables or item changed. | Acting on an outdated result | Every saved analysis now reports whether it is out of date and why. The stored snapshot is never altered. Results with a changed identity leave the ranked list; other out-of-date ones stay, flagged, below current ones. | `test_saved_recommendations_are_flagged_stale_but_never_rewritten`, `test_vision.py::test_identity_change_marks_earlier_analyses_stale` |
| A11 | "Confirmed" was a plain yes/no flag that survived any later edit. | BUY on a different item than the one confirmed | Confirmation is bound to the exact details and photos. See `docs/VISION.md`. | `test_vision.py::test_confirmation_is_bound_to_the_reviewed_details_and_photos` |
| A12 | No way to change an existing database's structure without deleting it. | Data loss on upgrade | Start-up adds missing optional columns and indexes only. It never drops or rewrites. | `test_older_database_is_upgraded_in_place_without_losing_rows` |

## Checked and found correct (now covered by stronger tests)

| Area | What was verified | Test |
|---|---|---|
| Bid solver | The bid returned equals an independent scan of every placeable bid, for 90 price/shipping/tax combinations and three rule sets including stepped increments. It is always a placeable bid; the next step up always fails a rule. | `test_recommended_bid_passes_everything_and_the_next_step_fails`, existing cent-by-cent brute-force test |
| Bid solver | More shipping, more tax, a lower sale price, a stricter profit or ROI rule, less budget or less seller room never raise the bid. | `test_higher_costs_or_stricter_rules_never_raise_the_bid` |
| Rounding | Bids are chosen from the ladder of placeable bids, so a ceiling is never rounded up. Tax and fees round half-up to the cent. | same |
| Over-budget receipts | Actual charges above budget are recorded as charged. The week shows over budget, new purchases are refused, and the original commitment stays in the ledger beside the settlement. | `test_actual_charges_above_budget_are_recorded_honestly_then_block_new_purchases` |
| Shipping | Incremental shipping per item, the bundle total and the per-item allocation all add up to the same figure, once. A cap is respected. | `test_bundle_shipping_is_counted_exactly_once` |
| Shipping | Shipping already paid never justifies another item; unknown shipping is estimated and flagged, never free. | existing `test_sunk_shipping_does_not_justify_an_unprofitable_item`, `test_unknown_additional_shipping_is_estimated_and_flagged` |
| Budget weeks | Monday boundaries in America/Chicago on both daylight-saving weekends of 2026, including the repeated hour. | `test_week_boundaries_in_chicago_across_daylight_saving_changes` |
| Budget history | A budget change alters this week's starting figure only. No transaction is rewritten. | `test_budget_change_applies_to_this_week_only_and_never_rewrites_transactions` |
| Practice mode | Separate ledger, bundles and exposure. | existing tests plus `test_a_repeated_request_records_the_win_once` |
| Projected proceeds | Never added to available budget. | existing `test_resale_proceeds_never_increase_available_budget` |

## Known and not fixed

1. **Risk reserve is an allowance, not an expense.** It is shown on its own line in every breakdown. When realized profit is built (Milestone 5) it must not be subtracted as if it had been spent.
2. **Item price versus delivered price.** Comparables are compared on item price when the buyer pays shipping separately on your resale marketplace, and on price plus shipping otherwise. The basis is stated on screen. The app cannot tell whether a listing from another marketplace follows the same convention; you choose what to enter.
3. **Comparables age silently.** A saved analysis is not flagged merely because time passed and a comparable crossed the 60 or 90 day line. Recalculating applies the current dates.
4. **A recorded win is not checked against the maximum bid.** The screen warns; the server records what actually happened.
5. **Seller exposure is per budget week**, not rolling.
6. **Cross-post detection is shallow.** Only the same link, or the same title and price, is noticed.
7. **Opportunity score weights are a heuristic.** They have not been validated against outcomes.
8. **One intermittent test failure, unexplained.** One full run failed once right after the purchase-locking change; the failing test was not captured. 62 later full runs passed, including 40 back-to-back. A7 or A8 may have been the cause but that is not established.
