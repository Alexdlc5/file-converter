#!/bin/sh
# Sets up File Converter and adds it to your desktop and app menu.
cd "$(dirname "$0")" || exit 1
for py in python3 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    exec "$py" install.py "$@"
  fi
done
echo "Python 3.9+ with Tk is needed, e.g.: sudo apt install python3 python3-venv python3-tk"
exit 1
