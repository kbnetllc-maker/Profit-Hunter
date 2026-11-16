# Handoff (end of the Milestone 4 sprint, 2026-11-16)

Branch `claude/kind-gauss-53igp5`. No pull request. Nothing deployed.

## Where things are

- Milestones 1 to 4 are built. Milestone 4 works against the mock provider only.
- Backend tests: `cd backend && .venv/bin/python -m pytest` (393 at handoff).
- Browser tests: `cd frontend && npm run build`, then `node e2e/run.cjs` from the project folder (5 at handoff). They start their own backend on a throwaway database.
- Audit report: `docs/AUDIT.md`. Vision design, costs, readiness: `docs/VISION.md`. Evaluation: `backend/eval/README.md`.

## Blocked on the owner

1. **Approve live API spending**, and put an OpenAI API key on a paid tier in `OPENAI_API_KEY`. Until then accuracy, token use and cost are unmeasured.
2. **Provide 40 to 50 labelled real photo sets** for the evaluation (`backend/eval/README.md`).
3. **Confirm Vinted's real seller fees and rules**, and whether it permits the intended selling. Current figures are placeholders.
4. **Decide the Whatnot bid-step thresholds** when known (Settings).

## Exact next steps once unblocked

1. Mock dry run of the label file: `python eval/run_eval.py eval/my-set/labels.jsonl`.
2. Live dev split: add `--split dev --live --i-approve-spending --allowance 0.50`.
3. Compare reported input tokens with the reservation in `runs/dev/eval.db` (`ai_usage`). If actual exceeds reserved, raise the image token multiplier or safety factor in Settings; if far below, lower the safety factor.
4. Adjust the prompt only against the dev split; bump `PROMPT_VERSION`. Score the held-out split once.
5. Replace the assumed token counts in `docs/VISION.md` with measured ones.
6. Then Milestone 5 (inventory, realized profit). Remember: the risk reserve is not a realized expense.

## Open engineering items

- One unexplained intermittent test failure (see `docs/AUDIT.md`, last item).
- Older tables have no workspace column.
- No automatic photo expiry.
- Analyses are not flagged out of date by the passage of time alone.
- The mock billing switch (`PROFIT_HUNTER_MOCK_BILLING=1`) is for tests on a throwaway database only.
- This cloud session's network allows `developers.openai.com` (documentation) only. `api.openai.com` is not allowed, so live calls cannot be made from here without a further change.
