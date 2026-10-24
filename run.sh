#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x backend/.venv/bin/python ]; then
  echo 'Set up backend/.venv first; see README.md.' >&2
  exit 1
fi
if [ ! -f website/dist/app.js ]; then
  npm --prefix website ci
  npm --prefix website run build
fi
exec backend/.venv/bin/python backend/app.py "$@"
