#!/bin/bash
# Run this ONCE if macOS won't open "Launch MRIQA.command".
# It removes the quarantine flag macOS puts on files from the internet.

cd "$(dirname "$0")"
xattr -dr com.apple.quarantine . 2>/dev/null || true
chmod +x "Launch MRIQA.command" 2>/dev/null || true
chmod +x "First-time-setup.command" 2>/dev/null || true

osascript -e 'display dialog "Setup complete. Now double-click \"Launch MRIQA.command\" to start the app." buttons {"OK"} default button "OK" with title "MRIQA.ai" with icon note' >/dev/null 2>&1
