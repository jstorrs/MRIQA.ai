# MRIQA.ai — Roadmap, Business Model, and Phased Build

**Companion to:** [`saas_architecture.md`](./saas_architecture.md)
**Audience:** founder, product lead, first 2–4 engineers

This document answers two questions: *in what order do we build the SaaS platform?* and *what is the commercial model the build is in service of?* It is opinionated. Every estimate assumes a small team — two engineers full-time, one designer half-time, the founder running product and customer development. With more people, phases shorten roughly linearly; with less, they stretch.

---

## 1. Reading guide

Each phase has three parts.

A **goal**, in one sentence, describing what success looks like at the end of the phase. A **scope** section, listing exactly what we build and explicitly what we don't. A **gating decisions** section, listing the calls the founder has to make before the phase starts. Effort estimates are wall-clock weeks for a two-engineer team after Phase 0 setup is complete.

You should not commit to Phase N+1 until Phase N is in production with a paying customer (or at least a signed pilot). The most common failure mode of a healthtech build is sprinting six phases ahead of the customer who is actually paying. The roadmap below is sequenced to prevent that.

---

## 2. Phase 0 — Foundation (2–3 weeks)

**Goal:** the monorepo, CI/CD, local dev environment, and "hello world" production deploy work end-to-end, with no product features yet.

We set up the empty shells of the architecture documented in `saas_architecture.md`. The deliverable is unsexy but high-leverage: every future phase moves faster because none of these stones get tripped on later.

**Scope.** Monorepo skeleton (`apps/web`, `apps/api`, `apps/workers`, `packages/qa_engine`). FastAPI + Next.js + Celery boilerplate. Docker Compose for local dev. Terraform that provisions a staging environment on AWS (VPC, RDS, S3, ECR, ECS, ElastiCache, Route53, ACM). GitHub Actions for lint/test/build/deploy. A single `/api/v1/health` endpoint that returns `{status: "ok", version: <git_sha>}`. Sentry + PostHog + Grafana Cloud wired up. Migration framework (Alembic) and one `0001_init.sql` migration with the `organizations` table.

**Explicitly out of scope.** Auth, billing, any QA logic. The MVP's analysis code stays in its current Streamlit form for now.

**Gating decisions.** Which cloud (recommendation: AWS, for the BAA path). Which auth provider (recommendation: Clerk for speed, swap later if needed). Whether we register the production domain now (recommendation: yes, even if marketing site lives on a placeholder).

---

## 3. Phase 1 — Productization (6–8 weeks)

**Goal:** an imaging center can sign up, add their scanner, upload an ACR phantom DICOM series, see all seven QA results with annotated images, approve the session, and download a PDF — all from a web UI hosted at a real URL with real auth and real multi-tenancy.

This is the smallest thing we can sell, and it's also the bulk of the work. Phase 1 must end with at least one external pilot customer using the product on real data; that's the gate to Phase 2.

**Scope.** Auth (Clerk-hosted login + signup + invitations). Org/Site/Scanner CRUD in the API and a clean UI for it. Multi-tenant Postgres schema with RLS turned on for every tenant table. Direct-to-S3 DICOM upload with presigned PUTs. Celery worker pool running the existing QA engine (lifted into `packages/qa_engine`). Server-sent events from API to web so test results stream in as workers complete them. Session detail page (the five-tab layout from the architecture doc). PDF report generation via WeasyPrint + Jinja templates. Audit log on every write. Anonymization toggle on the org (default off — we're phantom-only for v1).

**Explicitly out of scope.** Billing (we comp the first pilots). Trends / longitudinal dashboards. Custom protocol profiles. AI modules. Webhooks. The marketing site (use a single-page Framer or Webflow page).

**Gating decisions before this phase ends.** Pricing model and tier definitions (see Section 8 below). Which customer goes first — ideally one that is already manually doing ACR QA monthly and feels the pain.

**Definition of done.** The pilot can complete the whole upload-to-PDF flow without any engineering assistance, and the resulting PDF is one they're willing to submit to ACR or use internally.

---

## 4. Phase 2 — Trends + reviewable workflow (4–6 weeks)

**Goal:** a physicist comes back every month and gets real value from the historical view, not just the latest run.

Customer behavior at this phase is the moat. If they look at trend lines weekly to spot drift, churn risk drops dramatically.

**Scope.** Scanner detail page (`/app/scanners/{id}`) with seven trend charts, each overlaid with the ACR action limit band. Org-wide status dashboard (`/app/dashboard`) — one tile per scanner, traffic-light status, days-since-last-pass. Review state: sessions can be in `pending → processing → review → approved` with comments and a per-test "override" affordance for the physicist. Email digests (weekly per-scanner summary, immediate failure notification). Outbound webhooks for `qa.session.completed`, `qa.failure_detected` (so customers can wire Slack/Teams alerts themselves).

**Out of scope.** Marketing site. Self-serve billing (still manual invoicing). Custom report templates.

**Gating decisions.** Whether to invest in a self-serve marketing site here or in Phase 3.

---

## 5. Phase 3 — Commercialize (4–5 weeks)

**Goal:** anyone can find the product, sign up, pay with a credit card, and use the product without ever talking to us.

This is where the SaaS becomes a product the founder isn't personally selling every seat of.

**Scope.** Stripe integration: customer object, subscription, customer portal for invoices and plan changes. Pricing page on the marketing site. Free-trial behavior (14 days, no card required). In-app billing page with usage counters. Plan-gated features (e.g. trend retention duration). Onboarding wizard for first scanner. Documentation site (Mintlify or Nextra). Live chat (Intercom or Plain). DPA template ready to send. SOC 2 readiness review (controls inventory, gap analysis — but no audit yet).

**Out of scope.** Per-org SSO (push to Enterprise tier later). Multi-region storage residency (US-only for v1).

**Gating decisions.** Final tier names + prices (best decided after 3–6 pilots are paying). Whether to publish prices publicly (recommendation: yes; opaque pricing slows the bottom of the funnel).

---

## 6. Phase 4 — Compliance and enterprise (6–10 weeks)

**Goal:** a 200-bed hospital can buy us through their procurement process.

This is the unlock for the larger contracts. It is mostly paperwork and pre-existing controls; very little code.

**Scope.** Signed BAA with AWS (and any sub-processors). SOC 2 Type 1 audit kickoff (Vanta, Drata, or Secureframe). HIPAA risk assessment and policies documented. SSO via SAML for enterprise customers (using Clerk's enterprise tier or WorkOS). Audit log export. Retention controls per-org. Encryption-at-rest verification in the report we hand to security reviewers. Data-residency option (EU customers in eu-central-1).

**Out of scope.** SOC 2 Type 2 (begins automatically after Type 1; the audit is 6–12 months out by definition).

**Gating decisions.** Whether to start FDA / SaMD assessment (recommendation: yes, but pre-submission only; do not begin a 510(k) until customers actually require it).

---

## 7. Phase 5+ — Advanced QA modules

After Phase 4, the platform is a real SaaS. From here, growth is feature-driven rather than infrastructure-driven. Roughly the right sequencing, based on how much they reuse what's already built:

The first additional module to ship is the **ACR small phantom (head coil)** workflow. The phantom is different but the architecture is identical — new `phantom_type` enum value, new test modules, new report template. Two weeks of work, immediate revenue from neuro practices.

Next is **per-customer protocol profiles** so a site can save its expected TR/TE/FOV/matrix per scanner and the system flags acquisitions that deviate. Mostly a config UI plus a validation pass in the worker. Three weeks.

Then **B0 mapping / geometric distortion**. This is the first module that produces a 3D result rather than a scalar; the report grows a 3D viewer. Six weeks.

Then **AI-based artifact detection**. Train (or license) a model that classifies known artifact patterns (motion, ghosting, RF spike, gradient malfunction). Build a labelling pipeline so customers can submit corrections that improve the model over time. The model lives behind a Triton inference service; the QA worker calls it. Tight, customer-feedback-loop product. Eight to twelve weeks for v1.

Then **MR-Linac daily QA**. Higher cadence, simpler analytics per session but more sessions. Add a scheduler so sessions due/overdue show in the dashboard. Four to six weeks.

Then **protocol optimization recommendations** — a different product on shared infra. This is where the platform thesis pays off: a customer who pays for ACR QA and B0 mapping is the same customer who pays for protocol optimization, on the same scanners, with the same auth and audit trail.

The exact ordering should be set by which two pilot customers asked for which feature, in writing, with a signed pre-order.

---

## 8. Business model

### 8.1 Pricing tiers (proposed)

The unit of value is the **scanner**. Per-user pricing is a trap in this market because hospitals have many low-engagement users (technologists) and one or two high-engagement users (physicists, QA admin). Scanner-based pricing aligns with how customers think about the cost of accreditation and how they budget.

| Tier | Audience | Price (USD/month, per scanner) | Limits | Notable features |
|---|---|---|---|---|
| **Starter** | 1–3 scanner imaging centers | $149 | 12 sessions/scanner/month, 1-year history | Core ACR QA, PDF reports, email alerts |
| **Pro** | Multi-site imaging groups | $299 | Unlimited sessions, 5-year history | Trends, webhooks, custom report header, weekly digests, API access |
| **Enterprise** | Hospitals, large systems | Custom (typical floor $20k/year) | Unlimited | SSO, BAA, SOC 2 reports, dedicated support, on-prem option (year 2) |

Free trial is 14 days, full Pro features, no credit card. Pilots are comped (free) for the first 90 days, and then convert.

### 8.2 Customer onboarding

The first-run flow is deliberately short. Sign up → create org (name, region) → add first scanner (vendor, model, field strength) → invite teammates (optional) → upload first session. We block the experience there: no dashboard, no settings exploration — get the first session in.

Once the first session completes, we surface (a) a 60-second product tour of the trend chart and the report, (b) a "schedule next session" CTA, (c) a *very* gentle Intercom prompt asking how it went. We measure activation as "first session completed within 72 hours of signup."

### 8.3 Roles and seat economics

Roles in v1 are **admin**, **physicist**, **technologist**, **viewer**. Admin can change billing and invite. Physicist can configure scanners and approve sessions. Technologist can upload and run QA but cannot approve. Viewer is read-only (for hospital QA committees).

All seats included in tier price. There is no per-seat upcharge — we don't want the customer's procurement team to be the gate on adding a technologist. Pricing growth comes from adding scanners or upgrading to higher tiers, both of which align with the customer's growth, not with our seat manipulation.

### 8.4 Usage tracking and limits

Sessions, storage, and API calls are metered into `usage` rows in the database. Soft limits (warn at 80%, block at 100%) on Starter; soft warn only on Pro/Enterprise with an overage line item that converts to a tier upgrade conversation.

### 8.5 Licensing posture

Closed-source commercial. The core analysis engine (today's `app/qa_tests/`) is not open-source; the value of the algorithm transparency is met instead by **publishing the spec snapshot** in every report, so customers can audit the math even though they can't fork it.

---

## 9. Compliance and regulatory roadmap

The strategic objective is to be HIPAA-defensible, SOC 2 Type 1 audited within 12 months, and to have a written FDA SaMD positioning that we can update as customer use-cases evolve.

We **do not** pursue 510(k) clearance until a customer's intended use crosses into clinical decision support, because the cost (Class II 510(k) is typically $200k–$500k all-in, 9–18 months) doesn't pay back without that customer. We do, however, write down the analysis engine's "intended use" statement and the limits of it (decision support for accreditation, not a clinical diagnostic) in every report and on every page of the marketing site. That positioning is what keeps us outside SaMD for now.

The compliance milestones, sequenced:

Month 1–3 (during Phase 1): HIPAA gap assessment, written policies (access control, incident response, change management), all engineers complete HIPAA training.

Month 3–6 (during Phase 2/3): BAA signed with AWS. Encryption-at-rest verified on every datastore. Audit log immutability test. Penetration test (a small one, $5–15k, scoped to the app surface).

Month 6–12 (during Phase 3/4): SOC 2 Type 1 audit. Customer-facing trust portal (compliance, status, sub-processor list). DPA template available for EU customers.

Month 12–24: SOC 2 Type 2 audit. ISO 27001 if customer demand justifies. FDA pre-submission meeting if any pilot drifts into clinical decision support.

---

## 10. Risks and how we de-risk them

The biggest risk is not technical — it is **sales-cycle length in healthcare**. A 200-bed hospital procurement cycle is 6–18 months. Mitigation: sell to small imaging centers first (1–3 scanner shops, no procurement department) where the cycle is days, not months. Build credibility, then enter hospitals through physicist-consultant referrals.

The next risk is **algorithm trust**. Customers will not trust pass/fail numbers they don't understand. Mitigation: every test page shows the math (the formula, the spec, the ROI overlay). Every report carries the spec snapshot. There is no "trust me, it's an AI."

The third risk is **DICOM diversity**. Siemens, GE, Philips, and Canon all emit slightly different metadata. The MVP works on Siemens because that's the only data we have. Mitigation: pilot the first three customers across three vendors before declaring Phase 1 done.

The fourth risk is **the founder's bandwidth**. You cannot be the only engineer who understands the analysis math, the customer who signs the contract, the cloud architect, and the support person. Mitigation: hire engineer #2 before Phase 2 ends, with the engineer's first month spent owning the worker fleet end-to-end.

---

## 11. North-star metrics

Pick three, watch them weekly, ignore the rest. The right three for the first 18 months are:

**Activation rate** — fraction of new orgs that complete their first session within 72 hours. Target: 60%.

**Retention** — fraction of orgs that still run a session in month 3 after signup. Target: 80%.

**Scanner expansion** — average scanners per org at month 6. Target: 1.6 (most orgs start with one but expand once they trust the platform).

Revenue follows these three. If activation is 30% the funnel is broken. If retention is 50% the product isn't sticky. If scanner expansion is 1.0, customers don't see the platform as the obvious place to put their next scanner.

---

## 12. Total estimated effort to Phase 4 production

With two engineers full-time, starting from the current Streamlit MVP:

- Phase 0 (foundation): 2–3 weeks
- Phase 1 (productization): 6–8 weeks
- Phase 2 (trends + review): 4–6 weeks
- Phase 3 (commercialize): 4–5 weeks
- Phase 4 (compliance + enterprise): 6–10 weeks (much of which runs in parallel with paying customer onboarding)

**Total to a defensible, commercially-viable v1: roughly 22–32 weeks (5.5–8 months).**

This estimate assumes no major rebuilds, no team turnover, and at least one engaged design partner from week one whose feedback we incorporate as we go. The Phase 5+ modules are not in this estimate; they are revenue-funded expansions, not foundational work.

---

## 13. What to do next

Three concrete suggestions for what the next session of work should produce, in priority order.

The strongest move is to **scaffold the Phase 0 monorepo** — empty `apps/api`, `apps/web`, `apps/workers`, `packages/qa_engine`, plus Docker Compose for local dev. This is two to three days of focused work and unblocks everything. The MVP code lifts cleanly into `packages/qa_engine` and the existing Streamlit app keeps running.

A weaker but faster move is to **harden the current Streamlit MVP** to be usable by one or two pilot customers as-is, while the SaaS architecture is being built. The risk is investing in the Streamlit version distracts from the real platform; the upside is real customer feedback during Phase 0/1.

The third option is to **commission the UI design first** — wireframes for the five core pages (dashboard, scanner detail, session detail, sessions list, billing). This is the right call if a designer is available; it lets engineers build against a real visual target instead of inventing layouts as they go.

The right answer depends on team composition and whether there's a pilot customer waiting. The companion architecture document describes the technical end-state; this roadmap describes the path; the next session of work should pick one entry point and start.
