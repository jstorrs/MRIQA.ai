# How to run MRIQA.ai

## 99% of the time:

**Double-click `Launch MRIQA.command`** in this folder. Your browser opens with the app. Done.

---

## First time only — three possible hiccups, all one-time fixes

### Hiccup 1: macOS says "cannot be opened because it is from an unidentified developer"

This is macOS being protective of scripts that came from the internet. Two ways to fix it:

**Easiest:** double-click `First-time-setup.command` first. It strips the warning flag. Then double-click `Launch MRIQA.command`.

**Manual:** right-click `Launch MRIQA.command` → **Open** → click **Open** in the warning dialog. You only do this once.

### Hiccup 2: "Python 3.10 or newer is required"

The launcher will pop up a dialog and offer to open the Python download page for you. Click **Open Python.org**, download **Python 3.12** (the big yellow button), run the installer, then double-click `Launch MRIQA.command` again.

### Hiccup 3: First launch takes a minute

The very first time you run it, the launcher installs the Python libraries it needs (numpy, pydicom, streamlit, etc.) — about 30 seconds on a decent connection. You'll see install messages scroll past in the Terminal window. After that, every future launch is instant.

---

## Where things live

| Thing | Location |
|---|---|
| Launch the app | `Launch MRIQA.command` (this folder) |
| Your QA reports (PDF/CSV) | `exports/` |
| App code | `app/` |
| Feasibility doc | `docs/feasibility.md` |

## How to stop the app

Close the Terminal window that popped up when you launched. That stops the local web server. The browser tab can be closed any time without affecting anything.
