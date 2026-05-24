# MRIQA.ai — Feasibility & MVP Design

**Document version:** 0.1 (MVP scaffold)
**Author:** generated for Ali, 2026-05-18
**Phantom:** ACR Large MRI Phantom
**Reference:** ACR Magnetic Resonance Quality Control Manual, 2015 edition

---

## 1. Goal and scope

Build a desktop / lightweight-web MVP that ingests a DICOM series of the ACR Large Phantom and runs the seven QA tests defined in the ACR MR QC Manual. The MVP is a **feasibility prototype** for a future cloud-hosted multi-site QA tracker.

Out of scope for the MVP: user accounts, persistent storage, encrypted at-rest data, multi-site dashboards, longitudinal trend plotting.

---

## 2. Technical feasibility (per test)

| # | Test | Slice(s) | Algorithm | Automation in MVP | Reliability |
|---|---|---|---|---|---|
| 1 | Geometric Accuracy | 1, 5 | Half-max chord through centroid in 4 orientations on slice 5 + S-I on slice 1 | Automated | High |
| 2 | High-Contrast Spatial Resolution | 1 | Visual scoring of UL/LR hole arrays (1.1 / 1.0 / 0.9 mm) | **User-confirmation** | Reliable automated scoring needs ML or strong heuristics; not appropriate for MVP |
| 3 | Slice Thickness Accuracy | 1 | FWHM of two ramp bars, `0.2 * top * bot / (top + bot)` | Automated | Medium — depends on robust ramp localization; UI shows annotated ROIs so it is easy to sanity-check |
| 4 | Slice Position Accuracy | 1, 11 | FWHM of vertical wedge pair, report `right − left` per ACR sign convention | Automated | Medium — wedge localization is heuristic but visible |
| 5 | Image Intensity Uniformity (PIU) | 7 | Large ROI (200 cm²) + small ROI mean min/max, ACR formula | Automated | High — well-defined ACR algorithm |
| 6 | Percent Signal Ghosting (PSG) | 7 | Large interior ROI + 4 air ROIs (top/bot/left/right), ACR formula | Automated | High |
| 7 | Low-Contrast Object Detectability | 8-11 | Count complete spokes per slice | **User-confirmation** | Visual scoring; automatable later with ML |

### Why two tests stay manual

The ACR procedures for high-contrast resolution (Test 2) and low-contrast detectability (Test 7) are explicitly defined as *visual* tests in the manual — the technologist decides whether a row of holes is "fully resolvable" or whether a spoke is "complete." Automating these reliably needs either a calibrated edge-spread model or a small CNN; either is bigger than the MVP brief. They are scaffolded in the codebase as `user-confirmation` modules so the report still includes the result.

### Tests likely to need tuning after first real run

* **Slice thickness** and **slice position** rely on detecting small bright bars inside the phantom. The default heuristics work on the Siemens Skyra T1 axial series used to scope this design, but bar localization may drift on scanners with very different signal-to-noise or contrast. Both tests show the detected ROIs in the annotated image so the user can spot a bad fit.
* **PIU / PSG** are robust as long as the phantom is well-centered and roughly the right radius is detected; the localizer is Otsu + largest connected component + fill-holes, which is the same recipe used by most published ACR analysers.

---

## 3. Tech stack

| Layer | Choice | Reason |
|---|---|---|
| UI | **Streamlit 1.32+** | Web-app feel with near-zero boilerplate; instant viewer, sliders, file uploads, tabs. Easy to demo. |
| DICOM I/O | **pydicom 2.4+** | Standard. Reads vendor-flavored tags including Siemens private. |
| Numerics | **numpy / scipy / scikit-image** | All standard, no heavy deps. |
| Plotting | **matplotlib + Pillow** | Annotated overlays are rendered to PIL images; reused by Streamlit and the PDF. |
| Reporting | **reportlab 4** | Pure-Python PDF, no LibreOffice headless dependency. CSV via stdlib. |
| Packaging | venv + `requirements.txt` | Sufficient for MVP; Docker is one step away when we move to cloud. |

### Why not Flask + React for the MVP

A FastAPI + React stack is the right destination if we go cloud, but it triples the MVP build time (separate backend, frontend bundler, CORS, auth scaffold) without changing what the user gets to evaluate. The QA *algorithms* live in `app/qa_tests/`, which is fully decoupled from Streamlit — when we move to cloud we keep those modules verbatim and replace `app/app.py` with FastAPI routes and a React frontend.

---

## 4. Architecture (current MVP)

```
app/io_dicom/dicom_loader.py        # parse, sort, ACR-slice-role map
app/utils/phantom.py                # phantom localization (shared)
app/utils/geometry.py               # ROIs, FWHM, line profile, edge finding
app/utils/viz.py                    # annotated PIL images
app/qa_tests/<each test>.py         # one file per ACR test, exposes run(series)
app/qa_tests/__init__.py            # TEST_ORDER list = single source of truth
app/reporting/{pdf,csv}_report.py   # never touches qa logic — works only off TestResult
app/app.py                          # Streamlit UI: upload, viewer, mapper, run, results, export
```

Every test returns a `TestResult` (`base.py`), which has measurements, annotated images, and a status. The reporting layer iterates `TEST_ORDER` and never imports any QA module directly — adding an eighth test is a one-line change.

### Data flow

1. User uploads DICOMs (zip or files) or points to a folder.
2. `load_series()` returns a `DicomSeries` with a stacked pixel array, sorted slices, metadata, and an auto ACR slice map.
3. User confirms / overrides the ACR slice map.
4. User runs QA → each test gets the `DicomSeries` and returns a `TestResult`.
5. UI shows the results; export writes PDF + CSV into `exports/`.

---

## 5. Verification plan

We have not yet executed the app against the uploaded Siemens Skyra series (no DICOM dependency inside the sandbox). Verification on your Mac:

1. `cd /Users/alifatemi/Documents/Claude/Projects/MRIQA.ai && python3 -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `streamlit run app/app.py`
4. Upload `ACR test images/T1` (or zip it) and click *Run all automated tests*.
5. Confirm:
   - **Geometric Accuracy:** slice 5 horizontal & vertical diameters near 190 mm; slice 1 short-axis ~148 mm.
   - **PIU:** target ≥82%; fails below 80% for a 3 T Large phantom.
   - **PSG:** ≤ 3%.
   - **Slice thickness:** preferred 5 mm ± 0.7 mm; fails outside ±1.0 mm.
   - **Slice position:** preferred |Δ| ≤ 5 mm; fails above 7 mm on slices 1 and 11.

If any test produces an obviously wrong number, the annotated image in the *Results* tab will show *where* the detector ran. Two failure modes to expect on first run:

* **Slice thickness:** ramp-bar detection picks up the wrong feature. Fix is in `app/qa_tests/slice_thickness.py::_detect_ramp_bars` — tighten the search window.
* **Slice position:** wedge pair localization. Same fix path in `app/qa_tests/slice_position.py::_measure_wedge_pair`.

Once we have the first real-data run, we lock down the thresholds and add unit tests with golden DICOM fixtures.

---

## 6. Roadmap to a cloud product

Order of work post-MVP, with rough effort estimates:

| Step | Work | Effort |
|---|---|---|
| 6.1 | Replace Streamlit with FastAPI + React/Next.js, keep `app/qa_tests/` and `app/reporting/` verbatim | 2-3 weeks |
| 6.2 | Auth — Auth0 or Clerk; per-user/per-site roles | 1 week |
| 6.3 | DICOM upload to S3-compatible object store (Cloudflare R2 is cheap), Postgres for metadata + results | 2 weeks |
| 6.4 | Multi-site dashboard: per-scanner trend plots, longitudinal QA tracking, action-limit alerts | 2-3 weeks |
| 6.5 | Audit log + signed PDF reports (good if anyone wants to use this for accreditation evidence) | 1 week |
| 6.6 | Optional ML scoring for Tests 2 & 7 — supervised CNN trained on a few hundred labelled phantom slices | 4-6 weeks |
| 6.7 | DICOM C-STORE listener so scanners can push images directly | 2 weeks |

### Compliance considerations once we leave the laptop

* HIPAA: phantom data isn't PHI, but the field this app lives in usually means it gets pointed at de-identified patient series eventually. Bake in encryption at rest (AES-256 via the object store) and at transit (TLS 1.3) from day one.
* MDR / FDA: this MVP is a **QA decision-support tool**, not a diagnostic. If a customer ever uses results to gate a clinical workflow we have to decide whether to register as a medical device.
* Audit trail: every PDF should be signed with a per-site key; we can keep the signature minimal (HMAC over the result JSON) until we need full PKI.

---

## 7. Known limitations of v0.1

1. We did not have read access to the 2015 QC Manual PDF inside the build sandbox; thresholds and slice-role mappings come from the published ACR procedure. They are encoded as **module-level constants near the top of each test file** so reviewing them against the manual is one search away.
2. Phantom localization uses a global Otsu threshold; very noisy or low-SNR acquisitions may need a different segmenter (e.g. a Gaussian-mixture or a fixed-radius prior).
3. PSG air ROIs are placed at fixed offsets outside the phantom radius; for very large fields of view this is fine, for tight FOVs the ROIs may clip — the test errors out cleanly in that case.
4. There is no longitudinal storage in the MVP — every run is a one-shot report.

---

## 8. What "done" looks like for the MVP

* The user can load the Siemens Skyra T1 series, run all five automated tests, score the two user-confirmation tests, and export a PDF / CSV that lists every measurement, its spec, and its pass/fail.
* Architecture is modular enough that adding a sixth automated test would be a single new file in `app/qa_tests/` plus one line in `app/qa_tests/__init__.py`.
* The road from this MVP to a cloud product is paved: no analysis code has to be rewritten.
