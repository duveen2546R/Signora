#!/usr/bin/env bash
# Idempotent setup for a fresh clone of SignSure. Safe to re-run.
#
#   ./scripts/setup.sh              # backend + validation + frontend, then tests
#   ./scripts/setup.sh --live       # also local speech recognition (Sherpa-ONNX, ~44 MB model)
#   ./scripts/setup.sh --skip-tests # install only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
LIVE=0
TESTS=1
for arg in "$@"; do
  case "$arg" in
    --live) LIVE=1 ;;
    --skip-tests) TESTS=0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }
warn() { printf '!!  %s\n' "$*" >&2; }

step "Checking tools"
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3.12 python3.13 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
[ -n "$PY" ] || { warn "Python 3.11+ is required (3.12 is what the project is tested on)."; exit 1; }
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), sys.version' \
  || { warn "$PY is older than 3.11; set PYTHON=/path/to/python3.12"; exit 1; }
echo "python: $("$PY" --version)"
if command -v node >/dev/null 2>&1; then
  echo "node: $(node --version)"
  node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22||(a===22&&b>=12)||(a===20&&b>=19)||(a>20&&a<22)?0:1)' \
    || warn "Vite needs Node 20.19+ or 22.12+."
else
  warn "Node.js and npm are required for the frontend (20.19+ or 22.12+)."
fi

step "Python environment (.venv at the repository root)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
VENV_PY="$ROOT/.venv/bin/python"
"$VENV_PY" -m pip install --upgrade pip >/dev/null
"$VENV_PY" -m pip install \
  -r backend/requirements-dev.txt \
  -r backend/requirements-validation-video.txt \
  -r backend/requirements-validation-secondary.txt
if [ "$LIVE" = 1 ]; then
  "$VENV_PY" -m pip install -r backend/requirements-live.txt
  (cd backend && "$VENV_PY" tools/setup_live_speech.py)
fi

step "Runtime data directories (git-ignored)"
mkdir -p backend/data/uploads backend/data/clips backend/data/transitions \
  backend/data/video-plans backend/data/analyses

step "Pose models (RTMW whole-body + YOLOX detector, cached in ~/.cache/rtmlib)"
"$VENV_PY" - <<'EOF'
from rtmlib import Wholebody
Wholebody(mode="performance", to_openpose=False, backend="onnxruntime", device="cpu")
print("rtmlib models ready")
EOF

step "Frontend dependencies"
if command -v npm >/dev/null 2>&1; then
  (cd frontend && if [ -f package-lock.json ]; then npm ci; else npm install; fi)
fi

step "Checking local-only assets that Git does not carry"
if [ ! -f SignoraAvatarTracking/WebBuild/Build/WebBuild.loader.js ]; then
  warn "Unity WebGL build missing (SignoraAvatarTracking/WebBuild, ~73 MB, git-ignored)."
  warn "The avatar will not render until it is copied from another machine or rebuilt with"
  warn "Unity 6000.5.9f1 + WebGL Build Support. Analysis, validation and the API work without it."
fi
ls videos/*.mp4 >/dev/null 2>&1 || warn "videos/*.mp4 reference clips are git-ignored; copy them if you need them."

if [ "$TESTS" = 1 ]; then
  step "Backend tests"
  (cd backend && "$VENV_PY" -m pytest -q)
  if command -v npm >/dev/null 2>&1; then
    step "Frontend tests"
    (cd frontend && npm test)
  fi
fi

step "Done"
cat <<'EOF'
Run the app (two terminals):
  cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000
  cd frontend && npm run dev          # http://localhost:5173
EOF
