# MRIQA.ai — MVP testing & validation protocol

**Audience:** medical physicist or QA technologist running the pilot.
**Goal:** prove (or disprove) that the app produces correct, reliable ACR-phantom QA numbers across multiple datasets — *before* you sign anyone up to depend on it.

This is not a feature checklist. It is a validation protocol. Treat each dataset as a single experiment with a known answer (your manual measurement), and record whether the app got it right.

---

## What you need before you start

A computer that can run the app locally (double-click `Launch MRIQA.command`) OR the deployed Streamlit Cloud URL.

A minimum of three anonymized ACR Large Phantom DICOM datasets. Ideal mix:

- Three from the same scanner taken on different days
- One or two from a different scanner / vendor (Siemens vs GE vs Philips vs Canon)
- At least one with a known issue if you can find it (a real failure event from your archive)

**De-identify every dataset before uploading**, even to the local app. Strip patient name, MRN, accession, birth date. Keep acquisition parameters (TR/TE/FOV/matrix/slice thickness/pixel spacing) — the analysis needs them.

For each dataset, have your own manual QA results ready for tests applicable to that selected series. ACR T1 includes five automated tests; ACR T2 excludes T1-only axial geometric accuracy and PSG. This is the ground truth the app gets compared against.

---

## Step-by-step, per dataset

### 1. Upload and confirm metadata

Open the app. In the sidebar, drop a zipped phantom series (or individual `.dcm` files).

Confirm that the metadata strip at the top of the page shows the scanner, field strength, pixel spacing, and slice count you expect.

If the **Series warnings** box appears, read every warning. Examples and what they mean:

- *"Series has N slices but the ACR Large Phantom protocol uses 11"* — the upload is incomplete or you sent the wrong series.
- *"PixelSpacing is missing or invalid"* — the DICOM header is stripped; physical measurements will be wrong.
- *"Could not identify sequence"* — the SeriesDescription doesn't look like T1 or T2. Note this, but it's not necessarily a deal-breaker.

If a warning is critical (wrong slice count, missing pixel spacing) **stop**. The dataset isn't right for testing. Find a complete one.

### 2. Confirm slice mapping

Switch to the **Slice mapping** tab. Auto-mapping should place ACR slice 1 on the inferior slice with the bars/wedges, slice 7 in a uniform region, and slice 11 on the superior wedge pair.

Click each preview to enlarge if needed. If anything looks wrong, override the mapping with the number inputs.

### 3. Run the QA

On the **Analysis** tab, click **Run all automated tests**. Watch the progress bar. Applicable tests should each complete in seconds. If any errors out on complete, correctly mapped data, note the test name — that's a bug to report.

For the two visual tests:

- High-contrast resolution: on **Manual scoring**, find the smallest size where all four holes are distinguishable in any UL row and any LR column. The passing limit is fixed at ≤1.0 mm.
- Low-contrast detectability: on **Manual scoring**, look at slices 8–11, count complete spokes on each, and save the scoring.

### 4. Verify every overlay

This is the most important step. Switch to **Results**. For each automated test shown for the selected series:

- Open the test's section (clicking the row expands it).
- Look at the **annotated image**.
- Verify that the detector landed in the right place:
   - Geometric Accuracy: the colored measurement lines must cross the phantom from edge to edge, not from a bright spot to a bright spot. Each line should be a chord through the phantom centroid.
   - Slice Thickness: the cyan and magenta lines must lie along the two bright bars of the slice-thickness insert near the phantom center. Not along the phantom edge, not on a wedge.
   - Slice Position: the cyan and magenta vertical lines must lie on the two wedge bars near the top of the phantom. Not on the phantom edge.
   - PIU: the large cyan circle should fill ~80% of the phantom interior. The red and blue small circles should be inside that large circle.
   - PSG: the four colored ellipses should sit *outside* the phantom in air, not overlap the phantom. The large cyan circle should be inside the phantom.

If the overlay is wrong, the number is wrong even if the pass/fail label looks plausible. Flag it.

### 5. Read the confidence chip

Each test has a **Confidence: HIGH / MEDIUM / LOW** badge. The heuristics that drive this are:

- Geometric Accuracy: measured length must be in [100, 230] mm or LOW; within 15 mm of nominal or MEDIUM; otherwise HIGH.
- Slice Thickness: result must be in [1, 15] mm or LOW; top/bot ramp FWHM asymmetry < 40% or MEDIUM.
- Slice Position: |Δ| ≤ 20 mm or LOW.
- PIU: result in [50, 100]% or LOW.
- PSG: air ROIs must have mean signal < 10% of phantom mean or MEDIUM (likely overlap with phantom).
- Phantom radius outside [70, 115] mm at all → MEDIUM warnings on PIU/PSG.

A LOW or MEDIUM is a sign to look at the overlay, not a guarantee the result is wrong. Investigate.

### 6. Record the dataset

Switch to the **Validation** tab.

Fill in **Dataset label**, **Vendor**, **Scanner / model**.

Under "Manual measurements", enter the numbers from your own QA workflow for as many tests as you measured. The app accepts text (no validation on units) so you can paste whatever you have.

Write any observations in the **Notes** field — overlay placement issues, surprising values, "matches our caliper measurement perfectly," etc.

Click **Add to validation log**.

### 7. Export

Switch to the **Export** tab. Click **Generate PDF + CSV**. Download both. Open the PDF and confirm:

- Cover page has scanner, study date, sequence, slice count.
- Pass/fail summary table is correct.
- Each test page has a measurements table and at least one annotated image.
- The overall verdict block at the top of the cover is the expected color.
- The footer of every page has the engine version, generation timestamp, and a 16-character signature.

The PDF is what your accreditation reviewer would see — judge it as if you were that reviewer.

### 8. Repeat

Repeat steps 1–7 for every dataset. The Validation tab keeps growing the log. When you've done all your datasets, click **Download validation log (CSV)** to save the full record.

---

## The dataset-by-dataset comparison table

The Validation Log CSV columns include, per entry:

```
logged_at, dataset, vendor, scanner, field_strength_t, study_date, series, sequence,
n_slices, verdict, pass_count, fail_count, review_count, error_count,
<test_id>__status, <test_id>__confidence, <test_id>__warnings,
<test_id>__app_value, <test_id>__unit, <test_id>__error,
manual__geo_slice1, manual__geo_slice5_h, manual__geo_slice5_v,
manual__slice_thickness, manual__slice_position_1, manual__slice_position_11,
manual__piu, manual__psg, manual__res_ul, manual__res_lr, manual__lcd_total,
notes
```

Open the CSV in Excel or Numbers. The columns prefixed `manual__` are what you entered; the columns prefixed `<test_id>__app_value` are what the app produced. Side-by-side comparison is one VLOOKUP or one quick eyeball.

What I'd like to see when you send this CSV back: which tests agree with manual within tolerance, which disagree, and on which scanners.

---

## What to look for and report

Send the validation log CSV plus, for each disagreement, a screenshot of the annotated image and a one-line note. The pattern of failures matters more than any individual failure:

- **Same test fails on every vendor:** the algorithm is wrong, not the data.
- **Same test fails only on one vendor:** the detector needs vendor-specific tuning. Usually a different image-intensity scale or a different in-plane orientation.
- **Geometric accuracy off by exactly 2× pixel spacing:** off-by-one in the edge detection. Easy fix.
- **PIU low confidence and overlay shows the small ROI in air:** phantom segmentation included background. Fix is in `phantom.py`.
- **Slice thickness wildly different from manual:** ramp detection picked up the wrong feature. Fix is in `slice_thickness.py`.

Three datasets per scanner from one vendor is the bare minimum to call any test "validated" for that scanner. More is better. Datasets that contain a known real failure are gold — they prove the app *can* detect a real problem, not just call everything PASS.

---

## What good looks like

After ~10 datasets across 2 vendors, you should be able to say one of three things to your pilot customer:

1. *"Every automated test agreed with my manual measurement within tolerance on every dataset. We're ready for pilot use."*
2. *"Most tests agreed; tests X and Y need adjustment before pilot use."*
3. *"The app is consistently wrong on at least one fundamental test. It's not ready."*

The validation log is the evidence behind whichever statement you make. Don't ship without it.

---

## When to escalate

Stop and flag a dataset to me if any of the following happen:

- The app crashes during analysis. Capture the error text from the Terminal (or `streamlit.log`).
- Any test errors out (status = ERROR) on a clean dataset. Send the test ID and the screenshot.
- A test reports PASS with LOW confidence and the overlay clearly shows the detector on the wrong feature. This is the worst kind of bug: the user trusts a number that's based on noise.

We iterate on the data, not on opinions.
