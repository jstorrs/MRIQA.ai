#!/bin/bash
# MRIQA.ai launcher — double-click in Finder.
# Starts Streamlit as a background process so closing this Terminal
# window does NOT stop the app. Use "Stop MRIQA.command" to stop it.

cd "$(dirname "$0")" 2>/dev/null || cd "$(dirname "${BASH_SOURCE[0]}")"

LOGFILE="launch.log"
APP_LOG="streamlit.log"
PIDFILE=".streamlit.pid"
PORTFILE=".streamlit.port"
PROJECT_DIR="$(pwd)"

{
    echo "=== MRIQA.ai launch — $(date) ==="
    echo "Project dir: $PROJECT_DIR"
} > "$LOGFILE"

exec > >(tee -a "$LOGFILE") 2>&1

show_dialog() {
    osascript -e "display dialog \"$1\" buttons {\"OK\"} default button \"OK\" with title \"MRIQA.ai\" with icon stop" >/dev/null 2>&1 || true
}

die() {
    echo ""
    echo "==================================================="
    echo "ERROR: $1"
    echo "==================================================="
    echo "Full log: $PROJECT_DIR/launch.log"
    show_dialog "MRIQA.ai could not start.\n\n$1\n\nFull log: $PROJECT_DIR/launch.log"
    echo "Press Return to close this window."
    read -r _ || true
    exit 1
}

echo ""
echo "================================================"
echo "  MRIQA.ai — ACR Large Phantom QA"
echo "================================================"
echo ""

# ---- 0. If an existing instance is running, surface that and exit ----
if [ -f "$PIDFILE" ]; then
    OLD_PID="$(cat "$PIDFILE" 2>/dev/null || echo '')"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        OLD_PORT="$(cat "$PORTFILE" 2>/dev/null || echo 8501)"
        echo "MRIQA.ai is already running (PID $OLD_PID) on port $OLD_PORT."
        echo "Opening browser to http://localhost:$OLD_PORT ..."
        open "http://localhost:$OLD_PORT"
        echo ""
        echo "To stop the app, double-click 'Stop MRIQA.command'."
        echo "This window will close automatically in 5 seconds."
        sleep 5
        exit 0
    fi
fi

# ---- 1. Find or create the venv Python ----
VENV_PY=".venv/bin/python3"
if [ ! -x "$VENV_PY" ]; then
    echo "Creating Python virtual environment..."
    SYSPY=""
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$c" >/dev/null 2>&1; then
            ver=$("$c" -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])" 2>/dev/null || echo 0)
            if [ "$ver" -ge 310 ]; then SYSPY="$c"; break; fi
        fi
    done
    if [ -z "$SYSPY" ]; then
        if osascript -e 'display dialog "Python 3.10+ is required. Open the Python download page?" buttons {"Cancel","Open Python.org"} default button "Open Python.org" with title "MRIQA.ai" with icon caution' 2>/dev/null | grep -q "Open Python.org"; then
            open "https://www.python.org/downloads/macos/"
        fi
        die "Python 3.10+ not found. After installing, run the launcher again."
    fi
    "$SYSPY" -m venv .venv || die "Failed to create the virtual environment."
fi
[ -x "$VENV_PY" ] || die "Python venv is broken (no .venv/bin/python3)."
echo "Python in venv: $($VENV_PY --version 2>&1)"

# ---- 2. Verify or install packages ----
if ! "$VENV_PY" -c "import streamlit, pydicom, numpy, scipy, skimage, matplotlib, reportlab, PIL" >/dev/null 2>&1; then
    echo "Installing Python packages..."
    osascript -e 'display notification "Installing packages (~30 s)" with title "MRIQA.ai"' >/dev/null 2>&1 || true
    "$VENV_PY" -m pip install --quiet --upgrade pip || die "Could not upgrade pip."
    "$VENV_PY" -m pip install -r requirements.txt || die "Could not install required packages. Check your internet connection."
fi
echo "All packages present."

# ---- 3. Pick a free port ----
PORT=8501
while lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; do
    PORT=$((PORT + 1))
    if [ "$PORT" -gt 8520 ]; then
        die "No free port between 8501 and 8520. Run 'Stop MRIQA.command' and try again."
    fi
done
echo "Using port $PORT"
echo "$PORT" > "$PORTFILE"

# ---- 4. Launch Streamlit IN THE BACKGROUND, detached from this Terminal ----
# nohup + setsid so closing the Terminal doesn't send SIGHUP to streamlit.
# Output goes to streamlit.log.
echo "Starting Streamlit (background process)..."
nohup "$VENV_PY" -m streamlit run streamlit_app.py \
    --server.headless true \
    --browser.gatherUsageStats false \
    --server.port "$PORT" \
    > "$APP_LOG" 2>&1 &

STREAMLIT_PID=$!
echo "$STREAMLIT_PID" > "$PIDFILE"
disown 2>/dev/null || true

# ---- 5. Wait for the server to actually be listening ----
echo "Waiting for the server to come up..."
READY=false
for i in {1..40}; do
    if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        READY=true
        break
    fi
    if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
        break
    fi
    sleep 0.5
done

if [ "$READY" != true ]; then
    rm -f "$PIDFILE" "$PORTFILE"
    echo ""
    echo "Streamlit failed to start. Tail of its log:"
    tail -n 50 "$APP_LOG" 2>/dev/null
    die "Streamlit did not start listening on port $PORT. See $APP_LOG."
fi

echo ""
echo "================================================"
echo "  READY at http://localhost:$PORT"
echo "================================================"
echo ""
echo "The app is now running in the background (PID $STREAMLIT_PID)."
echo "You can CLOSE this Terminal window — the app keeps running."
echo "To stop the app later, double-click 'Stop MRIQA.command'."
echo ""
echo "Opening your browser..."
open "http://localhost:$PORT"

osascript -e "display notification \"App ready at localhost:$PORT — you can close the Terminal\" with title \"MRIQA.ai\"" >/dev/null 2>&1 || true

# Stay open for a few seconds so the user can read the message, then exit cleanly.
echo "This window will close automatically in 8 seconds."
sleep 8
exit 0
