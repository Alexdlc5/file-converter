#!/bin/bash
# Double-click to set up File Converter. If macOS blocks it, right-click > Open.
cd "$(dirname "$0")" || exit 1

for py in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
          python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$py" >/dev/null 2>&1 && \
     "$py" -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    "$py" install.py
    status=$?
    echo
    read -n 1 -s -r -p "Press any key to close this window."
    exit $status
  fi
done

echo "Python 3 (with Tk) isn't installed. Get it from https://www.python.org/downloads/"
echo "then double-click this file again."
open "https://www.python.org/downloads/"
read -n 1 -s -r -p "Press any key to close this window."
exit 1
