# MRIQA.ai — ACR Large Phantom QA (MVP)

A pilot-ready Streamlit web app that ingests an MRI DICOM series of the **ACR Large or Medium MRI Phantom** and runs the seven QA tests defined in the ACR MRI Quality Control Manual and the *ACR Large and Medium Phantom Test Guidance (Oct 2022)*. Five tests are fully automated; two visual scoring tests open inside the app with zoomed views.

**Status:** MVP. **Audience:** medical physicists, QA technologists, imaging-center pilots.
**Not a medical device. Not for diagnostic use.**

---

## What you get

- Drag-and-drop DICOM upload (zip or individual `.dcm` files)
- Auto-mapping of ACR slice roles (1, 5, 7, 11) with manual override
- Five automated tests: **Geometric Accuracy · Slice Thickness · Slice Position · Image Intensity Uniformity (PIU) · Percent Signal Ghosting (PSG)**
- Two visual scoring tests: **High-Contrast Spatial Resolution · Low-Contrast Object Detectability**
- Polished results page with overall verdict, status badges, annotated images per test
- In-browser-session history of completed runs
- Professional PDF report with cover page, verdict block, per-test pages, footer with tamper-evident signature
- CSV export of every measurement
- ACR thresholds taken from the 2022 *Large and Medium Phantom Test Guidance*; auto-adjusted for field strength and phantom model

---

## Validate it on your own data

This MVP is meant to be tested dataset by dataset against manual measurements before any pilot trusts it. The app ships with a **Validation** tab — testing checklist + manual-measurement input + per-test confidence chips + warning list + a per-session CSV log.

The full validation protocol is in [`TESTING.md`](./TESTING.md): how to choose datasets, how to inspect every overlay, how to read the confidence chips, what to record, and what to send back as evidence. **Do not deploy publicly until at least three datasets across two scanners have been validated end-to-end.**

---

## Run it three ways

### 1. Easiest — double-click on a Mac (local)

After cloning/copying the project to your computer, double-click **`Launch MRIQA.command`** in Finder. The first launch installs Python packages (~30 s); subsequent launches are instant. Streamlit runs in the background; close the Terminal window safely, the app keeps running. Use **`Stop MRIQA.command`** to stop it.

If macOS blocks the launcher the first time ("from an unidentified developer"), double-click **`First-time-setup.command`** once to strip the quarantine flag, or right-click the launcher → Open → Open. Detailed walkthrough in [`HOW_TO_RUN.md`](./HOW_TO_RUN.md).

### 2. Manual — for developers

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Then open the URL Streamlit prints (usually `http://localhost:8501`).

### 3. Cloud — share a public URL with your pilot

The app is designed to deploy on Streamlit Community Cloud (free) in about 20 minutes. End state is a URL like `https://mriqa-pilot.streamlit.app` your pilot can click. Step-by-step (no Terminal needed) in [`DEPLOY.md`](./DEPLOY.md).

---

## Project layout

```
MRIQA.ai/
├── streamlit_app.py            # Streamlit entry point (lives at project root)
├── app/                        # Python package
│   ├── io_dicom/dicom_loader.py
│   ├── qa_tests/               # one module per ACR test
│   │   ├── base.py             # TestSpec + shared TestResult helpers
│   │   ├── geometric_accuracy.py
│   │   ├── slice_thickness.py
│   │   ├── slice_position.py
│   │   ├── uniformity.py
│   │   ├── ghosting.py
│   │   ├── high_contrast_resolution.py
│   │   ├── low_contrast_detectability.py
│   │   └── localizer_geometry.py   # sagittal S-I length
│   ├── reporting/
│   │   ├── pdf_report.py       # ReportLab-based, with cover page + footer
│   │   └── csv_report.py
│   ├── ui/                     # Streamlit-facing modules (the only place Streamlit is imported)
│   │   ├── landing.py
│   │   ├── uploads.py
│   │   ├── slice_mapping.py
│   │   ├── analysis_inputs.py
│   │   ├── sagittal_analysis.py
│   │   ├── results_view.py
│   │   ├── manual_scoring.py
│   │   ├── viewer.py
│   │   ├── history.py
│   │   ├── export.py
│   │   ├── validation.py
│   │   ├── badges.py
│   │   ├── banner.py
│   │   └── auth.py
│   └── utils/                  # phantom localization, ROI helpers, geometry, theme, viz
│       ├── phantom.py
│       ├── phantom_spec.py
│       ├── geometry.py
│       ├── theme.py
│       └── viz.py
├── docs/
│   ├── feasibility.md          # per-test feasibility analysis
│   ├── saas_architecture.md    # technical blueprint for cloud SaaS evolution
│   └── saas_roadmap.md         # phased build plan + business model
├── exports/                    # generated PDFs/CSVs land here (git-ignored)
├── .streamlit/config.toml      # theme + server config
├── requirements.txt
├── Launch MRIQA.command        # macOS launcher (double-click)
├── Stop MRIQA.command          # macOS stop script
├── First-time-setup.command    # one-time macOS quarantine fix
├── HOW_TO_RUN.md
├── DEPLOY.md                   # cloud deployment walkthrough
└── README.md                   # this file
```

The analysis code under `app/qa_tests/`, `app/io_dicom/`, `app/reporting/`, and `app/utils/` has zero dependency on Streamlit — Streamlit only appears inside `app/ui/` and `streamlit_app.py`. When the project evolves into the full SaaS (architecture in `docs/saas_architecture.md`), the analysis modules lift unchanged into the production backend.

---

## What ACR tests are automated, and at what thresholds

All thresholds come from the **ACR Large and Medium Phantom Test Guidance (Oct 2022)**. They live in a single `PhantomSpec` dataclass per phantom in `app/utils/phantom_spec.py`, so they're easy to audit, override, and add new phantoms to.

Defaults below are for the **Large** phantom; **Medium** thresholds are tighter where the doc specifies (e.g. ±2 mm geometric tolerance, PIU ≥ 85 % at 3 T).

The app runs one of two analyses depending on the series picked: the
**axial series analysis** (11-slice ACR protocol, the seven tests below) or
the **sagittal localizer analysis** (single sagittal image, S-I length only).

**Axial series analysis**

| # | Test                              | Automation        | Slice    | Large-phantom threshold                                       |
|---|-----------------------------------|-------------------|----------|---------------------------------------------------------------|
| 1 | Geometric Accuracy (axial)        | Automated         | 1, 5     | 190 mm ± 3 mm diameters                                       |
| 2 | High-Contrast Spatial Resolution  | User confirmation | 1        | 1.0 mm row resolvable in UL and LR (configurable)             |
| 3 | Slice Thickness Accuracy          | Automated         | 1        | 5.0 mm ± 0.7 mm                                               |
| 4 | Slice Position Accuracy           | Automated         | 1, 11    | \|bar offset\| ≤ 5 mm                                         |
| 5 | Image Intensity Uniformity (PIU)  | Automated         | 7        | ≥ 87.5 % at < 3 T; ≥ 82 % at 3 T                              |
| 6 | Percent Signal Ghosting (PSG)     | Automated         | 7        | ≤ 3.0 %                                                       |
| 7 | Low-Contrast Object Detectability | User confirmation | 8–11     | ≥ 37 total spokes at 3 T; ≥ 30 at 1.5 T (ACR-T1)              |

**Sagittal localizer analysis**

| # | Test                                          | Automation | Image       | Large-phantom threshold |
|---|-----------------------------------------------|------------|-------------|-------------------------|
| 1 | Geometric Accuracy — Sagittal (S-I length)    | Automated  | single scout| 148 mm ± 3 mm           |

---

## Upload guidance

The web-deployed instance is meant for **ACR phantom DICOMs only**. Even though uploads are processed in memory (nothing is persisted between sessions on the free Streamlit Cloud tier), please **de-identify your data before uploading**:

- Strip patient name, MRN, accession number, birth date, study description.
- Keep acquisition parameters (TR, TE, FOV, matrix, slice thickness, pixel spacing) — the QA tests need them.
- Many vendors offer one-click anonymization at the scanner console; alternatively use DICOM tools like `dcmodify`, `gdcmanon`, or the [DCMTK toolkit](https://dicom.offis.de/dcmtk.php.en).

Do not upload patient (PHI) DICOMs to a publicly hosted MVP instance.

---

## Limitations and known caveats

The MVP was scoped and validated against a Siemens Skyra 3 T axial ACR Large Phantom acquisition. Real-world validation across Siemens, GE, Philips, and Canon is the next milestone. Expect to tune the slice-thickness and slice-position ROI heuristics on the first run against a new vendor; the annotated images make it obvious where the detector landed.

The two visual scoring tests (high-contrast resolution and low-contrast detectability) are explicitly defined as visual tasks in the ACR manual, so the MVP keeps them manual with zoomed crops. Future versions can add ML-based scoring once we have a labelled corpus.

Session history is per-browser-tab only. Closing the tab loses it. The Export tab is the way to save permanent records.

The Streamlit Cloud free tier is not HIPAA-eligible. For real clinical data, the architecture in [`docs/saas_architecture.md`](./docs/saas_architecture.md) lays out a HIPAA-aware deployment path.

---

## Roadmap

The full SaaS architecture and a phased build plan live in [`docs/saas_architecture.md`](./docs/saas_architecture.md) and [`docs/saas_roadmap.md`](./docs/saas_roadmap.md). For now, the priority is pilot validation on this Streamlit MVP: ship the cloud version, get two or three imaging centers using it on real phantom data, fix what they tell us is broken, then start building the production platform.

---

## License

Closed-source MVP. The ACR analysis math is published in the QC manual and is openly auditable in the code; the implementation, UI, and reporting layer are proprietary.

---

## Questions and feedback

Open an issue on the repository, or contact the maintainer.
