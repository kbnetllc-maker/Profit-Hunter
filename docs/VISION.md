# AI identification: design, limits, costs and commercial readiness

Status: built and tested against a mock provider. **No live request has ever
been made, so real accuracy, real token counts and real cost are unmeasured.**

## What it does and does not do

It turns 1 to 3 photos (plus optional seller text) into *suggested* item
details, each with a basis (seen in photo, guess, seller's claim, unknown)
and the photo it came from. It does not value items, set bids, confirm
identity, assess authenticity or condition, or touch the inventory budget.
The schema has no price field and no confidence field.

Rules a model cannot be trusted to follow are enforced in code after the
answer arrives (`vision/schema.py::review`): guessed size or material is
removed, a seller's statement is never an "observation", a cited photo that
does not exist turns the claim into a guess, conflicting evidence blocks
"ready for review", and authenticity or price talk is flagged and ignored.

## Pieces

| Piece | File |
|---|---|
| Provider interface | `vision/provider.py` |
| Mock provider (no network, no cost) | `vision/mock.py` |
| OpenAI adapter | `vision/openai_provider.py` |
| Answer schema and review rules | `vision/schema.py` |
| Prompt (versioned) | `vision/prompt.py` |
| Image checks and preparation | `vision/images.py` |
| Cost ledger | `services/ai_ledger.py` |
| Orchestration, cache, retry | `services/vision_service.py` |
| Confirmation binding | `services/identity_service.py` |

Adding another provider means writing one class with `name`, `bills` and
`identify()`. Nothing in the financial engine imports this package.

## Checked against official OpenAI documentation on 2026-11-16

| Fact | Result |
|---|---|
| `gpt-6-luna` and `gpt-6.1-terra` exist, accept image input, support Structured Outputs and the Responses API | Confirmed on both model pages |
| Reasoning effort values | `none`, `low`, `medium` (default), `high`, `xhigh`, `max`. The app uses `low` |
| Luna price | $0.10 input, $0.50 output per million tokens (model page and pricing page) |
| Terra price | $1.00 input, $5.00 output per million tokens (model page and pricing page) |
| SDK call | `client.responses.parse(..., text_format=Model)`, result in `output_parsed`; truncation is `status == "incomplete"`; a refusal is a content part of type `refusal`. Matches installed SDK 3.51.0 |
| Image input | `{"type": "input_image", "image_url": "data:image/jpeg;base64,..."}`; PNG, JPEG, WEBP accepted |
| Free API tier | Listed as "Not supported" for both models. A paid tier is required |

**Not confirmed:** the image-sizing and token-multiplier tables in the vision
guide list `gpt-6-astra` and the `gpt-5.6` family but not these two models.
The app assumes the documented 32-pixel patch rule with a 1.2 multiplier and
adds a 50% safety margin to every cost reservation. The first live requests
will show the true figure; if actual input tokens exceed the reservation, the
ledger records the actual cost and the estimate settings must be raised.
Also not confirmed: whether your API account has access to both models.

## Cost controls

- Mock by default. Live needs three things: provider set to OpenAI, the
  "allow live" switch on, and `OPENAI_API_KEY` set on the server.
- Before each attempt a worst-case cost is reserved: estimated input tokens
  (images by the patch rule, text at 3 characters per token, times the safety
  factor) plus the full output limit, at the dated price. The check and the
  reservation are a single database statement, so simultaneous requests
  cannot share the last of the allowance.
- Limits: $2.00 total, never reset automatically; $0.02 per item including
  second look and retries. Both editable.
- After the answer, the reservation is replaced by the cost of the reported
  tokens. An answered request with no usage figures stays charged in full.
- A timeout or dropped connection may have been billed. Its reservation is
  held as "billing uncertain" until you mark it billed or not billed in
  Settings after checking the provider's usage page.
- An error response from the provider (rate limit, server error, bad request)
  is not billed and releases the reservation.
- At most one retry, only after a temporary failure, only if a fresh
  reservation fits. The SDK's own retries are off.
- No tools are sent with the request. The model cannot browse, search or act.
- A model with no price record cannot be used live.
- Second look runs only when you ask, after the maximum cost is shown and
  accepted. With default limits it does not fit for three full-size photos;
  the screen says so rather than sending it.
- "Stop waiting" in the browser stops the screen from waiting. A request
  already sent still completes on the server, is charged, saved and reused.

Every attempt records: workspace, item, identification id, provider, model,
prompt/schema/preprocessing versions, image count and sizes, input, output
and reasoning tokens, reserved and actual cost, latency, outcome, error,
retry flag, second-look flag and cache use.

## Cache

Key: workspace, provider, model, reasoning effort, prompt version, schema
version, preprocessing version, each photo's role and the hash of the exact
bytes sent, and the cleaned seller text. Only successful answers are cached.
A reused answer is a new record at zero cost. It carries no confirmation and
no recommendation; valuations are never cached.

## Confirmation

A confirmation stores a fingerprint of the item, its eight identity details
(category, brand, model, size, color, material, era, tags) and its photos
including crops. It is created only by a person: the confirm button on
Identify Item, or the "I have personally confirmed" tick on Analyze Item.
Editing an identity detail, or adding, deleting, re-cropping or re-typing a
photo, withdraws it. Confirming against details that changed since you looked
is refused. Two models agreeing confirms nothing.

## Images, privacy and retention

- Accepted: JPEG, PNG, WEBP, checked by content not by file name; up to 12 MB;
  at least 64 pixels a side; at most 50 megapixels; not animated; 3 per item.
- On upload the image is re-encoded, which removes EXIF, GPS and other
  metadata. Stored copies are capped at 4096 pixels.
- Files are stored under `data/images/local/` with random names. The uploaded
  file name is never used, so a path cannot escape that folder.
- Sent copies are cropped, scaled to at most 1280 pixels on the long side and
  saved at high JPEG quality to keep label text legible. Nothing is enhanced
  or generated.
- Deleting a photo removes the file at once. The record keeps only its size
  and hash, so earlier identifications remain auditable. Photos you do not
  delete are kept indefinitely. There is no automatic expiry.
- In live mode the cropped photos and the seller text go to OpenAI. The
  request sets `store=False`. What OpenAI retains beyond that is governed by
  your account's data settings and has not been reviewed here.
- The API key is read from the server's environment. It is never stored in
  the database, returned by any endpoint, or included in the web app.

## Workspaces

All new AI records carry a workspace id, and the cache and cost totals are
scoped by it. There is exactly one workspace, `local`. Older tables (items,
purchases, sessions) have no workspace column. **This is bookkeeping
preparation, not access control. There is no login.**

## Monthly cost projection (assumptions, not measurements)

Per-analysis token counts are **assumed**; nothing has been measured live.

| Case | Input tokens | Output tokens (incl. reasoning) | Wasted requests |
|---|---|---|---|
| Low | 3,000 | 500 | 2% |
| Central | 4,000 | 800 | 5% |
| High (the app's own limits) | 9,000 | 2,000 | 10% |

Central case basis: one garment photo near 960 by 1280 (about 1,440 tokens),
one label crop near 800 by 600 (about 570), and roughly 2,000 tokens of
instructions and schema. "Wasted" covers failed, truncated and retried
requests that are still paid for.

Vision cost per month, 500 analyses per customer:

| Customers | Case | Luna only | 10% get a Terra second look | 25% get one |
|---|---|---|---|---|
| 100 | Low | $28 | $56 | $98 |
| 100 | Central | $42 | $84 | $147 |
| 100 | High | $105 | $209 | $366 |
| 1,000 | Low | $281 | $561 | $982 |
| 1,000 | Central | $420 | $840 | $1,470 |
| 1,000 | High | $1,045 | $2,090 | $3,658 |

Per customer per month: about $0.28 to $1.04 on Luna alone, and $0.98 to
$3.66 with a 25% second-look rate. A second look costs ten times a first
look, so the second-look rate matters more than anything else in this table.

Uncertainty is large: the low and high cases differ by a factor of almost
four, the image-token rule for these models is unconfirmed, and usage of 500
analyses a month is itself a guess. Replace these with measured numbers after
the first evaluation run (`backend/eval/`). Caching will lower real cost by an
unknown amount.

**Not included:** hosting, database and image storage, marketplace-data
licensing, payment processing, support, and the cost of wrong
identifications. Marketplace data is likely to cost more than vision.

## Before this could be sold

None of the following exists. Passing tests do not make it ready.

| Area | Status |
|---|---|
| Real accuracy | Untested. A 40-photo public set is imported with draft labels; it needs the owner's label review, a live run, then a larger test on the owner's own item photos |
| Login, permissions, tenant isolation | Not built. Must exist and be tested before a second user |
| Per-customer quotas and rate limits | Not built. The single allowance is a pilot guard. Unlimited scans would not be viable at any price in the table above |
| Abuse controls | Not built: upload flooding, oversized batches, shared accounts, prompt-injection probing |
| Marketplace data | Unresolved. All comparables are typed in by the user. No right to collect, store or resell any marketplace's listing data has been established |
| Resale marketplace rules | Vinted: permitted, 3% seller fee, per the owner (not independently checked). Other marketplaces: unverified placeholders |
| Privacy | No privacy policy, data-deletion process, retention schedule, or review of the provider's data terms |
| Payments and subscriptions | Not built |
| Hosting | Local only. SQLite and local files would need replacing for multi-user use |
| Opportunity score | Heuristic weights, never validated against outcomes |
| Claims | The product must not claim to authenticate items or guarantee profit |
