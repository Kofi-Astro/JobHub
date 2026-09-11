# JobHub — System Architecture

This document is the design of record. It explains **what** each part of the
system does and **why** it is shaped that way. Code comments explain the local
detail; this file explains the system.

---

## 1. Goals and constraints

| # | Requirement (from the brief)                                                        | Design consequence |
|---|------------------------------------------------------------------------------------|--------------------|
| 1 | Aggregate real jobs from many worldwide sources into one searchable platform       | Source-adapter pattern; normalized `jobs` table; Postgres full-text search |
| 2 | Companies can also post listings directly                                          | `origin` discriminator on `jobs`; employer submissions enter the same pipeline at the normalize/categorize stage |
| 3 | Every listing leads to a **direct** application path — no gates, no middlemen       | `apply_url` / `apply_email` stored verbatim from the source; apply button links straight out; no account required to view or apply |
| 4 | Global from day one; no restructuring to add a country                             | Location stored as structured ISO fields (`country_code`, `region`, `city`) + raw string; no country tables to extend |
| 5 | Prioritize APIs/feeds over scraping                                                | Adapters are API-first; a `ScraperAdapter` base exists but ships disabled |
| 6 | Paid API tiers are a **config change, not a rewrite**                              | `sources` table carries `tier`, `rate_limit_per_min`, `requires_api_key`, `api_key_ref`, `config` JSON |
| 7 | Dedupe identical postings across sources                                           | `dedupe_hash` + canonical-row pointer; only canonical rows surface in search |
| 8 | Employer jobs and aggregated jobs appear side by side, no visual bias              | Same `jobs` table, same search path, same card; only an optional "Direct from employer" badge |
| 9 | Job seekers need **zero** account; employers **must** have one                     | Anonymous browsing everywhere; `users.role` separates seeker/employer/admin; anon state in `localStorage` |
| 10| Non-technical admin panel manages taxonomy, sources, moderation, content, users   | Admin API + `admin.html`; everything data-driven from DB, nothing hard-coded |
| 11| Visa sponsorship is nice-to-have; never inferred from scraped data                 | `jobs.visa_sponsorship` is `NULL` unless an employer ticks the box; no parser |
| 12| Comment code extensively                                                          | Every module/class/non-trivial function documents what + why |

Non-goals for v1: paid employer plans (schema is ready, billing is not),
Meilisearch/Typesense (Postgres FTS is structured to migrate later), a mobile app.

---

## 2. High-level shape

```
                 ┌──────────────────────────────────────────────────────┐
                 │                    INGESTION                          │
  external APIs  │  SourceAdapter.fetch()  ──►  RawJob (dataclass)       │
  (Remotive,     │        │                                             │
   Greenhouse,   │        ▼                                             │
   Lever, …)     │   normalize()  ──►  dedupe()  ──►  categorize()       │
                 │        │                              │              │
                 └────────┼──────────────────────────────┼──────────────┘
                          │                              │
 employer form ───────────┴───────► (enters here) ───────┘
 (self-categorized,                          │
  moderation-gated)                          ▼
                                     ┌───────────────┐
                                     │   PostgreSQL  │  jobs, sources, taxonomy,
                                     │   (storage +  │  users, saved_*, analytics,
                                     │    FTS index) │  site_content, audit_log
                                     └───────┬───────┘
                                             │
                                     ┌───────▼───────┐
                                     │  FastAPI      │  /api/jobs (search+filter+facets)
                                     │  (read + write│  /api/taxonomy  /api/auth
                                     │   API)        │  /api/seeker  /api/employer  /api/admin
                                     └───────┬───────┘
                                             │  JSON
                                     ┌───────▼───────┐
                                     │  Static       │  index.html  job.html
                                     │  frontend     │  employer.html  admin.html
                                     │  (vanilla JS) │  ES-module components
                                     └───────────────┘

   ┌──────────────────────────────────────────────────────────────────┐
   │  WORKER (separate process, APScheduler)                           │
   │   • per-source refresh jobs (interval from sources.refresh_*)     │
   │   • expire stale aggregated listings (last_seen_at too old)       │
   │   • send saved-search alert emails (daily/weekly)                 │
   │   • roll up analytics snapshots                                   │
   └──────────────────────────────────────────────────────────────────┘
```

### Separation of concerns (the pipeline)

`ingestion (adapters) → normalization/dedupe → categorization → storage → API → frontend`

Each stage has a single responsibility and a typed hand-off object, so a stage can
be changed or tested in isolation:

| Stage | Input | Output | Module |
|-------|-------|--------|--------|
| Ingestion | source config | `list[RawJob]` | `app/ingestion/adapters/*` |
| Normalization | `RawJob` | `NormalizedJob` | `app/ingestion/normalize.py` |
| Dedupe | `NormalizedJob` + DB | canonical decision | `app/ingestion/dedupe.py` |
| Categorization | `NormalizedJob` | `(field_id, subfield_id, method, confidence)` | `app/categorization/classifier.py` |
| Storage | `NormalizedJob` + category | upserted `jobs` row | `app/ingestion/pipeline.py` |
| API | query params | JSON | `app/api/routes/*` |
| Frontend | JSON | DOM | `frontend/js/*` |

**Employer submissions** are constructed as a `NormalizedJob` directly from the
posting form and enter at the *normalization/dedupe* boundary. They skip
auto-categorization (the employer picked field/sub-field) and carry
`moderation_status = pending` until an admin approves.

---

## 3. Data model

All tables use `uuid` primary keys (generated app-side) except high-volume
append-only logs which use `bigint` identity. Every table has `created_at`;
mutable tables also have `updated_at` (touched by a SQLAlchemy event listener).

Timestamps are `timestamptz`, always stored UTC.

### 3.1 `sources` — the adapter registry (admin-managed)

Why a table and not code: the brief requires adding/disabling sources and
flipping free↔paid tiers **without touching code**. Adapter *logic* is code
(one class per source shape); adapter *configuration* is a row.

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid | |
| `key` | text unique | machine name, e.g. `remotive`, `greenhouse` |
| `name` | text | display name |
| `adapter` | text | which adapter class handles it (`registry` key). Many sources can share one adapter — e.g. every Greenhouse board uses `greenhouse` with a different `config.board_token`. |
| `kind` | enum `aggregator \| ats \| scraper` | |
| `tier` | enum `free \| paid` | **the paid-tier hook** |
| `enabled` | bool | admin on/off switch |
| `base_url` | text null | adapter default if unset |
| `config` | jsonb | adapter-specific: Greenhouse board tokens, Adzuna country list, Lever company slugs, result caps, etc. |
| `requires_api_key` | bool | |
| `api_key_ref` | text null | **name of the env var / Railway secret** holding the key. The key itself is never stored in the DB. |
| `rate_limit_per_min` | int null | token-bucket limit applied by the fetch client |
| `request_timeout_seconds` | int | default 30 |
| `refresh_interval_minutes` | int | how often the worker schedules this source (default 360) |
| `priority` | int | dedupe tie-breaker; higher wins as canonical (employer 100 > ATS 50 > aggregator 10) |
| `last_run_at` / `last_success_at` / `last_error_at` | timestamptz null | health surface for admin |
| `last_error` | text null | |
| `consecutive_failures` | int | worker backs off / admin alerts when high |

`source_runs` records one row per ingestion run (started/finished, status,
counts of seen/created/updated/expired/failed, error, structured `log` JSON) so
the admin "sync health" screen has real history.

### 3.2 Taxonomy — `fields` → `subfields`

Two-level hierarchy, both editable in the admin panel.

- `fields`: `slug` (unique), `name`, `description`, `display_order`, `icon`, `is_active`.
- `subfields`: `field_id`, `slug`, `name`, `display_order`, `is_active`,
  **`keywords text[]`** — the terms the keyword classifier matches against job
  title/description. Unique on `(field_id, slug)`.

Remapping: admin picks a subfield, reassigns its jobs to another subfield; the
change is written to `audit_log`. Deleting a field/subfield is blocked while jobs
reference it (must remap first) — enforced in the service layer with a friendly
error, not just an FK violation.

### 3.3 `companies`

Lightweight. Aggregated jobs resolve to a company by normalized-name match
(create-if-missing). Employer jobs link to the employer's company.
`is_verified` = an employer has claimed and been approved for this company.
`slug` unique for clean URLs.

### 3.4 `jobs` — the core table

The single table every listing lives in, aggregated or employer-posted.

**Identity / provenance**

| Column | Notes |
|--------|-------|
| `origin` | enum `aggregated \| employer` — the only structural difference between the two kinds |
| `source_id` | FK `sources`, **null for employer jobs** |
| `posted_by_user_id` | FK `users`, **null for aggregated jobs** |
| `company_id` | FK `companies`, nullable until resolved |
| `external_id` | id in the source system; unique per source (`unique(source_id, external_id)`) |
| `source_url` | canonical posting URL on the source |
| `apply_url` / `apply_email` / `apply_instructions` | the **direct application path** — stored exactly as provided |
| `raw` | jsonb — original payload, kept for debugging + re-categorization without re-fetching |

**Content**

`title`, `description_html` (sanitized), `description_text` (plaintext, drives
search + classifier), `company_name_raw`.

**Location (structured, global-safe)**

`location_raw`, `city`, `region`, `country_code` (ISO 3166-1 alpha-2),
`country_name`, `is_remote`, `workplace_type` (enum
`remote \| hybrid \| onsite \| unknown`), `remote_scope` (free text like
"worldwide" / "US only" — shown, not filtered).

**Compensation**

`salary_min`, `salary_max`, `salary_currency` (ISO 4217), `salary_period`
(enum `year \| month \| week \| day \| hour`), `salary_is_disclosed`.
When not disclosed the UI shows "Not disclosed" — **never hidden** (brief).

**Classification**

`job_type` (enum `full_time \| part_time \| contract \| internship \| temporary \| other \| unknown`),
`experience_level` (enum `entry \| mid \| senior \| lead \| unknown`),
`field_id`, `subfield_id`, `categorization_method`
(enum `keyword \| employer \| admin \| none`), `categorization_confidence` (float),
`is_uncategorized` (bool, mirrors `field_id IS NULL`, indexed for the admin queue).

`visa_sponsorship` (bool, **nullable, default NULL**) — only ever set from the
employer posting checkbox. Aggregated ingestion never writes it.

**Lifecycle**

| Column | Notes |
|--------|-------|
| `status` | enum `active \| pending \| rejected \| closed \| expired \| hidden` |
| `moderation_status` | enum `not_required \| pending \| approved \| rejected` (employer flow, orthogonal to `status`) |
| `posted_at` | when it went live at the source |
| `ingested_at` | when we first saw it |
| `last_seen_at` | last ingestion run that still listed it — drives staleness expiry |
| `expires_at` | explicit expiry if the source gives one |

**Dedupe**

`dedupe_hash` (sha1 of normalized company+title+country+workplace_type),
`canonical_job_id` (self-FK; null if this row *is* canonical), `is_canonical`.
Search filters to `is_canonical = true`.

**Search + metrics**

`search_vector tsvector GENERATED ALWAYS AS (...) STORED` with a GIN index —
built from title (weight A), company (B), location (C), description (D).
`view_count`, `apply_click_count` (incremented via lightweight endpoints; the
authoritative event history is in `analytics_events`).

Key indexes: GIN(`search_vector`); btree(`status`, `posted_at desc`);
btree on each filter column; `unique(source_id, external_id)`;
btree(`dedupe_hash`); btree(`is_uncategorized`) partial where true.

### 3.5 Users and roles

One `users` table, `role` enum `seeker \| employer \| admin`. Role-specific data
lives in satellite tables so the core stays lean and the separation is explicit:

- `users`: `email` (citext, unique), `password_hash` (nullable — OAuth-ready),
  `full_name`, `is_active`, `is_email_verified`, `last_login_at`.
- `employer_profiles` (1:1, role=employer): `company_id`, `job_title`, `phone`,
  `account_status` (enum `pending \| approved \| rejected \| suspended`),
  `approved_by`, `approved_at`, `rejection_reason`,
  **`plan` (text null = free)**, **`plan_expires_at`**, **`posting_quota` (int null = unlimited)** — the monetization hooks.
- `admin_profiles` (1:1, role=admin): `admin_role` enum
  `superadmin \| moderator \| editor \| analyst`. Permission checks map
  `admin_role` → allowed actions in `app/services/authz.py`.
- `refresh_tokens`: hashed refresh tokens with `expires_at`, `revoked_at`,
  `user_agent`, `ip` for rotation + revocation.

**Why not separate `seekers` / `employers` tables?** Auth (hashing, tokens,
login) is identical for all three; duplicating it invites drift. Separation is
enforced where it matters: distinct signup endpoints, distinct dashboards, and
role checks on every protected route.

### 3.6 Job-seeker state

- `saved_jobs`: `(user_id, job_id)` unique, optional `notes`.
- `saved_searches`: `name`, `query_params` jsonb (the serialized filter state),
  `alert_enabled`, `alert_frequency` (enum `daily \| weekly`), `last_alerted_at`,
  `last_checked_at`. Alerts are a flag on a saved search, not a separate concept.
- `alert_deliveries`: log of sent alerts (`saved_search_id`, `sent_at`,
  `job_count`, `status`).

**Anonymous users**: the same state (last search, saved job ids, filter panel
collapse) is mirrored to `localStorage` by the frontend `store` module. Signing
in merges the local state into the account once.

### 3.7 Admin / content / audit

- `site_content`: `key` unique (`homepage.featured_fields`, `homepage.hero`),
  `value` jsonb — homepage is data-driven.
- `announcements`: `title`, `body`, `level`, `is_active`, `starts_at`, `ends_at`.
- `analytics_events`: `bigint` id, `event_type` enum, `occurred_at`, `session_id`,
  `user_id?`, `job_id?`, `source_id?`, `properties` jsonb. Append-only; indexed on
  `(event_type, occurred_at)`. v1 keeps raw rows; a later migration can partition
  by month and pre-aggregate.
- `audit_log`: `actor_user_id`, `action`, `entity_type`, `entity_id`, `before`,
  `after` jsonb — every admin mutation and every taxonomy remap.

---

## 4. Ingestion

### 4.1 The adapter contract

```python
class SourceAdapter(ABC):
    key: str                      # matches sources.adapter
    kind: SourceKind              # aggregator | ats | scraper

    def fetch(self, source: SourceConfig) -> Iterable[RawJob]: ...
```

- `SourceConfig` is a frozen snapshot of the `sources` row (plus the resolved API
  key from the environment) — adapters never touch the DB or ORM.
- `RawJob` is a permissive dataclass: every field optional, strings mostly
  unparsed. The adapter's only job is to pull data and map source field names to
  `RawJob` field names. All cleaning happens in `normalize()`.
- Adapters are pure/streaming where possible and fully covered by contract tests
  that run against **recorded fixture payloads** (`backend/tests/fixtures/`), so
  CI never hits a live API.

Registry: `app/ingestion/registry.py` maps `adapter` string → class. Adding a
source that fits an existing shape (another Greenhouse/Lever/Ashby board) is a
row insert with no code. Adding a genuinely new shape is one new class + one
registry line.

### 4.2 Adapters shipped in v1

| Adapter | Kind | API key? | Coverage |
|---------|------|----------|----------|
| `remotive` | aggregator | no | remote jobs, global |
| `remoteok` | aggregator | no | remote jobs, global |
| `arbeitnow` | aggregator | no | EU + remote |
| `greenhouse` | ats | no | per-company boards (`config.board_token`) |
| `lever` | ats | no | per-company boards (`config.company`) |
| `ashby` | ats | no | per-company boards (`config.org`) |
| `adzuna` | aggregator | **yes** (`ADZUNA_APP_ID` / `ADZUNA_APP_KEY`) | ~20 countries — **config-stubbed, disabled until keys set** |
| `jooble` | aggregator | **yes** (`JOOBLE_API_KEY`) | global — config-stubbed, disabled |
| `usajobs` | aggregator | **yes** (`USAJOBS_API_KEY`) | US federal — config-stubbed, disabled |

Keyed adapters are fully implemented but seeded `enabled = false` with
`tier`/`api_key_ref` set. Turning one on = add the secret in Railway, flip
`enabled` in admin. That is the "paid tier is a config change" requirement made
concrete.

### 4.3 Normalization

`normalize(RawJob) -> NormalizedJob` centralizes every messy transform:

- HTML sanitize (`bleach` allowlist) → `description_html`; strip → `description_text`.
- Location parsing: recognise "Remote", "Remote (US)", "Berlin, Germany",
  "London, UK", ISO codes; fill `country_code`/`country_name` via a static
  `pycountry`-backed lookup; set `workplace_type`.
- Salary parsing: ranges, single values, "$", "k", "per year/hour", currency
  words → `salary_min/max/currency/period`; unset ⇒ `salary_is_disclosed = false`.
- Job type / experience level: map source vocab + keyword fallback to our enums;
  unknown stays `unknown` (never guessed away).
- Dates: parse to UTC; missing `posted_at` falls back to `ingested_at`.

### 4.4 Dedupe

Cross-source duplicates are common (the same role on Remotive and the company's
Greenhouse board).

1. Compute `dedupe_hash = sha1(normalize_company | normalize_title | country_code | workplace_type)`.
2. On upsert, look for existing canonical rows with the same hash.
3. If found, the higher `sources.priority` row is canonical; the other gets
   `canonical_job_id` set and `is_canonical = false`.
4. Search / listing endpoints always filter `is_canonical = true`. The detail
   page can show "Also listed on: …" from the shadowed rows.

This is deliberately conservative (exact hash, not fuzzy) — a missed dupe is a
minor UX wart; a wrong merge hides a real job.

### 4.5 Upsert + expiry

- Upsert key: `(source_id, external_id)`. Existing row → update mutable fields,
  bump `last_seen_at`. New → insert.
- After a **full** successful run for a source, any of that source's `active`
  jobs whose `last_seen_at` is older than the run start are marked `expired`
  (they fell off the source). Partial/failed runs never expire anything.
- A nightly worker task also expires anything past an explicit `expires_at`.

---

## 5. Categorization

`app/categorization/classifier.py` — deterministic keyword scoring, no ML in v1.

```
for each subfield:
    score = 3 * (keyword hits in title) + 1 * (keyword hits in description_text)
pick argmax; require score >= MIN_SCORE and margin over runner-up >= MIN_MARGIN
else field_id = subfield_id = NULL, is_uncategorized = true  → admin review queue
```

- Keywords live in `subfields.keywords` (admin-editable), seeded generously.
- `categorization_confidence` = normalized top score, stored for admin triage
  ordering.
- **Employer jobs**: the form makes the employer pick field + sub-field from the
  live taxonomy, so `categorization_method = employer`, classifier skipped.
- Re-categorization: admin "re-run classifier" action reprocesses using `raw` +
  current keywords without re-fetching.

Why keyword and not an LLM/embedding: transparent, instant, free, debuggable by a
non-technical admin (they can see *which* keyword matched and fix the list). The
`classify()` signature returns a result object, so a smarter backend can be
dropped in later behind the same call site.

---

## 6. Search and filtering

### 6.1 Search

Postgres FTS via the generated `search_vector` column + `plainto_tsquery` (with a
`websearch_to_tsquery` upgrade path for quoted phrases). Results ranked by
`ts_rank_cd(search_vector, query)` blended with recency
(`posted_at`). No search term ⇒ order by `posted_at desc`.

`app/services/search.py` builds one SQLAlchemy `Select` from a `JobQuery`
value-object. The query object — not raw request parsing — is the seam a future
Meilisearch/Typesense backend implements. Nothing else in the app knows how
search works.

### 6.2 Filters (all combinable, all optional)

| Filter | Column(s) | UI |
|--------|-----------|----|
| Field / sub-field | `field_id`, `subfield_id` | nested checkboxes |
| Location | `city` / `country_code` / `is_remote` | typeahead |
| Workplace | `workplace_type` | remote / hybrid / onsite toggles |
| Salary range | `salary_min/max` overlap | min/max inputs; "include not disclosed" toggle (default on) |
| Job type | `job_type` | checkboxes |
| Experience | `experience_level` | checkboxes |
| Date posted | `posted_at` | last 24h / 7d / 30d |
| Source | `source_id` / `origin='employer'` → "Direct from employer" | checkboxes |
| Country / region | `country_code` | select |
| Visa sponsorship | `visa_sponsorship = true` | **shown only if ≥1 job has a non-null value** (feature-flagged by data presence) |

Salary filtering never removes `salary_is_disclosed = false` rows unless the user
explicitly turns off "include not disclosed".

### 6.3 Facet counts ("live result counts")

`GET /api/jobs/facets` returns, for each filter dimension, the count **as if that
one dimension's selection were cleared** (standard faceted-search behaviour so
counts don't all collapse to the current result set). Implemented as one grouped
aggregate query per dimension against the filtered base; cached 60s per
filter-signature in-process (Redis-ready).

### 6.4 API surface

```
GET  /api/jobs                 list + search + filter + paginate + sort
GET  /api/jobs/facets          per-dimension counts for the current filter
GET  /api/jobs/{id}            full detail (+ shadowed dupes, related jobs)
POST /api/jobs/{id}/view       increment view_count (fire-and-forget beacon)
POST /api/jobs/{id}/apply-click  increment apply_click_count, log event, return apply target

GET  /api/taxonomy            fields + subfields tree (public, cached)
GET  /api/meta/countries     distinct countries present in active jobs
GET  /api/meta/sources       public source list for the Source filter

POST /api/auth/register/seeker | /register/employer
POST /api/auth/login | /refresh | /logout
GET  /api/auth/me

GET/POST/DELETE /api/seeker/saved-jobs
GET/POST/PATCH/DELETE /api/seeker/saved-searches
POST /api/seeker/merge-anon           merge localStorage state on first login

POST /api/employer/jobs               create (→ moderation)
GET  /api/employer/jobs               my listings + counts
PATCH/POST /api/employer/jobs/{id}    edit / close / republish
GET  /api/employer/stats             view + apply-click counts

/api/admin/*   taxonomy, sources, source-runs, moderation queue, jobs,
               users, employers, site-content, announcements, analytics
```

Auth: JWT access token (15 min) in `Authorization: Bearer`, refresh token (30 d,
rotating) in an httpOnly cookie. Public endpoints need nothing. `X-Session-Id`
header (client-generated UUID in `localStorage`) ties anonymous analytics events
together.

**Cross-site cookie note**: the frontend and API are separate origins, so every
call the frontend makes — including the silent `/api/auth/refresh` on page
load — is a cross-site fetch from the browser's perspective. The refresh
cookie is `SameSite=None; Secure` in staging/production (required for a
cross-site cookie to be sent on `fetch`/XHR at all) and falls back to
`SameSite=Lax` locally, because `SameSite=None` requires `Secure`, which
requires HTTPS — something plain-HTTP local dev cannot provide. This means
silent refresh across two localhost ports is a known, accepted local-only
limitation (the in-memory access token still works fine within one page
session); the production path, over HTTPS, works correctly. This was found by
an end-to-end browser test, not the API test suite — FastAPI's `TestClient`
doesn't enforce `SameSite` the way a real browser does, so a regression here
needs a real-browser check, not just more unit tests.

---

## 7. Frontend

Static files, no build step beyond Tailwind. ES modules, no framework, organized
into `components/` (pure render functions returning DOM), `pages/` (wire
components + API + URL state), `api/` (typed fetch client), `store/` (state +
`localStorage`), `util/`.

- **`index.html`** — search-first hero, then results grid + persistent
  collapsible filter sidebar with live counts. Filter + search + page state lives
  in the URL query string (shareable, back-button-friendly) and is mirrored to
  `localStorage` for "resume where you left off".
- **`job.html?id=…`** — detail + a large, unmissable **Apply** button that hits
  `/apply-click` then navigates to the real `apply_url`.
- **`employer.html`** — clearly separate "Post a job" entry: login/register,
  dashboard (list + counts), posting form (same structured fields as scraped
  jobs; field/sub-field picked from live taxonomy).
- **`admin.html`** — tabbed panel over `/api/admin/*`.

Mobile-first: the filter sidebar becomes a bottom-sheet under `md`. Job cards are
a single responsive component shared by every listing context.

No visual bias: employer and aggregated jobs render with the identical card;
`origin === 'employer'` adds only a subtle "Direct from employer" badge.

---

## 8. Background worker

`app/worker/run.py` starts APScheduler (`AsyncIOScheduler`) in its own process.

| Job | Trigger | Action |
|-----|---------|--------|
| `refresh_source:<key>` | interval = `sources.refresh_interval_minutes` | run that adapter through the pipeline, write a `source_runs` row |
| `expire_stale` | hourly | mark aggregated `active` jobs unseen for > N days (per-source configurable) as `expired` |
| `send_alerts` | hourly | for due `saved_searches` with `alert_enabled`, run the query, email new matches, log `alert_deliveries` |
| `analytics_rollup` | daily | snapshot counts for the admin dashboard |
| `source_health_check` | every 15 min | flag sources with high `consecutive_failures` |

Why APScheduler over Celery for v1: no broker to run, in-process scheduling is
enough for periodic work at this scale, and one fewer service on Railway. The
task functions are plain callables invoked by name — moving to Celery later is
wrapping them in `@task` and swapping the scheduler, not rewriting them.

Rate limiting + caching for external calls: `app/ingestion/http.py` wraps `httpx`
with a per-source token-bucket (`rate_limit_per_min`), ret/backoff on 429/5xx,
and an ETag/Last-Modified response cache keyed by URL.

---

## 9. Deployment

```
Railway project
├── Postgres plugin        → injects DATABASE_URL
├── service: api           Dockerfile, CMD = uvicorn …            (railway.json)
│     health: GET /api/health
└── service: worker        same Dockerfile, start = python -m app.worker.run
```

- One image, selected behaviour by start command — keeps api/worker byte-identical.
- Migrations run on release via `release` phase (`alembic upgrade head`) so a bad
  migration blocks the deploy instead of half-migrating.
- Secrets (`JWT_SECRET`, `ADZUNA_*`, SMTP, …) set in the Railway dashboard,
  referenced by name from `sources.api_key_ref`.
- The static frontend deploys anywhere (Railway static service, Netlify, a CDN);
  it only needs `API_BASE_URL` baked into `frontend/js/config.js` (or read from a
  `<meta>` tag) at deploy time.

## 10. Testing

- **Adapter contract tests**: each adapter runs against a recorded fixture and
  must yield `RawJob`s satisfying shared assertions (has apply path, has title,
  dates parse). No network in CI.
- **Normalization tests**: table-driven — messy input string → expected
  structured output (locations, salaries, job types).
- **Dedupe tests**: same role from two sources collapses to one canonical row.
- **Classifier tests**: seeded taxonomy + sample titles → expected subfield.
- **API tests**: FastAPI `TestClient` against a transactional test database
  (rolled back per test).

## 11. Build order (tracks the brief)

1. Scaffold + data models + migrations + seeds ← *milestone 1–2*
2. Adapter framework + 2 adapters end-to-end + normalize + dedupe ← *3–4*
3. Search/filter/listing API + frontend against real seeded data ← *5–6*
4. Job detail + apply flow ← *7*
5. Categorization + admin taxonomy management ← part of *4, 11*
6. Optional job-seeker accounts, saved state, alerts ← *8–9*
7. Employer registration + posting portal + moderation queue ← *10*
8. Full admin interface ← *11*
