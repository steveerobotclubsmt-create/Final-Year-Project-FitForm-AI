#!/bin/bash
# Starts FitForm from the desktop icon (tools/fitform.desktop). Only one copy runs at a time - a second one
# could not open the camera or the phone app's port. Output goes to logs/fitform_app.log.
# Install the icon on the desktop and in the menu:  bash tools/run_fitform.sh --install
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

if [ "$1" = "--install" ]; then
    sed "s|@ROOT@|$ROOT|g" tools/fitform.desktop > /tmp/fitform.desktop
    mkdir -p ~/.local/share/applications ~/Desktop
    install -m 755 /tmp/fitform.desktop ~/.local/share/applications/fitform.desktop
    install -m 755 /tmp/fitform.desktop ~/Desktop/fitform.desktop
    rm -f /tmp/fitform.desktop
    echo "FitForm icon added to the desktop and the menu"
    exit 0
fi

if pgrep -f "fitform_env/bin/python main.py" > /dev/null; then
    exit 0                                   # already running
fi
mkdir -p logs
echo "=== started $(date '+%Y-%m-%d %H:%M:%S') ===" >> logs/fitform_app.log
exec "$HOME/fitform_env/bin/python" main.py >> logs/fitform_app.log 2>&1
