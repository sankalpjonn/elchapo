# elchapo: Lambda → Go-on-EC2 migration

**Goal:** Replace the Zappa/Flask Python Lambda (`elchapo-production`, URL shortener)
with a Go HTTP server running in Docker on one of our EC2 instances, and add a
DynamoDB TTL so short-link rows expire instead of accumulating forever and racking
up the bill.

Branch: `worktree-go-migration` (worktree under `.claude/worktrees/go-migration`).
Base: branched from `origin/master` @ `93fa290`. Note: local commit `fe2b11e`
("logging errors only") was NOT pushed and is not in this base.

---

## What the service does today (port these exactly)

Source: `app.py`, `models.py`, `constants.py`, `utils.py` in repo root.

Endpoints:
- `POST /c` — create a short link. JSON body `{path, redirect_url, webhook?, secret_key}`.
  - `secret_key` must equal the configured secret or return `403`.
  - If `path` already exists → `409`. Else save → `200 {"success": true}`.
- `GET /<path>` — look up `path`, fire optional webhook asynchronously, then
  `302` redirect to `redirection_url`. Missing → `404 {"error": "Not found"}`.
- `GET /` — health check, returns `"sucess"` (sic), `200`.

DynamoDB table: **`production-el-chapo-short-url-store`** (region `us-east-1`,
PAY_PER_REQUEST / on-demand). Current attributes:
- `url` (hash key, String)
- `redirection_url` (String)
- `webhook` (String, nullable)
- `created_at` (UTC datetime)
- **No TTL attribute. No last-accessed tracking.** ← this is the whole problem.

Config / secrets (currently hardcoded in `constants.py` / `zappa_settings.json`):
- `SECRET_KEY` production = `batman-beats-superman-any-day` (move to a real secret store).
- `WEBHOOK` default `None`; `NOT_FOUND_URL` unused in redirect path.

Webhook behavior: on redirect, if a webhook is set, async GET it with up to 3
retries (`call_url` via `zappa.asynchronous.task`). **Bug to fix in Go:**
`get_hook()` in `app.py` builds the `?path=` URL but never assigns it (the
`webhook + '...'` expressions are discarded), so the `path` query param is never
actually appended today.

---

## Traffic findings (benchmark targets) — measured 2026-06-14 → 2026-06-21

Source: CloudWatch `AWS/Lambda` for `elchapo-production`, per-minute over 7 days
(10,079 minutes). Cross-checked vs API Gateway `Count`. Async `@task` webhook
invocations are negligible (~15/hr), so Invocations ≈ real redirect requests.

**KEY FINDING — this is a WRITE-heavy workload, not a redirect service.**
Splitting by endpoint via DynamoDB per-operation counts (`SuccessfulRequestLatency`
SampleCount; API Gateway method-level metrics aren't enabled and logs are gone):
- `POST /c` (create) = **97.9%** of traffic (~4.43M req/wk) — counted as `PutItem`.
- `GET /<path>` (redirect) = **2.1%** of traffic (~95K req/wk) — counted as
  `GetItem − PutItem`.

Only ~2% of created links are ever clicked. The two endpoints must be benchmarked
and scaled **separately**; the redirect path is trivial, the create path is the
whole game.

**Per-endpoint RPS** (per-minute → RPS, percentiled across the week):

| metric | POST `/c` (write) | GET `/<path>` (read) |
|---|---:|---:|
| p50 | 1.42 | 0.12 |
| p90 | 29.9 | 0.33 |
| p99 | 67.9 | 0.72 |
| max (busiest min) | 103.4 | 5.65 |
| weekly avg | 7.3 | 0.16 |
| peak minute | 6,204 req | 339 req |

**Per-endpoint response time** (ms; `POST /c` measured via API GW `Latency`
≈whole-API since it's 98% of traffic; `GET /<path>` derived = POST minus one
`PutItem`, webhook is async/non-blocking):

| pctl | POST `/c` | GET `/<path>` |
|---|---:|---:|
| p50 | 40 | ~36 |
| p90 | 55 | ~51 |
| p99 | 96 | ~88 |
| max | ~29,000 ⚠️ | ~29,000 ⚠️ |

Measured DynamoDB op latency (the per-endpoint DB component): `GetItem` p50 1.3 /
p99 7.9 ms; `PutItem` p50 3.3 / p99 8.1 ms. The Lambda's ~40ms p50 is dominated by
Lambda/API-GW overhead, NOT DynamoDB — a warm Go server on EC2 should hit
single-digit-ms p50.

⚠️ The ~29s max is a Lambda **cold-start** outlier. `models.py` runs
`ShortURL.exists()` (DescribeTable) at import and would call `create_table(wait=True)`
if it read as missing — table management on the request path. In Go: do all
table/TTL setup at deploy time, never per-request. A warm Go server should erase
this tail.

- **Max concurrency** (`ConcurrentExecutions`, per-minute Maximum): **peak 25**,
  p99 17, p50 2. Rarely >25 functions at once (mostly the write path).
- Shape: bursty, business-hours. Peak 07:00–08:00 UTC (~12:30 IST), near-idle
  20:00–02:00 UTC.

Caveat: CloudWatch's finest standard resolution is 1 minute, so `max` = busiest
minute's average; true sub-minute peaks are likely somewhat higher.

### Scale targets the Go service must pass — 10× per endpoint (set by Sankalp)

| endpoint | measured peak | **10× throughput target** | latency SLO |
|---|---:|---|---|
| **POST `/c`** (write) | 103 RPS | **~1,000 RPS sustained** | **p50 < 50ms & p99 < 100ms** (today 40 / 96ms) |
| **GET `/<path>`** (read) | 5.65 RPS | 10× ≈ 57 RPS → **use 100 RPS** for headroom | **p50 < 50ms & p99 < 100ms** (today ~36 / ~88ms) |

- **Latency SLO: preserve current response times — p50 < 50ms AND p99 < 100ms for
  BOTH endpoints** at the 10× load above. Today's Lambda already sits at p50 40ms /
  p99 96ms (POST) and p50 ~36ms / p99 ~88ms (GET); a warm Go server on EC2 should
  beat this with single-digit-ms p50. This is a no-regression bar, not a stretch goal.
- **Concurrency: 50 in-flight at peak** (≈2× the measured peak of 25). Go needs far
  less concurrency than Lambda per RPS (one process + goroutines vs Lambda's
  1-request-per-container model), so 50 is the design ceiling.
- The create (write) path is the real load — load-test `POST /c` to 1,000 RPS first.
  The redirect path only needs to clear 100 RPS, trivially.
- A single modest EC2 box + Go should handle this comfortably; the likely bottleneck
  at 10× is **DynamoDB write** throughput / hot-partition behavior (it's
  write-dominated), not the app or reads.

---

## TTL design — the key decision

The original question was "what's the oldest DynamoDB row still being accessed, so
we can set a TTL?" **That can't be answered from current data:**
1. Schema has no last-accessed field — DynamoDB only knows `created_at`, never
   when a link was last clicked.
2. No DynamoDB read perms on these creds (Scan/Query/DescribeTable → AccessDenied).
3. Prod Lambda logs: 1-day retention, 0 bytes stored, newest streams stale (Sep
   2024). No history to mine for which old links still get hit.

**The Go rewrite makes this moot — use a sliding TTL instead of a fixed one:**
- Add a `ttl` attribute (Number, epoch seconds) and enable DynamoDB native TTL on it.
- On every `GET /<path>` redirect, set `ttl = now + N days` (e.g. N=90). Optionally
  also write `last_accessed`.
- Result: any link that's still clicked auto-extends and never expires; only links
  dormant for N days get reaped by DynamoDB TTL. The bill sheds dead rows without
  ever breaking a live link — and we never needed the historical "oldest accessed"
  number. Pick N conservatively (90d is safe); it can be tuned later once
  `last_accessed` data accumulates.
- Backfill: existing rows have no `ttl`. Decide a one-time backfill (e.g. set
  `ttl = created_at + N days`, or a longer grace for legacy rows) so old rows
  eventually expire. **Risk:** a backfill that's too aggressive could expire a
  still-used legacy link before it gets re-clicked. Prefer a long initial grace.
- The sliding update is a cheap conditional `UpdateItem` per redirect; only update
  when the stored ttl is > ~1 day old to avoid a write on every single hit.

---

## Build checklist (next session)

- [ ] Scaffold Go module + minimal HTTP server (stdlib `net/http` or chi/echo).
- [ ] AWS SDK v2 DynamoDB client; model with `url`, `redirection_url`, `webhook`,
      `created_at`, `ttl`, `last_accessed`.
- [ ] Implement `POST /c` (secret auth, dup check → 409), `GET /<path>` (302 +
      sliding ttl update + async webhook w/ 3 retries, fixing the `get_hook` bug),
      `GET /` health.
- [ ] Move `SECRET_KEY` out of source into env / secrets manager.
- [ ] Dockerfile (multi-stage, scratch/distroless final image).
- [ ] Decide EC2 host (which instance? — open question), deploy method
      (docker run / compose / behind nginx or ALB), and how it gets the DNS that
      API Gateway currently fronts.
- [ ] Enable DynamoDB native TTL on the `ttl` attribute; plan the backfill.
- [ ] Grant the EC2 IAM role DynamoDB R/W on the table.
- [ ] Load test to the 10x targets above before cutover.

## Open questions for Sankalp
- Which EC2 instance hosts it? What's already running there?
- TTL window N — 90 days OK as the starting sliding window?
- Keep API Gateway / the existing public URL in front, or expose EC2 directly
  (ALB/nginx + the current domain)?
- Backfill policy for legacy rows with no `ttl`.
- Need DynamoDB read access granted if we want to inspect the real `created_at`
  distribution before deciding the backfill grace.
