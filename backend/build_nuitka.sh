#!/bin/bash
# Compile the Molly backend into a standalone Nuitka binary.
#
# Run this ON the target OS/architecture (or an equivalent build image/
# container) - Nuitka produces native code plus bundled shared libraries,
# and that output is not portable across OS or CPU architecture. If you
# deploy to e.g. Ubuntu 24.04 x86_64, build on Ubuntu 24.04 x86_64.
#
# Output: dist/cli.dist/  - a self-contained directory. Copy the whole
# directory to the target machine; nothing else from this repo (no venv,
# no system Python) is required there. Entry point inside it is the
# `molly` executable, which is app/cli.py compiled - so it's both the
# server ("molly serve") and the admin CLI ("molly worker enroll",
# "molly connect", "molly projects", "molly run ...") in one binary.

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_VENV="$BACKEND_DIR/.nuitka-build-venv"
DIST_DIR="$BACKEND_DIR/dist"

cd "$BACKEND_DIR"

echo "=== Molly Backend: Nuitka standalone build ==="

# --- 1. Isolated build environment -----------------------------------
# A dedicated venv (not the dev venv) so build-only tooling (nuitka,
# ordered-set, zstandard) never leaks into the requirements.txt used for
# normal source deployments.
python3 -m venv "$BUILD_VENV"
# shellcheck source=/dev/null
source "$BUILD_VENV/bin/activate"
pip install --upgrade pip

# requirements.txt includes "-e ../protocol": pip installs it in editable
# mode, which is enough for Nuitka to find and compile it in - it just
# needs to be importable at compile time, same as any other dependency.
pip install -r "$BACKEND_DIR/requirements.txt"
pip install "nuitka>=2.5,<3" ordered-set zstandard

# --- 2. Compile --------------------------------------------------------
# --standalone (not --onefile): this runs under systemd as a long-lived
# process, so there's no benefit to onefile's self-extracting wrapper -
# it would just add extraction latency to every restart. Standalone also
# ships as a plain directory, which is simpler to rsync/inspect/diff.
#
# The --include-package flags below exist because uvicorn chooses several
# of these implementations at runtime via importlib string lookups (e.g.
# loop="auto"/http="auto"), and because serve() itself reaches app.main
# via the string "app.main:app" (uvicorn re-imports it by name) rather
# than a plain top-level import. Nuitka's static import-follower can't
# see either kind of reference from app/cli.py alone - --include-package
# forces them in regardless. Everything else (fastapi, starlette, the
# rest of app.*, ...) is reached by ordinary top-level imports and gets
# included automatically by --follow-imports.
python -m nuitka \
    --standalone \
    --output-dir="$DIST_DIR" \
    --output-filename=molly \
    --follow-imports \
    --python-flag=no_site \
    --include-package=app \
    --include-package=molly_tunnel_protocol \
    --include-package=google.genai \
    --include-package=uvloop \
    --include-package=httptools \
    --include-package=websockets \
    --include-package=wsproto \
    --include-package=h11 \
    --include-package=tree_sitter \
    --include-package=tree_sitter_python \
    --include-package=tree_sitter_javascript \
    --include-package=tree_sitter_typescript \
    --include-package=tree_sitter_go \
    --include-package=tree_sitter_rust \
    --include-package-data=certifi \
    --nofollow-import-to=pytest \
    --nofollow-import-to=pytest_asyncio \
    --nofollow-import-to=pytest_cov \
    --nofollow-import-to=coverage \
    --assume-yes-for-downloads \
    app/cli.py

# deploy.sh uses this to seed a fresh deployment's .env; Nuitka's output
# contains only Python modules/native libs, not repo-side config templates.
cp "$BACKEND_DIR/.env.example" "$DIST_DIR/cli.dist/.env.example"

deactivate

echo ""
echo "=== Build complete ==="
echo "Directory: $DIST_DIR/cli.dist/"
echo "Binary:    $DIST_DIR/cli.dist/molly"
echo ""
echo "Quick smoke test:"
echo "  cd $DIST_DIR/cli.dist && ./molly serve"
echo "  cd $DIST_DIR/cli.dist && ./molly projects"
echo ""
echo "The .env file (or a systemd EnvironmentFile) still needs to live"
echo "next to the binary / be set on the process, same as the source"
echo "deployment - compiling doesn't change how config is read."
