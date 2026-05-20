#!/bin/bash
# Stop the MRIQA.ai background process started by Launch MRIQA.command.

cd "$(dirname "$0")" 2>/dev/null || cd "$(dirname "${BASH_SOURCE[0]}")"

PIDFILE=".streamlit.pid"
PORTFILE=".streamlit.port"

echo "Stopping MRIQA.ai..."

STOPPED=false

# 1) Try the recorded PID first
if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE" 2>/dev/null)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        sleep 1
        kill -9 "$PID" 2>/dev/null || true
        STOPPED=true
        echo "Stopped PID $PID."
    fi
    rm -f "$PIDFILE"
fi

# 2) Belt-and-braces: kill anything streamlit-flavored on our port range
for p in 8501 8502 8503 8504 8505 8506 8507 8508; do
    PIDS="$(lsof -ti tcp:$p 2>/dev/null || true)"
    if [ -n "$PIDS" ]; then
        kill $PIDS 2>/dev/null || true
        sleep 0.5
        kill -9 $PIDS 2>/dev/null || true
        STOPPED=true
        echo "Killed process(es) on port $p."
    fi
done

rm -f "$PORTFILE"

if [ "$STOPPED" = true ]; then
    osascript -e 'display notification "MRIQA.ai stopped." with title "MRIQA.ai"' >/dev/null 2>&1 || true
    echo "Done."
else
    echo "Nothing to stop (MRIQA.ai was not running)."
fi

sleep 2
exit 0
