# Vision evaluation harness

Measures how well the vision model reads real clothing photos, and what it
really costs. **No real evaluation has been run yet.** Accuracy is untested
until you supply labelled photos and approve the spending.

## What you need to provide

40 to 50 photos sets of real items you can identify with certainty, in a
folder of your own (do not commit private photos):

```
backend/eval/my-set/
  labels.jsonl
  images/...
```

Copy `labels.template.jsonl` to start. One line per example:

| Field | Meaning |
|---|---|
| `id` | Unique name |
| `split` | `dev` (you may look at results and adjust the prompt) or `heldout` (score rarely; never tune against it) |
| `group` | Same value for near-duplicates (same garment, same listing). A group must stay in one split; the harness refuses otherwise |
| `case_type` | `clear_label`, `partial_logo`, `similar_styles`, `generic`, `conflicting`, `unidentifiable` |
| `images` | 1 to 3 files with a role: `garment`, `label` or `detail` |
| `seller_text` | Optional. Include some that contradict the photo |
| `truth.identifiable` | `false` when the honest answer is "cannot tell" |
| `truth.brand`, `truth.style` | The correct value, or `null` when it cannot be determined from the photos. `*_aliases` lists other acceptable spellings |

Aim for roughly: 12 clear labels, 8 partial logos, 8 similar styles, 6
generic, 6 conflicting, 8 unidentifiable; about 30 dev and 15 to 20 held out.

## Running it

From the `backend` folder. A mock run checks the plumbing and costs nothing:

```bash
python eval/run_eval.py eval/my-set/labels.jsonl
```

A real run (paid; needs `OPENAI_API_KEY` and both flags):

```bash
python eval/run_eval.py eval/my-set/labels.jsonl --split dev --live --i-approve-spending --allowance 0.50
```

Each run keeps its own database and cost ledger in `eval/my-set/runs/<split>/`
and stops when `--allowance` is reached. That spending is separate from the
app's own ledger, so count both toward whatever total you approved.

## What is measured

- `structured_output_validity`: answers that came back usable.
- `brand_accuracy_when_brand_is_determinable`, `style_accuracy_...`: correct value where a correct value exists. A missing answer counts as wrong.
- `brand_precision_when_a_brand_is_asserted`: when it names a brand, how often it is right.
- `unsupported_specific_identification_rate`: answers that assert a brand or style that is wrong or cannot be determined. This is the number that protects your money; it should be near zero.
- `correct_abstention_rate`: on photos that cannot be identified, how often it says so.
- `useful_result_coverage`: share of all examples that came back ready for review, correct, with nothing unsupported.
- `latency_ms_p50` / `p95`, `mean_cost_per_example_usd`, `cost_per_usable_identification_usd` (all spending, failures included, divided by usable results).

The scoring code is `profit_hunter/vision/evaluation.py` and has its own tests
using synthetic records. Those tests prove the arithmetic, not the model.
