# Deploy MRIQA.ai to the public web (free)

**Goal:** turn your local Streamlit app into a public URL like `https://mriqa.streamlit.app` that your pilot customer can click and use, with no install on their end. Free, ~20 minutes, no credit card.

**You will need:** a GitHub account (free), a Streamlit Community Cloud account (free, uses GitHub login), and a working internet connection.

---

## Step 1 — Create a GitHub account (skip if you already have one)

1. Go to <https://github.com/signup>.
2. Sign up with your email. Pick a free Personal account.
3. Verify your email when GitHub sends the confirmation.

---

## Step 2 — Install GitHub Desktop (easiest way to push code without Terminal)

You *can* do everything via Terminal with `git`, but GitHub Desktop has buttons instead of commands and is dramatically easier if you're not a daily git user.

1. Go to <https://desktop.github.com/> and download GitHub Desktop for macOS.
2. Open the `.dmg`, drag GitHub Desktop into Applications, launch it.
3. Sign in with the GitHub account you just made.

---

## Step 3 — Create a new repository for MRIQA.ai

1. In GitHub Desktop: **File → New repository...**
2. Fill in:
   - **Name:** `mriqa-ai`
   - **Local path:** `/Users/alifatemi/Documents/Claude/Projects/` (so it creates `mriqa-ai/` next to your existing folder)
   - **Initialize with a README:** uncheck (we already have one)
   - **Git ignore:** None
   - **License:** None for now
3. Click **Create repository**.

GitHub Desktop just made an empty folder at `~/Documents/Claude/Projects/mriqa-ai/`. We're going to copy our project files into that folder.

4. In Finder, open `~/Documents/Claude/Projects/MRIQA.ai/`.
5. Select EVERYTHING **except**: `.venv`, `__pycache__`, `exports`, `launch.log`, `streamlit.log`, `.streamlit.pid`, `.streamlit.port`. The `.gitignore` I added will skip these for you, but cleanly copying only the source code is safer.
6. Drag the selected files into the new `mriqa-ai/` folder GitHub Desktop just created.

Tip: an easy way to do this is just copy everything, GitHub Desktop will respect `.gitignore` and won't track the venv/logs.

---

## Step 4 — Publish the repository to GitHub

1. Back in GitHub Desktop, you should see a long list of "Changes" — every file you copied.
2. At the bottom-left, fill in:
   - **Summary:** `Initial commit`
3. Click **Commit to main**.
4. At the top, click **Publish repository**.
5. In the dialog:
   - Uncheck "Keep this code private" — Streamlit Community Cloud's free tier requires a public repo.
   - Click **Publish repository**.

Your code is now live on GitHub at `https://github.com/<yourname>/mriqa-ai`.

### Privacy note

The free tier requires a public repo. For an MVP that analyses **phantom** DICOMs (not patient data), this is fine — phantom data isn't PHI, and the ACR analysis math is published in the QC manual. If you want the repo private later, Streamlit Cloud has paid tiers, or you can deploy to Render/Fly (also have free tiers, support private repos).

**Important:** never put real patient DICOMs in this repo. The `.gitignore` already blocks `*.dcm` and `*.zip` files for this reason.

---

## Step 5 — Deploy to Streamlit Community Cloud

1. Go to <https://share.streamlit.io/>.
2. Click **Continue with GitHub** and authorize Streamlit to read your repos.
3. Click **Create app** (or **New app**).
4. Fill in:
   - **Repository:** `<yourname>/mriqa-ai`
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
   - **App URL:** pick something like `mriqa-pilot` — your URL will be `https://mriqa-pilot.streamlit.app`.
5. Click **Advanced settings** and set **Python version:** `3.12`.
6. Click **Deploy!**

Streamlit will spend 2-4 minutes installing your `requirements.txt` and starting the app. Watch the log on the right; you want to see "You can now view your Streamlit app in your browser."

When it's done, your app is live at the URL you chose.

---

## Step 6 — Test the live app end-to-end

1. Open your new URL (e.g. `https://mriqa-pilot.streamlit.app`) in an incognito/private window so you experience it the way your pilot will.
2. Upload the same `ACR test images/T1` zip you tested locally.
3. Run all automated tests.
4. Download the PDF.

If it works in incognito, it works for anyone with the URL.

---

## Step 7 — Send the URL to your pilot customer

A simple email template:

```
Subject: MRIQA.ai — please try the ACR phantom QA web app

Hi [name],

The web app is live: https://mriqa-pilot.streamlit.app

To try it:
  1. Open the URL (works in any modern browser; Chrome, Safari, Edge).
  2. In the sidebar, drop a DICOM folder (zipped) or your individual .dcm files.
  3. The metadata strip should populate from the DICOMs.
  4. Click into the "Run QA" tab and press "Run all automated tests".
  5. Inspect each test's results and annotated images.
  6. Export the PDF and open it.

Five of the seven ACR tests run fully automated. Two are visual scoring
tests (high-contrast resolution and low-contrast detectability) where the
app shows you the zoomed images and asks you to enter what you see.

This is an early MVP — please tell me where it gets numbers wrong, where
the UI confuses you, and what's missing for your real QA workflow. I'm
particularly interested in:
  - whether the geometric accuracy numbers match what your physicist gets
    with calipers
  - whether the slice-thickness and slice-position detectors land their
    ROIs in the right place on your scanner
  - what your current QA report looks like, so I can match the output

I'll iterate quickly on whatever you find.

Thanks,
Ali
```

---

## Step 8 — Iterate

Every time you change code in `~/Documents/Claude/Projects/mriqa-ai/`:

1. Open GitHub Desktop.
2. Type a short summary in the bottom-left ("Fix PSG threshold for 1.5T", etc).
3. Click **Commit to main**.
4. Click **Push origin** at the top.

Streamlit Cloud auto-detects the push and redeploys within ~60 seconds. Your pilot sees the updated app on their next page refresh.

---

## Troubleshooting

**"My app keeps showing 'Oh no.' on Streamlit Cloud."**
Click the "Manage app" button at the bottom of the page; you'll see the deploy log. Usually a missing package in `requirements.txt` — add it, commit, push, wait.

**"My pilot's uploads are huge and time out."**
The free Streamlit Cloud tier has 1 GB RAM. A normal ACR T1 series is ~5 MB so this is rarely an issue, but if you start handling full clinical series in the same app, move to Render's paid tier ($7-19/mo).

**"They can use it but I want it password-protected for the pilot."**
Streamlit Community Cloud has private apps on the Teams plan. Cheaper option: add `streamlit-authenticator` (one Python file change) and put a shared password in `.streamlit/secrets.toml`. I can walk you through this when you're ready.

**"They want it on a custom domain."**
Streamlit Community Cloud supports custom subdomains on Teams plan only. Render/Fly support custom domains on free tier. Cross that bridge after pilot validation.

---

## What this gets you

A live, hosted, free, multi-user web app at a URL you can put in a pitch deck, in a sales email, or on LinkedIn. Each visitor gets their own session (data is per-browser-session, not stored on the server beyond the current run). When you're ready for a real platform — multi-tenant database, login, billing — the full architecture is already written up in [`docs/saas_architecture.md`](./docs/saas_architecture.md) and the phased build sequence is in [`docs/saas_roadmap.md`](./docs/saas_roadmap.md).

**For now: ship this, sign two pilots, watch what they actually do, and let real customer feedback dictate what Phase 1 of the real platform looks like.** That's worth more than any architecture document.
