# elchapo cost-fix plan: copy-forward table + Django direct write

**End goal:** drop the two large AWS charges on the elchapo URL shortener to near zero,
**without** disrupting live link creation or redirects.

| Charge today | ~$/mo | After this plan | How |
|---|---:|---|---|
| **API Gateway** (REST requests) | ~$80 | **~$0.30** | Stop routing the ~18.5M/mo creates through API Gateway. Django writes to DynamoDB directly; only the ~95K/mo redirects keep hitting API Gateway. |
| **DynamoDB storage** (892M backlog rows) | ~$49 | **~$0** | New rows carry a 3-month TTL; the legacy backlog is reclaimed for free via `DeleteTable` of the old table after a copy-forward grace period. |
| DynamoDB writes/reads | ~$14 | ~$14 (unchanged) | Workload-driven, irreducible. **In scope to keep, not reduce.** |
| Lambda | ~$5 | ~$0.10 | Falls out for free: ~98% of Lambda invocations were creates, which now bypass Lambda entirely. |

Net: elchapo goes from ~$148/mo to **~$15/mo**, all from config/IAM/code changes, no rewrite.

---

## The two goals

1. **Lambda copy-forward** — stand up a new TTL-enabled table (`v2`), have the redirect
   path serve from `v2` and lazily copy still-clicked legacy links forward from the old
   table (`v1`), so that `v1` can eventually be **`DeleteTable`-d for free** (reclaiming the
   ~$49/mo storage) without losing any active link.
2. **Django direct write** — change the backend so creating a short link does a direct
   `boto3` conditional `PutItem` into `v2` instead of `POST https://link.delight.chat/c`,
   so the create traffic stops hitting API Gateway (and Lambda) entirely.

These are sequenced: **Goal 1 must be live before Goal 2 cuts over**, because once Django
writes new links only to `v2`, the redirect path must already be reading `v2`.

---

## What we verified before committing (evidence)

- **~97% of API Gateway requests are `POST /c` creates** from our own backend.
  - API GW `Count` = 19.5M/30d; Lambda `Invocations` corroborates to **0.05%**.
  - Code-corrected split: ~96.6% creates / ~3.4% redirects (each create does a
    dup-check `GetItem` + a `PutItem`, so raw op counts mislead).
  - 19.5M × $3.50/M ≈ **$68** of pure request charge (rest of the $80 is data-transfer-out).
- **Sole creator of short links is the backend** `URLShortener` class
  (`shared_inbox_server/utils/__init__.py:28` and the `shared_inbox_server-flexype`
  variant). No frontend, mobile, external, or other-service creators.
- **Same AWS account** (330087460411, us-east-1) for the EC2 fleet and the DynamoDB
  table, so direct writes need no cross-account setup.
- **Lambda execution role** (`elchapo-production-ZappaLambdaExecutionRole`) already has
  `dynamodb:*` on `arn:aws:dynamodb:*:*:*` → it **already covers `v2`**, no change needed.
- **Django auths to AWS via a static IAM-user key** (`AKIA…` in `prod.env`,
  `settings.py:554`), used by boto3 for all instances incl. the `Broadcast-autoscaling`
  spot fleet. That user has **no DynamoDB access today** → it needs a new scoped policy.
- Lambda is **512MB / 30s**; its duration cost sits under the free GB-seconds tier, so the
  ~$5 bill is almost entirely the per-request charge (≈ creates).

---

## Tables

| | Name | TTL | Role |
|---|---|---|---|
| **v1** (old) | `production-el-chapo-short-url-store` | none (892M rows) | read-only legacy source during grace; **deleted at the end** |
| **v2** (new) | `production-el-chapo-short-url-store-v2` | enabled on `expires_at` | all new writes + copied-forward legacy links |

Staging mirrors this: `staging-el-chapo-short-url-store` / `…-v2`.

**Item shape in `v2`:** `url` (hash key), `redirection_url`, `webhook` (nullable),
`created_at` (preserved from v1 on copy-forward; = now for new creates), `expires_at`
(Number, epoch seconds; DynamoDB TTL attribute).

**TTL rule (3 months = 90 days) — DECIDED:**
- New create (Django): `expires_at = now + 90d`.
- Copy-forward of a clicked legacy link: `expires_at = now + 90d` (**not** `created_at + 90d`
  — a 2-year-old link would already be expired and vanish the instant we copy it). We
  preserve `created_at` only for the age metric, never for TTL math.
- **Hard expiry, no sliding refresh** (decided): a link expires 90 days after its creation
  (or its copy-forward), *regardless of how often it is clicked*. We are explicitly **not**
  keeping frequently-clicked links alive past the window. Implication to accept: a link still
  being clicked at day 100 will already have expired at day 90 and 404 (for a legacy link,
  if v1 still exists it would re-copy-forward on that click; once v1 is deleted, it 404s).
  This is the simpler model and matches the "links are guaranteed to live 3 months" contract.

---

## Goal 1 — Lambda copy-forward (so v1 can be deleted for free)

**Redirect path** `GET /<path>` becomes:
1. `GetItem` from **v2**.
   - **Hit** → 302 redirect; fire webhook async. (No TTL refresh — hard expiry, see TTL rule.)
   - **Miss** → `GetItem` from **v1**.
     - **Hit** → copy the row into **v2** (preserve `created_at`, set `expires_at = now+90d`),
       **emit the CloudWatch age metric** (below), 302 redirect, fire webhook async.
     - **Miss** → 404.

**Lambda `POST /c`** stays deployed as a rollback path during the transition, but is
rewritten to write to **v2** (conditional `PutItem`, same dup-check semantics as Django) so
both create paths stay consistent. After Django cutover is verified, this endpoint goes idle
(nothing calls it) but is left in place until v1 is deleted.

**CloudWatch metric (bare minimum, as agreed):**
- Name `ActiveLinkAgeDays`, **value only — no dimensions, no short codes**.
- Value = `(now − created_at)` in days, emitted **only on a v1 copy-forward** (i.e. when a
  *legacy* link is clicked for the first time post-migration).
- Two curves this lets us watch over a few weeks: the **age distribution** of still-clicked
  legacy links (percentiles), and the **discovery rate** (`SampleCount` — how many distinct
  old links still get first-clicks over time). Together they tell us the real max active-link
  age and when legacy discovery has tailed off — the empirical signal for deleting v1.

**Also fix while in `app.py`:** the `get_hook()` bug — it builds the `?path=` webhook URL but
never assigns it, so the `path` query param is silently dropped today.

**Tasks**
- [ ] [Sankalp] Pre-create `…-v2` (prod + staging), `PAY_PER_REQUEST`, enable TTL on
      `expires_at`. Do **not** rely on pynamodb import-time `create_table`.
- [ ] [Claude] Add a `v2` model; implement v2-first / v1-fallback + copy-forward in the
      redirect path; sliding `expires_at` refresh; `ActiveLinkAgeDays` emission; rewrite
      `POST /c` to write v2; fix `get_hook()`.
- [ ] [Sankalp] `zappa update production` (and staging) to deploy.
- [ ] Verify: a known legacy link still redirects (and now appears in v2); a new link
      created against v2 redirects; metric data points appear.

---

## Goal 2 — Django direct `PutItem` into v2

Change `URLShortener.get_url()` in **`shared_inbox_server`** — every call site funnels
through this one method, so it's a single-method change. Build it in a **new worktree/branch
off `pre_prod`**. (NOTE: this is ONE repo / one deployment. The local
`shared_inbox_server-flexype` folder is the *same* GitHub repo checked out on `dev`, not a
separate fork — verified via identical `origin` — so there is nothing to change there.)

Replace `requests.post(SHORT_URL_BASE_URL + 'c', …)` with:

```python
import boto3, time
from datetime import datetime, timezone
_ddb = boto3.client("dynamodb", region_name="us-east-1")  # pin region; uses the prod.env key

# Kill-switch is an ENV VAR (not a DB flag) so the create path stays a single put,
# no extra read. When off, fall through to the existing requests.post(.../c) path.
if not settings.USE_DIRECT_DYNAMO_WRITE:
    ... existing requests.post(SHORT_URL_BASE_URL + 'c', ...) ...

# inside the retry loop, with a freshly generated `path`:
expires_at = int(time.time()) + settings.SHORT_URL_TTL_DAYS * 24 * 3600   # prod 180 / stg+default 90
# pynamodb 6.0.0 deserializes this on EVERY redirect (ShortURLV2.get) -> MUST be exactly
# this format; isoformat (+00:00), `Z`, or missing microseconds all raise on read (verified).
created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z")  # 2026-..T..+0000

# Grace-period only: dup-check v1 so a new random path can't hijack a legacy link.
# Remove this read once v1 is deleted.
if _ddb.get_item(TableName=V1_TABLE, Key={"url": {"S": path}}).get("Item"):
    raise Collision  # -> regenerate path, retry

item = {
    "url": {"S": path},
    "redirection_url": {"S": self.redirect_url},
    "created_at": {"S": created_at},
    "expires_at": {"N": str(expires_at)},
}
if self.webhook:                 # OMIT when absent (mirror pynamodb null=True), don't write NULL
    item["webhook"] = {"S": self.webhook}
_ddb.put_item(
    TableName=V2_TABLE, Item=item,
    ConditionExpression="attribute_not_exists(#u)",
    ExpressionAttributeNames={"#u": "url"},
)
# ConditionalCheckFailedException -> regenerate path, retry (existing while retry < 3 loop)
return settings.SHORT_URL_BASE_URL + path
```

Notes:
- The conditional `PutItem` is the dup-check for v2 (atomic — strictly safer than today's
  read-then-write `get`+`save`, which has a race). The extra `GetItem` covers v1 **only
  during the grace window**; drop it after v1 is deleted (then v2 is the only namespace).
- `SHORT_URL_BASE_URL` stays `https://link.delight.chat/` — the **returned** short URL is
  unchanged; only the *creation mechanism* moves off HTTP. Redirects still go through the
  Lambda, so the public contract is identical.
- Preserve current failure behavior: on exhausted retries `get_url()` returns `None`; the
  message-send flow must not break on shortener failure.

**Tasks (A / B / C — updated 2026-06-22)**
- [x] **B (IAM):** scoped `PutItem`+`GetItem` policy (below) on
      `{staging,production}-el-chapo-short-url-store*` attached to `api-access-user` — **DONE
      & proven live** by the direct-`put_item` benchmark from the rq box (5000/5000 ok,
      p50 ~11ms / p99 ~66ms, zero throttle). No further IAM work.
- [ ] **A0:** resolve/create the **Jira ticket** (NFR project — cost/perf work).
- [ ] **A1:** worktree + branch off `pre_prod` (`feature/<slug>-<JIRA-ID>`).
- [ ] **A2:** env config — `V1_TABLE`/`V2_TABLE`, `SHORT_URL_TTL_DAYS` (prod 180 / staging 90 /
      default 90), `USE_DIRECT_DYNAMO_WRITE` (default off); `staging.env=true`, `prod.env=false`.
- [ ] **A3:** rewrite `URLShortener.get_url()` (boto3, conditional put, grace v1 dup-check,
      pinned `created_at` format, omit-webhook-when-absent, flag-gated, `None` on exhausted retries).
- [ ] **A4:** TDD incl. a `created_at` round-trip through pynamodb 6.0.0 `UTCDateTimeAttribute`.
- [ ] **C1:** deploy branch to **staging** (merge→`dev`, run migration check).
- [ ] **C2:** canary verify on staging — create → redirect **through the Lambda** → 302 + row in v2.
- [ ] **C3:** raise **PR: feature → `pre_prod`** (Jira ID in title/branch/commits; diff-confirm gate).
- [ ] **C4:** PR artifacts — `pr_docs/<JIRA-ID>-<slug>.md` (AI) + human PR description + layman
      `#dev-pull-requests` post tagging `@backend-team`, sent directly.
- [ ] **Downstream (Sankalp, later — out of this effort's scope):** merge `pre_prod`→`master`
      prod deploy, flip `USE_DIRECT_DYNAMO_WRITE=true` in prod, watch API GW `Count` fall to the
      redirect-only floor (~95K/mo).

**IAM policy for the Django user** (tight — just these tables, just Get/Put; prefix `*`
covers v1, v2, and a future v3 so we don't re-edit IAM mid-migration):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "ElchapoShortUrlReadWrite",
    "Effect": "Allow",
    "Action": ["dynamodb:PutItem", "dynamodb:GetItem"],
    "Resource": [
      "arn:aws:dynamodb:us-east-1:330087460411:table/production-el-chapo-short-url-store*",
      "arn:aws:dynamodb:us-east-1:330087460411:table/staging-el-chapo-short-url-store*"
    ]
  }]
}
```

---

## Phased sequencing (order matters)

| Phase | What | Owner | Reversible? |
|---|---|---|---|
| **0** | Pre-create `v2` (prod+staging) + enable TTL on `expires_at` | Sankalp | yes (drop v2) |
| **1** | Deploy Lambda copy-forward (v2-first read, v1 fallback+copy, metric, get_hook fix, v2 writes) | Claude → Sankalp deploys | yes (revert zappa) |
| **2** | Verify redirects work for both legacy and v2 links; metric flowing | both | — |
| **3** | (IAM ✅ done) ship `URLShortener` direct-write to staging → canary → **PR into `pre_prod`** (no direct prod deploy from this effort; prod cutover is downstream) | Claude | yes (revert to `requests.post`) |
| **4** | Monitor: API GW `Count` falls to redirect-only; `ActiveLinkAgeDays` age + discovery curves | both | — |
| **5** | **Grace period** — keep v1 as read-only fallback while legacy links get copied forward on click | — | — |
| **6** | When exit criteria met: `DeleteTable` v1 (free); remove the v1 dup-check from Django and the v1 fallback from Lambda | Sankalp + Claude | **no** (v1 gone) |
| **7** | Confirm storage + API GW charges dropped on CloudKeeper | Sankalp | — |

**Division of labor:** Claude writes all code and ops scripts; Sankalp runs the privileged
prod steps (table create/TTL, `zappa update`, IAM attach, `DeleteTable`).

---

## Exit criteria for deleting v1 (Phase 6)

Delete v1 only when **all** hold:
1. `ActiveLinkAgeDays` **discovery rate** (`SampleCount`/day of copy-forwards) has decayed to
   near zero and stayed there — i.e. legacy links have essentially stopped getting
   first-clicks. (This is the empirical answer to "how long must a link stay active.")
2. The observed **age distribution** has stabilized, confirming nothing older than our
   window is still being clicked beyond a negligible tail.
3. A full grace period has elapsed (start assumption: **90 days**; extend if curve #1 hasn't
   flattened).

Because `DeleteTable` is free at any size, the only cost of waiting longer is the ~$49/mo
storage for the extra months — so we err toward a safe, data-driven cutoff rather than rushing.

---

## Rollback

- **Goal 2 (Django):** revert `URLShortener.get_url()` to the `requests.post(.../c)` HTTP
  call. Links created via direct-write are already in v2 and still resolve, so reverting is
  clean.
- **Goal 1 (Lambda):** `zappa update` the prior version. v2 rows are harmless if unused.
- **Hard line:** once Phase 6 `DeleteTable` runs, v1 is gone — that step is the
  point of no return and only happens after the exit criteria above.

---

## Decisions locked
- TTL attribute name: **`expires_at`** (epoch **SECONDS**).
- TTL window is **env-driven** (`SHORT_URL_TTL_DAYS` for Django / `TTL_DAYS` for the Lambda):
  **prod = 180d**, staging + default = 90d. (Prod bumped 90→180 on 2026-06-22; covers ~99th pct
  of clicked-legacy-link ages.)
- **No sliding refresh** — hard expiry from creation/copy-forward.
- Goal 2 write uses **boto3** (no new library). Kill-switch = **`USE_DIRECT_DYNAMO_WRITE` env var**
  (not a DB flag — avoids an extra read per create).
- Django `created_at` MUST be written as `%Y-%m-%dT%H:%M:%S.%f%z` (tz-aware UTC) — pynamodb 6.0.0
  rejects isoformat/`Z`/no-microseconds on `ShortURLV2.get()` (verified).
- Goal 2 is **one repo** (`shared_inbox_server`); `-flexype` is the same repo on `dev`, not a target.

## Open items / decisions to confirm

- [ ] (Deferred security) rotate the long-lived `api-access-user` `AKIA…` key / move Django to
      the EC2 instance role — it sits in `prod.env` in plaintext. Separate effort.
- [ ] Grace-period length and whether to drive Phase 6 (`DeleteTable` v1) off the metric vs a fixed date.

---

## Related docs / memory

- `MIGRATION_PLAN.md` — earlier Go-rewrite plan (superseded by this cheap-fix track; kept
  for the traffic/latency baselines).
- Memory: `project_state_go_migration`, `elchapo_cost_breakdown`, `elchapo_traffic_findings`,
  `elchapo_ttl_blocker`.
