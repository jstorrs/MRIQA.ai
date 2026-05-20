# MRIQA.ai — SaaS Architecture Blueprint

**Status:** design document (v0.1)
**Author target:** founding engineer + CTO + cloud/security lead
**Scope:** evolve the existing Streamlit MVP into a production multi-tenant SaaS that imaging centers can use for ACR accreditation, ongoing MRI QA, and (later) advanced QA workflows (B0 mapping, MR-Linac, AI artifact detection).

This document captures the *whole* technical picture. A companion document, [`saas_roadmap.md`](./saas_roadmap.md), sequences the work into phases and lays out the business model. **Read this one for shape, that one for order.**

---

## 1. Product context

### 1.1 Who we're serving

Three distinct buyer/user types shape every architectural choice below.

The **medical physicist** is the primary daily user. They run weekly/monthly phantom scans on each scanner, need fast turnaround on a clean PDF that goes into accreditation evidence, and want long-term trend lines so they can catch drift before action limits are hit. They are a senior technical user — they will inspect the algorithm, demand to see ROI overlays, and want to override anything we got wrong.

The **imaging center administrator** never opens a DICOM but cares deeply about per-scanner pass/fail dashboards, ACR audit-readiness, and "are we still in compliance?" status views. They sign the contract.

The **QA technologist** at the modality is the person who actually walks the phantom into the bore. They need a 30-second flow: upload, see results, print, walk away.

### 1.2 What competitors do, and what we do differently

Tools like RadBinder, AQUA, ACR's own portal, and home-grown Excel sheets all exist. The differentiator we're building toward is (a) automated ACR-compliant phantom analysis with visible math, (b) longitudinal per-scanner trending with action-limit alerts, and (c) a clean extension path to non-ACR QA modules (B0, MR-Linac, AI artifact). Nothing here is novel science; what's novel is bundling it as a clean SaaS that a small physics group can adopt in a day.

---

## 2. High-level architecture

The platform breaks into six logical services, each with a clear interface. We do **not** start as microservices — we start as a single modular monolith that has these as packages, and graduate to separate services only when load or team structure justifies it. This is a deliberate anti-overengineering choice: premature microservices is the single most common reason healthtech startups burn out their first engineering year.

```
┌────────────────────┐         ┌─────────────────────────────────────────┐
│   Web frontend     │  HTTPS  │              API gateway                 │
│   (Next.js)        │ ───────►│         (FastAPI + Pydantic v2)          │
│  - dashboards      │         │  - authn (JWT)  - rate limit            │
│  - DICOM upload    │         │  - tenant resolution                    │
│  - report viewer   │         └──┬─────────────────┬──────────────────┬─┘
└────────────────────┘            │                 │                  │
                                  ▼                 ▼                  ▼
                          ┌──────────────┐   ┌─────────────┐   ┌──────────────┐
                          │  Core API    │   │  Reporting  │   │   Admin /    │
                          │  service     │   │  service    │   │   Billing    │
                          │ (Python)     │   │ (ReportLab) │   │  (Stripe)    │
                          └──┬───────────┘   └──────┬──────┘   └───┬──────────┘
                             │                      │              │
                             ▼                      │              │
                     ┌────────────────┐             │              │
                     │  Job queue     │             │              │
                     │  (Celery +     │             │              │
                     │   Redis)       │             │              │
                     └──┬─────────────┘             │              │
                        ▼                           │              │
                ┌──────────────────┐                │              │
                │  QA workers      │                │              │
                │ (existing engine │                │              │
                │  modules: ACR    │                │              │
                │  tests, future   │                │              │
                │  B0/MR-Linac)    │                │              │
                └──┬───────────────┘                │              │
                   │                                │              │
        ┌──────────┴──────────┐                    │              │
        ▼                     ▼                    │              │
┌────────────────┐   ┌────────────────────┐        │              │
│  S3-compat     │   │  PostgreSQL 16     │◄───────┴──────────────┘
│ object store   │   │  - tenant data     │
│ (DICOM, PNG,   │   │  - results         │
│  PDF reports)  │   │  - audit log       │
└────────────────┘   └────────────────────┘
```

The **frontend** is a Next.js app for the product UI and the (eventual) marketing site. The **API gateway** is one FastAPI process that owns authn, tenant resolution, and request routing into internal packages. The **QA workers** are Celery workers that import the exact same analysis modules we already have in `app/qa_tests/`. The **reporting service** is a thin renderer that turns a `TestResult` set into a PDF or HTML snapshot — also reused from the MVP. **PostgreSQL** holds everything structured; **S3-compatible object storage** holds everything binary (DICOM, annotated PNGs, generated PDFs).

The pattern we're following is the one Stripe, Linear, and PostHog all use: monorepo, one main Python service for business logic, one TypeScript frontend, one queue for async work, one Postgres, one object store. It scales further than people think.

---

## 3. Recommended tech stack

Each row notes the alternative we considered and the reason we passed.

| Layer | Choice | Rationale | Considered instead |
|---|---|---|---|
| Frontend framework | **Next.js 14 + TypeScript + Tailwind + shadcn/ui** | App router gives SSR + RSC out of the box, mature ecosystem, easy to ship marketing site in same repo. shadcn/ui gives professional default look without lock-in. | Remix (smaller community), SvelteKit (smaller talent pool for hiring) |
| API framework | **FastAPI (Python 3.12)** | Keeps the analysis code in same language as the existing engine. Async, auto-generated OpenAPI, Pydantic v2 for validation. | Django REST (slower iteration), NestJS (would force IPC to the Python analysis layer) |
| Database | **PostgreSQL 16** | Boring, proven, native JSONB for flexible result schemas, row-level security for multi-tenancy, mature on every major cloud. | MySQL (weaker JSON), Mongo (premature flexibility) |
| Object storage | **S3** (AWS) or **Cloudflare R2** | DICOMs are 100KB-50MB each, and a single scanner generates GB/year. Cheap egress on R2 is attractive; AWS S3 is HIPAA-eligible via BAA. | Storing in Postgres (terrible idea), filesystem (won't scale) |
| Queue | **Celery + Redis** | The Python ecosystem default. Existing analysis code drops in as a Celery task with zero refactor. | Temporal (great but heavy), SQS+Lambda (vendor lock, harder local dev), RQ (smaller community) |
| Cache + session store | **Redis** | Reuse the queue broker; one less moving part. | Memcached (no persistence) |
| Auth | **Clerk** (managed) or **Auth0** for v1 | Outsource auth complexity. Both support orgs, SSO, MFA, magic links, SOC2. Move to self-hosted (e.g. Ory Kratos) only when economics demand it. | Roll-your-own (NIH problem, slows down launch), Supabase (less SaaS-shaped) |
| Billing | **Stripe** | Standard. Built-in tax, invoicing, dunning, customer portal. | Paddle (better for global VAT but less ecosystem) |
| Email | **Resend** or **Postmark** | Transactional only at first. | SES (more setup), SendGrid (legacy) |
| Observability | **Sentry** (errors) + **PostHog** (product analytics) + **Grafana Cloud** (infra metrics) | All three have generous free tiers. | Datadog (great but expensive at our stage) |
| Deployment | **AWS** (HIPAA via BAA) on **ECS Fargate** + **RDS** + **ElastiCache** | The boring, defensible answer for healthcare. BAA available end-to-end. Fargate avoids EC2 babysitting. | Render/Fly (great DX, but BAA path is harder), Kubernetes (overkill until we're hiring SREs) |
| CI/CD | **GitHub Actions** | Same place we store code. | CircleCI (more expensive at scale) |
| Infrastructure as code | **Terraform** | Industry standard, multi-cloud-portable. | Pulumi (newer, smaller community), CDK (vendor lock to AWS) |
| Local dev | **Docker Compose** | One command spins up postgres, redis, the API, workers. | Tilt (overkill for monorepo of this size) |

### 3.1 What we're explicitly *not* using yet

We are not adopting Kubernetes, a service mesh, GraphQL, or microservices at v1. We are not building a custom DICOM PACS — we use a flat object store and metadata in Postgres. We are not training our own ML models in v1 (artifact detection, etc.); those become modules in a later phase.

---

## 4. Multi-tenancy and data model

### 4.1 Tenancy strategy

We adopt **shared schema + tenant ID column + Postgres row-level security (RLS)**. Every tenant-owned table carries an `org_id` column, and every connection sets `SET app.org_id = '<uuid>'` after auth. RLS policies on each table reject any row whose `org_id` doesn't match. This is the same pattern used by Linear, Notion, and most modern B2B SaaS — it gets you 99% of the safety of a separate-database-per-tenant model with 1% of the operational cost.

We reserve schema-per-tenant (or DB-per-tenant) for a future enterprise tier where a customer demands their own database for compliance reasons. That's a configuration switch, not a rewrite, because all tenant access already goes through the same RLS-enforced session variable.

### 4.2 Core entities

```
Organization      one row per paying customer (hospital, imaging group)
 ├── Site         a physical location with one or more scanners
 │    └── Scanner    one MRI unit; serial number, vendor, model, B0, coil set
 ├── User         a human; belongs to one org with one role
 ├── Subscription Stripe customer/subscription state cache
 └── Session      a single QA run on one scanner
       ├── DicomSeries     uploaded series, possibly multiple per session
       ├── TestResult      one per ACR test, per session
       │    └── Measurement
       │         └── Spec  ACR action-limit values used at evaluation time
       └── Report          rendered PDF, hash, signature
```

Plus three cross-cutting tables:

```
AuditLog          immutable, per-org, who-did-what
ApiKey            for org-level API access (future integrations)
ProtocolProfile   per-org library of expected scan parameters (TR/TE, FOV, matrix, etc.) — used for input validation
```

### 4.3 PostgreSQL DDL (excerpt — illustrative, not exhaustive)

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- search

-- Tenant root
CREATE TABLE organizations (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name               text NOT NULL,
    slug               text UNIQUE NOT NULL,                 -- url-friendly handle
    plan               text NOT NULL DEFAULT 'trial',        -- trial|starter|pro|enterprise
    region             text NOT NULL DEFAULT 'us-east-1',
    created_at         timestamptz NOT NULL DEFAULT now(),
    deleted_at         timestamptz
);

CREATE TABLE users (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email              citext NOT NULL UNIQUE,
    name               text,
    role               text NOT NULL DEFAULT 'technologist',  -- admin|physicist|technologist|viewer
    auth_provider_id   text NOT NULL,                         -- Clerk/Auth0 sub
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sites (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name               text NOT NULL,
    timezone           text NOT NULL DEFAULT 'UTC',
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE scanners (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    site_id            uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    name               text NOT NULL,
    vendor             text,                                  -- Siemens, GE, Philips, Canon
    model              text,                                  -- Skyra, Aera, Discovery MR750
    field_strength_t   numeric(3,1),
    serial_number      text,
    coil_set           text,
    accreditation_id   text,                                  -- ACR accreditation # if known
    install_date       date,
    deleted_at         timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, site_id, name)
);

CREATE TABLE sessions (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    scanner_id         uuid NOT NULL REFERENCES scanners(id) ON DELETE CASCADE,
    submitted_by       uuid REFERENCES users(id),
    phantom_type       text NOT NULL DEFAULT 'acr_large',     -- room to add 'acr_small', 'mr-linac'
    status             text NOT NULL DEFAULT 'pending',       -- pending|processing|review|approved|failed
    started_at         timestamptz NOT NULL DEFAULT now(),
    completed_at       timestamptz,
    anonymized         boolean NOT NULL DEFAULT false,
    notes              text
);

CREATE TABLE dicom_series (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    session_id         uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    description        text,
    sequence_type      text,                                  -- T1, T2, Localizer
    n_slices           int,
    pixel_spacing_mm   numeric[],
    slice_thickness_mm numeric,
    storage_uri        text NOT NULL,                         -- s3://bucket/path
    sha256             char(64) NOT NULL,
    size_bytes         bigint NOT NULL,
    uploaded_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE test_results (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    session_id         uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    test_id            text NOT NULL,                         -- e.g. 'geometric_accuracy'
    status             text NOT NULL,                         -- pass|fail|review|error
    passed             boolean,
    notes              text,
    error              text,
    measurements_json  jsonb NOT NULL,                        -- structured measurements
    annotated_image_uris text[],
    spec_snapshot      jsonb,                                 -- the thresholds applied
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reports (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    session_id         uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    pdf_uri            text NOT NULL,
    sha256             char(64) NOT NULL,
    signature_hex      text,                                  -- HMAC over the canonical JSON
    generated_by       uuid REFERENCES users(id),
    generated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    id                 bigserial PRIMARY KEY,
    org_id             uuid NOT NULL,
    actor_user_id      uuid,
    action             text NOT NULL,                         -- e.g. 'session.create'
    target_kind        text,                                  -- 'session','scanner','user'
    target_id          uuid,
    ip                 inet,
    user_agent         text,
    payload            jsonb,
    occurred_at        timestamptz NOT NULL DEFAULT now()
);

-- ----- Row-level security ---------------------------------------------------
ALTER TABLE users         ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites         ENABLE ROW LEVEL SECURITY;
ALTER TABLE scanners      ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE dicom_series  ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_results  ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports       ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log     ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_isolation_users        ON users        USING (org_id = current_setting('app.org_id')::uuid);
CREATE POLICY org_isolation_sites        ON sites        USING (org_id = current_setting('app.org_id')::uuid);
CREATE POLICY org_isolation_scanners     ON scanners     USING (org_id = current_setting('app.org_id')::uuid);
CREATE POLICY org_isolation_sessions     ON sessions     USING (org_id = current_setting('app.org_id')::uuid);
CREATE POLICY org_isolation_series       ON dicom_series USING (org_id = current_setting('app.org_id')::uuid);
CREATE POLICY org_isolation_results      ON test_results USING (org_id = current_setting('app.org_id')::uuid);
CREATE POLICY org_isolation_reports      ON reports      USING (org_id = current_setting('app.org_id')::uuid);
CREATE POLICY org_isolation_audit        ON audit_log    USING (org_id = current_setting('app.org_id')::uuid);

-- Indexes for the common query: "latest sessions for this scanner"
CREATE INDEX sessions_org_scanner_started ON sessions (org_id, scanner_id, started_at DESC);
CREATE INDEX results_session              ON test_results (session_id);
CREATE INDEX audit_org_time               ON audit_log (org_id, occurred_at DESC);
```

The single most important thing here is that **every tenant table has `org_id` and every table has RLS on**. That guardrail catches the entire class of "I forgot a WHERE clause and leaked another customer's data" bugs.

---

## 5. API design

We expose a REST API at `/api/v1/*`. Versioning is in the URL because we want to evolve without breaking integrations. OpenAPI 3.1 is auto-generated from FastAPI — that's the public contract.

### 5.1 Authentication and tenant resolution

Every request must carry a bearer token (JWT issued by Clerk/Auth0). On the way through the gateway:

1. The JWT is verified; the user's `sub` is looked up to resolve the user record.
2. The user's `org_id` becomes the active tenant. We `SET app.org_id = <uuid>` on the Postgres connection for the request.
3. Role-based access checks gate every endpoint via a small decorator: `@requires(role="physicist")`.

For service-to-service or external integration use, an org can mint an **API key** (stored hashed, `prefix_random` like Stripe). The key resolves to a service user with a fixed role.

### 5.2 Endpoint surface (v1)

```
# ----- Auth (mostly handled by Clerk; we expose a thin "me" endpoint)
GET    /api/v1/me                            current user + org

# ----- Organizations + people
GET    /api/v1/orgs/current                  org details, plan, seats used
PATCH  /api/v1/orgs/current                  rename, change region
POST   /api/v1/orgs/current/invitations      invite a user
GET    /api/v1/orgs/current/users            list users
PATCH  /api/v1/orgs/current/users/{id}       change role / deactivate

# ----- Sites + scanners
GET    /api/v1/sites
POST   /api/v1/sites
GET    /api/v1/scanners
POST   /api/v1/scanners
PATCH  /api/v1/scanners/{id}
DELETE /api/v1/scanners/{id}                  soft delete

# ----- QA sessions (the core)
POST   /api/v1/sessions                      create a session (scanner_id, phantom_type, notes)
       → returns presigned upload URLs for the DICOMs
GET    /api/v1/sessions                      filter by scanner_id, status, date
GET    /api/v1/sessions/{id}                 session detail + results
POST   /api/v1/sessions/{id}/finalize        signal "all DICOMs uploaded; start analysis"
       → enqueues Celery jobs
POST   /api/v1/sessions/{id}/approve         physicist approves
POST   /api/v1/sessions/{id}/comments        add a comment
GET    /api/v1/sessions/{id}/report          presigned URL for the PDF

# ----- DICOMs
POST   /api/v1/sessions/{id}/series          register an uploaded series (after the upload completes)
GET    /api/v1/sessions/{id}/series/{sid}    metadata + presigned image URLs

# ----- Trends and dashboards
GET    /api/v1/scanners/{id}/trends?test=geometric_accuracy&from=...&to=...
GET    /api/v1/scanners/{id}/compliance      latest status, days-since-pass, action items
GET    /api/v1/dashboards/overview           org-wide status grid

# ----- Audit
GET    /api/v1/audit?actor=...&action=...&from=...&to=...

# ----- Webhooks (outbound; for customer Slack / Teams)
POST   /api/v1/webhooks                      register a URL + events
DELETE /api/v1/webhooks/{id}

# ----- Billing (mostly redirects to Stripe)
GET    /api/v1/billing/portal                returns a signed Stripe Billing Portal URL
GET    /api/v1/billing/usage                 monthly counters
```

### 5.3 DICOM upload protocol

Direct-to-object-store via presigned PUT URLs. The API never proxies DICOM bytes, which keeps the gateway cheap and CPU-free.

```
1. Client: POST /sessions  →  server creates session in pending, returns up to N presigned PUT URLs
2. Client: PUT each .dcm directly to S3 (or R2)
3. Client: POST /sessions/{id}/series with object keys + SHA-256
4. Client: POST /sessions/{id}/finalize
5. Server: enqueues celery job(s), session -> processing
6. Worker: pulls DICOMs from S3, runs the analysis (existing modules), writes annotated PNGs back to S3, inserts test_results rows, session -> review
7. Server: posts webhook event qa.session.completed
```

### 5.4 Error model

All errors return JSON in the shape:

```json
{ "error": { "code": "scanner_not_found", "message": "...", "request_id": "req_abc" } }
```

`code` is a stable enum; `message` is human-readable; `request_id` is the trace id we log in Sentry/Datadog. Don't lean on HTTP status alone — clients need stable codes.

---

## 6. UI / UX page structure

### 6.1 Information architecture

```
/                                Marketing site (signed-out)
/login, /signup                  Auth (Clerk-hosted)
/onboarding                      First-run wizard (org name, region, first scanner)
/app                             Authenticated app shell
  /app/dashboard                 Org-wide QA status grid (one tile per scanner)
  /app/scanners
       /app/scanners/[id]        Scanner detail: trends, action items, sessions list
  /app/sessions
       /app/sessions/new         Upload wizard (pick scanner → upload → confirm slice map)
       /app/sessions/[id]        Session detail: 5 tabs (Overview, Slices, QA Results, Report, Audit)
  /app/reports                   PDF library, search by date/scanner/test
  /app/sites                     Site + scanner admin (admins/physicists)
  /app/users                     Team, roles, invitations (admins)
  /app/billing                   Plan, seats, usage (admins)
  /app/settings                  Org settings, anonymization defaults, webhook config
```

### 6.2 Key flows

The **upload-to-report** flow is what users perform every QA cycle. It must feel like three steps:

1. **`/app/sessions/new`** — pick the scanner from a dropdown that defaults to the last one used, drag-drop the DICOM folder onto a big drop zone, watch a progress ring as files PUT to S3.
2. **Slice-map confirm modal** — auto-mapping is shown; the user clicks "Run QA" or overrides a slice and then clicks Run.
3. **`/app/sessions/{id}`** — automated tests stream their results into the page as workers finish them (server-sent events). The user scores the two visual tests inline. One button: "Approve & generate report."

The **trends** flow lives on `/app/scanners/{id}`. A single page shows: a status header (PASS/FAIL today, days-since-pass, days-to-next-required-scan based on ACR cadence), seven line charts (one per ACR test) with the action limit drawn as a horizontal band, the table of the last twelve sessions, and a "schedule next session" CTA.

The **admin** flow on `/app/dashboard` is a status grid of every scanner across every site, color-coded by current QA status, with a single-click drill-in.

### 6.3 Component system

shadcn/ui as the base. The bespoke components we need:

- **`<DicomDropZone>`** — drag-drop, chunked PUTs to S3, retries, progress per file.
- **`<DicomViewer>`** — slice scroller with window/level. We can wrap [`cornerstone3d`](https://www.cornerstonejs.org/) for proper DICOM rendering rather than ship our own.
- **`<TestResultCard>`** — one per ACR test; value, spec, pass-fail badge, annotated image, "review" / "override" actions.
- **`<TrendChart>`** — recharts-based; an action-limit band is the differentiator vs a generic line chart.
- **`<ScannerStatusTile>`** — dashboard tile with the QA status, traffic light, last session timestamp.

---

## 7. Security and HIPAA-aware architecture

We design for HIPAA from day one even though phantom data is *not* PHI — because customers will eventually point this at de-identified patient series, and because passing security review of a hospital procurement is faster if the answer to "are you HIPAA-aware?" is "yes, here's our BAA path."

### 7.1 What HIPAA actually requires (the part architects need)

The HIPAA Security Rule maps to four categories of technical controls: access control, audit, integrity, and transmission security. Below is how each maps to our build.

| Category | Control | Our implementation |
|---|---|---|
| Access control | Unique user ID, automatic logoff, encryption | Clerk/Auth0 with per-user accounts (no shared logins). Session JWT lifetime 1h, refresh 7d, idle timeout 30 min. AES-256-at-rest on RDS, S3, and EBS. |
| Audit | Recordable mechanisms that record and examine activity | `audit_log` table with append-only triggers. CloudTrail on AWS account. Immutable WORM bucket for log archives. |
| Integrity | PHI must not be improperly altered | All result and report rows are immutable after generation; corrections write a new row referencing the prior `parent_id`. Reports are HMAC-signed; the signature is stored next to the PDF. |
| Transmission security | Encryption when transmitted over open networks | TLS 1.3 everywhere. HSTS preload. Presigned S3 URLs expire in 10 min. |

### 7.2 Compliance posture

We will pursue a **Business Associate Agreement** with AWS (or whichever cloud we land on) before storing anything that could be PHI. We will **not** pursue SOC 2 Type 1 until we have at least one paid customer asking for it — but we will build the controls now so the audit later is cheap.

We will publish a clear **data residency** policy: org `region` is honored at storage layer. EU customers get EU-region buckets and an EU-region replica RDS. Cross-region replication is opt-in.

### 7.3 DICOM anonymization

Before any DICOM hits long-term storage, we run a configurable de-identification pass. The default profile is **DICOM PS3.15 Basic Application Confidentiality Profile** with the "Retain Safe Private" option, which strips patient identifying tags but keeps acquisition parameters (we need TR/TE/etc. for QA). Each tenant can configure:

- Always anonymize (default-on for new orgs in clinical mode).
- Anonymize-on-export (raw stays in storage, public exports are clean).
- Off (phantom-only customers who never upload patient data).

The anonymizer is a worker that operates on the raw upload and writes a cleaned copy. The raw is retained for the org's "raw retention" window (configurable, default 30 days) and then deleted.

### 7.4 Threat model highlights

- **Cross-tenant data leak**: prevented by RLS in Postgres and by tenant-scoped S3 prefixes.
- **Direct S3 object enumeration**: bucket has `BlockPublicAccess = true`, all access via presigned URLs with short TTLs.
- **Stolen JWT replay**: short JWT lifetime, refresh token rotation, IP fingerprint in audit log.
- **SQL injection**: SQLAlchemy + parameterized queries; no raw string SQL in business code.
- **Supply-chain**: `pip-audit` and `npm audit` in CI; Dependabot enabled.
- **Insider threat**: only two engineers have prod data access; access is via SSO + short-lived AWS SSO sessions; every prod query is logged.

---

## 8. Background processing

Celery workers consume jobs from Redis. The job graph for a single QA session is:

```
1. ingest_session(session_id)
     - download DICOMs from S3 to worker tmp
     - parse with pydicom; validate against ProtocolProfile
     - on failure → session.status = 'failed', notify
2. anonymize_series(series_id)         # parallel for each series
3. run_qa_suite(session_id)
     - import app.qa_tests modules (existing code)
     - run all automated tests
     - upload annotated PNGs to S3
     - insert test_results rows
4. flag_for_review(session_id)
     - status -> review
     - fire webhook + email
```

Each job is idempotent (re-runnable safely) and reads its inputs from Postgres + S3 — workers are stateless. We start with two worker pools: `qa-default` (4 vCPU each, 8 GB RAM) and `qa-heavy` (16 GB RAM, used for the future B0/AI tasks). Autoscale on Redis queue depth.

For future AI modules, we add a `qa-gpu` pool on GPU-backed instances; the queue routing is by task name, so no code changes needed elsewhere.

---

## 9. Reporting engine

Reports are generated server-side and stored as PDF in S3. The pipeline:

1. After session approval, a Celery task pulls all `test_results` + their annotated images.
2. It renders an HTML document from a Jinja2 template (`templates/reports/acr_large_v1.html`) — this gives us clean control over layout and version-control of the report design.
3. It converts HTML → PDF with **WeasyPrint** (server-side, no headless browser dependency).
4. The PDF is hashed (SHA-256) and HMAC-signed with the org's signing key; both are stored in `reports`.
5. The user gets a presigned URL.

Trend graphs in the report are embedded as inlined SVG that the same Jinja template builds from `test_results` history (via matplotlib for the static images, since they appear inside the PDF). For interactive dashboards in the web app, the React frontend uses **recharts** off the API.

**Versioning**: every report carries the analysis-engine version and the spec snapshot (`spec_snapshot` jsonb). When we ship new thresholds or a new test, historical reports remain accurate to the spec they were generated against.

---

## 10. Deployment architecture

### 10.1 Environments

`local` (Docker Compose), `preview` (per-PR ephemeral on Render or AWS App Runner), `staging` (mirrors prod, scaled down), `prod` (us-east-1 primary, replication to us-west-2 for DR).

### 10.2 Production topology (AWS, single-region to start)

```
Route53 → CloudFront → ALB
                       ├── ECS Fargate service "web"         (Next.js, 2-N tasks)
                       └── ECS Fargate service "api"         (FastAPI, 2-N tasks)
                                  │
                                  ├── RDS Postgres 16 (Multi-AZ, encrypted)
                                  ├── ElastiCache Redis (cluster mode disabled to start)
                                  └── S3 buckets per region:
                                       - dicom-raw           (lifecycle: archive @ 30d)
                                       - dicom-clean         (long-term retention)
                                       - reports
                                       - audit-archive       (Object Lock: compliance mode)

ECS Fargate service "workers" (Celery, 2-N tasks, scales on queue depth via CloudWatch alarm)
```

A WAF is in front of CloudFront. Secrets are in AWS Secrets Manager; never in env files. Image registry is ECR; deploys are blue/green via CodeDeploy hooks.

### 10.3 CI/CD

GitHub Actions:

```
on PR:    lint, type-check (pyright + tsc), unit tests, integration tests against ephemeral postgres,
           build Docker images, deploy preview
on main:  build + push to ECR, deploy to staging, run smoke tests, manual approval, deploy to prod
on tag:   release notes, signed artifact
```

Database migrations are applied by a one-shot ECS task that runs before the new code rolls out. Alembic is the migration tool (it lives alongside the FastAPI app).

### 10.4 Observability and on-call

Sentry captures every unhandled exception in both Python and TypeScript with full traceback + correlation to `request_id`. PostHog tracks key product events (`session_uploaded`, `qa_completed`, `report_generated`). Grafana Cloud collects metrics and logs from ECS via the OpenTelemetry Collector. Two critical alarms: Postgres free disk < 20% and Celery queue depth > 100 for 10 min. The phone tree is two engineers on rotation via PagerDuty.

---

## 11. Scaling path

Boring is good. The single-region monolithic-API + worker-pool topology will scale to **hundreds of imaging centers and tens of thousands of QA sessions per month** before any of the following migrations are necessary:

- **Read replica** for Postgres when dashboards start dominating load — point the analytics queries at the replica.
- **Per-region sharding** when EU/APAC traffic justifies in-region storage.
- **Service split** along strong boundaries — first to split out is usually the worker fleet (already physically separate, but no longer co-deployed). Next is the reporting service if PDF generation starts dominating worker CPU.
- **Object-storage tiering** — push raw DICOMs to S3 Glacier Instant Retrieval at 90 days, deep archive at 1 year.
- **Search**: when "find me all sessions where Test 5 failed in Q1 across these three scanners" becomes the dominant query, copy `test_results` into OpenSearch via Postgres → Debezium → Kafka → OpenSearch.

We do not adopt Kubernetes until we have more than ~50 services or a dedicated platform engineer.

---

## 12. Future module integration

The plug-in points were chosen so the future modules you listed slot in cleanly.

### 12.1 New phantom or test types

Adding the small ACR head phantom, an MR-Linac daily QA phantom, or a custom institutional phantom is:

1. New folder `app/qa_tests/<phantom>/` with one Python module per test.
2. Register in `TEST_ORDER` registry (already in the MVP).
3. Add `phantom_type` enum value in the `sessions` table.
4. New Jinja template for the report.

Nothing else changes. Workers automatically pick up the new modules; the API is generic; the UI's session-detail page just iterates over `test_results`.

### 12.2 Advanced QA (B0 mapping, geometric distortion)

These need vector outputs (3D distortion maps), not scalar pass/fail. We extend `test_results.measurements_json` to carry a `payload_uri` pointing to a NIfTI or HDF5 in S3 with the dense data, plus a small set of summary scalars (max distortion, mean, etc.) at the top level. The UI grows a 3D-volume viewer (vtk.js / `cornerstone3d`) for these.

### 12.3 AI-based artifact detection

The orchestration is unchanged; the analysis is a Python module that calls a model server. We deploy ONNX models behind **NVIDIA Triton** on GPU instances. The Celery task routes to `qa-gpu` queue. Each inference run records the model version into `spec_snapshot` so reports are reproducible.

### 12.4 MR-Linac QA

The challenge here is daily QA at a much higher cadence than ACR's annual + monthly. We add a `cadence` field on `Scanner` and a small scheduler that emails the QA technologist when a session is overdue. The analysis itself is just more test modules.

### 12.5 Protocol optimization / patient-specific distortion correction

These are different products that share infrastructure (auth, tenancy, DICOM ingest, storage). We add them as new top-level navigation areas under `/app`, each backed by its own Python package. They reuse the auth, billing, audit, and DICOM-handling layers as libraries.

---

## 13. Folder structure (proposed monorepo)

```
mriqa-platform/
├── apps/
│   ├── web/                       # Next.js 14
│   │   ├── app/                   # App router pages
│   │   ├── components/
│   │   ├── lib/                   # API client, auth helpers
│   │   └── package.json
│   ├── api/                       # FastAPI gateway + business logic
│   │   ├── mriqa_api/
│   │   │   ├── main.py
│   │   │   ├── routers/           # one file per resource (sessions, scanners, ...)
│   │   │   ├── auth/              # JWT verify, tenant resolver
│   │   │   ├── db/                # SQLAlchemy models, sessions, RLS helpers
│   │   │   ├── billing/
│   │   │   ├── webhooks/
│   │   │   ├── reporting/         # html templates + PDF render
│   │   │   └── audit/
│   │   ├── alembic/               # migrations
│   │   └── pyproject.toml
│   └── workers/                   # Celery
│       ├── mriqa_workers/
│       │   ├── celery_app.py
│       │   ├── tasks/             # ingest, anonymize, run_qa, render_report
│       │   └── ...
│       └── pyproject.toml
├── packages/
│   ├── qa_engine/                 # existing analysis code, lifted in here
│   │   ├── qa_engine/
│   │   │   ├── io_dicom/          # from MVP
│   │   │   ├── utils/
│   │   │   ├── qa_tests/
│   │   │   └── reporting/
│   │   └── pyproject.toml
│   └── ui-kit/                    # shared React components
├── infra/
│   ├── terraform/                 # cloud
│   │   ├── modules/
│   │   └── envs/{staging,prod}/
│   ├── docker/
│   │   ├── api.Dockerfile
│   │   ├── web.Dockerfile
│   │   └── workers.Dockerfile
│   └── compose/
│       └── docker-compose.yml     # local
├── ops/
│   ├── runbooks/
│   └── dashboards/                # grafana JSON
├── docs/
│   ├── saas_architecture.md       # this file
│   ├── saas_roadmap.md
│   └── runbooks/
├── scripts/
└── README.md
```

The crucial structural point is that `packages/qa_engine` is a regular Python package consumed by both `apps/api` and `apps/workers`. The existing MVP code (`app/qa_tests/`, `app/utils/`, `app/reporting/`) lifts in there verbatim. **Zero re-implementation.**

---

## 14. Open questions for product/legal/finance

These are decisions the founder/CTO (you) need to make, in roughly this order. Each one materially shapes one of the sections above; flag them in the roadmap as gating items.

The first is whether v1 ever touches PHI. If it stays phantom-only, HIPAA becomes a marketing checkbox rather than a contractual obligation, and we don't need a BAA on day one. If clinical data is in scope from launch, we need a HIPAA-eligible cloud, signed BAA, and the de-identification pipeline before the first paid customer.

The second is whether we sell to imaging centers directly or to physicist consultants who service many centers. The pricing model (per-scanner vs per-org vs per-session) and the seat economics fall out of this.

The third is whether the report we generate is considered a regulated medical device under FDA's SaMD framework. The conservative read is: if the report is decision-support for accreditation only, it's outside the scope of SaMD. If a customer ever uses our pass/fail to gate clinical use of the scanner, we are arguably making a device claim and need a 510(k) path. We should ship with explicit product copy ("decision-support, not for diagnostic use") and revisit when a customer asks.

The fourth is the API tier of the product. Selling an API as a developer surface (so a hospital's automation team can push their nightly QA series in) is a different motion from selling a SaaS UI. We can ship both; we should sequence the UI first.

---

## 15. Summary

The architecture is intentionally boring at v1: a single FastAPI service plus Celery workers, one Postgres with row-level security for multi-tenancy, S3 for binaries, Stripe for billing, Clerk for auth, Next.js for the UI. Every choice has an explicit "instead of" so we can defend it later. The existing analysis engine lifts in unchanged. The path to advanced QA, AI, and global scale is paved but not paved over — we don't ship the future today, we ship the foundation that supports it.

The companion document, [`saas_roadmap.md`](./saas_roadmap.md), sequences the work into shippable phases and lays out the business model.
