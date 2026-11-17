# Handoff (end of the Milestone 4 sprint, 2026-11-16)

Branch `claude/kind-gauss-53igp5`. No pull request. Nothing deployed.

## Where things are

- Milestones 1 to 4 are built. Milestone 4 works against the mock provider only.
- Backend tests: `cd backend && .venv/bin/python -m pytest` (393 at handoff).
- Browser tests: `cd frontend && npm run build`, then `node e2e/run.cjs` from the project folder (5 at handoff). They start their own backend on a throwaway database.
- Audit report: `docs/AUDIT.md`. Vision design, costs, readiness: `docs/VISION.md`. Evaluation: `backend/eval/README.md`.

## Owner decisions on 2026-11-17

- **Live API spending: approved.** Held at the owner's request because there is no API key yet. Live calls remain switched off; nobody but the owner turns them on.
- **Vinted: 3% seller fee, and it permits the intended selling** (owner's statement, not independently checked). The default Vinted profile is now 3% and marked verified. Assumed: charged on the item price, buyer pays shipping.
- **Evaluation photos supplied**: "public-starter-40", 40 public real photos (24 dev, 16 held out), imported to `backend/eval/public-starter-40/` (not in git; this cloud container is temporary, so re-extract the zip there in a new session). Its own checker and the app's validator both pass. A mock dry run of the dev split completed with no live calls.

## Blocked on the owner

1. **An OpenAI API key on a paid tier** in `OPENAI_API_KEY`, then provider = OpenAI and "Allow live" in Settings. This session's network also does not allow `api.openai.com`.
2. **Review the draft labels.** All 40 are assistant drafts (`human_reviewed` is false for every row). Open `REVIEW_DEV.html`; have the held-out sheet reviewed without using it for prompt work. Freeze the labels before any scored run.
3. **Decide the Whatnot bid-step thresholds** when known (Settings).

## Notes on the evaluation set

- Single photo per example, so multi-photo matching is untested.
- Only 2 examples have a specific style, so no style-accuracy claim can be made from it.
- `truth.identifiable` in this set means "a brand or specific model is supported by the photo". It matches the scorer: an example with no brand can never be "ready for review" in the app, so abstention is scored as intended. No label or scoring rule was changed to fit.
- One held-out label row was displayed to the developer while checking the file format. No prompt work has been done since; do not tune on it.
- Public photos may have been seen by the model in training. A later test on your own item photos is still needed.
- Importing it found two bugs in image handling, both fixed: MPO phone photos were refused, and an embedded JPEG text comment survived metadata removal.

## Exact next steps once unblocked

1. Live dev split: `python eval/run_eval.py eval/public-starter-40/labels.jsonl --split dev --live --i-approve-spending --allowance 0.50` (from `backend`).
2. Compare reported input tokens with the reservation in `eval/public-starter-40/runs/dev/eval.db` (`ai_usage`). If actual exceeds reserved, raise the image token multiplier or safety factor in Settings; if far below, lower the safety factor.
3. Adjust the prompt only against the dev split; bump `PROMPT_VERSION`. Score the held-out split once.
4. Replace the assumed token counts in `docs/VISION.md` with measured ones.
5. Then Milestone 5 (inventory, realized profit). Remember: the risk reserve is not a realized expense.

## Open engineering items

- One unexplained intermittent test failure (see `docs/AUDIT.md`, last item).
- Older tables have no workspace column.
- No automatic photo expiry.
- Analyses are not flagged out of date by the passage of time alone.
- The mock billing switch (`PROFIT_HUNTER_MOCK_BILLING=1`) is for tests on a throwaway database only.
- This cloud session's network allows `developers.openai.com` (documentation) only. `api.openai.com` is not allowed, so live calls cannot be made from here without a further change.
