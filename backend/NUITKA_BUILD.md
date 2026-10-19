# Building the backend with Nuitka

The backend now ships as a compiled binary rather than source + venv.
`app/cli.py` is the compiled entry point, so the one binary is both the
server (`molly serve`) and the admin CLI (`molly worker enroll`,
`molly connect`, `molly projects`, `molly run ...`).

## Build

```bash
./build_nuitka.sh
```

Run this **on the same OS/architecture you'll deploy to** (or an
equivalent build image/container, e.g. `ubuntu:24.04` matching your server).
Nuitka compiles to native code and bundles native shared libraries
(pydantic-core, tree-sitter's per-language `.so`s, etc.) - the output is
not portable across OS or CPU architecture the way the pure-Python
source tree was.

Output: `dist/cli.dist/`, a self-contained directory. The whole directory
is the artifact - copy it as-is to the target machine. Nothing else from
this repo (no venv, no system Python) is required there; even `init_db()`
/ `create_default_projects()` run from inside the binary automatically on
first `molly serve` startup, same as they do from source.

## Deploy

```bash
sudo ./deploy.sh                      # looks for dist/cli.dist/ next to this script
sudo ./deploy.sh /path/to/cli.dist    # or point at a build produced elsewhere
```

This installs the compiled tree under `/var/www/molly/backend`, wires
a systemd unit that runs `molly serve` directly (no interpreter, no
venv activation), and prints the enrollment/pairing steps.

## What changed to make this work

- **`app/main.py`**: the direct (`python -m app.main`) entry point used
  to always start uvicorn via the string `"app.main:app"`. That only
  works because `-m app.main` guarantees the running module *is*
  `sys.modules["app.main"]`. A compiled entry point runs as `__main__`,
  so that string would instead trigger a **second**, independent import
  of `app.main` - a second `FastAPI()`, routers registered twice,
  `structlog.configure()` called twice, etc. Fixed by passing the `app`
  object directly to `uvicorn.run()` in the non-reload path (reload still
  needs the string form, and reload can't work in a frozen binary
  anyway, so it's dev-only now).
- **Compiled entry point is `app/cli.py`, not `app/main.py`**: `cli.py`'s
  `serve` command still starts uvicorn via `"app.main:app"` - but here
  that's correct, since `app.cli` genuinely isn't `app.main` and always
  needs a fresh import of it. This *is* a dynamic (string-based) import
  though, invisible to Nuitka's static import-follower, which is why the
  build passes `--include-package=app` explicitly rather than relying on
  `--follow-imports` to discover `app.main` on its own.
- **`--include-package` for uvicorn's runtime-selected implementations**
  (`uvloop`, `httptools`, `websockets`, `wsproto`, `h11`): uvicorn's
  `loop="auto"` / `http="auto"` pick one of these via `importlib` at
  startup based on what's installed, not via a static import Nuitka can
  trace from `app/cli.py`. Without forcing them in, the compiled binary
  would silently fall back to the slower pure-Python paths instead of
  uvloop/httptools.
- **`google.genai`**: `google` is a namespace package; called out
  explicitly since Nuitka's namespace-package handling sometimes needs
  the nudge even though the plain `from google import genai` import is
  otherwise static and traceable.
- **tree-sitter language packages** (`tree_sitter_python`,
  `_javascript`, `_typescript`, `_go`, `_rust`): each ships a compiled
  extension module. These are handled like any other C extension by
  Nuitka's standalone mode, but are included explicitly for clarity and
  to guard against any lazy-loading path inside them.
- **`certifi`**: included as package *data* (`--include-package-data`)
  since httpx/openai/google-genai load its `cacert.pem` as a file at
  runtime, not via a Python import.
- **Test-only packages excluded** (`pytest`, `pytest-asyncio`,
  `pytest-cov`, `coverage`) via `--nofollow-import-to` - they're in
  `requirements.txt` for local test runs but have no reason to be in a
  production binary.

## Things that did *not* need special handling

- **SQLite**: `app/storage/database.py` uses the stdlib `sqlite3` module
  directly (no `aiosqlite`/driver package), so it's just always present.
- **Config/data paths**: `.env`, `data/app.db`, `data/uploads/`,
  `data/projects/` are all resolved as paths **relative to the current
  working directory** (via `pydantic-settings`' `env_file=".env"` and the
  `Settings` defaults), not relative to `__file__`. That means they work
  identically whether running from source or from the compiled binary,
  as long as the process's working directory is the deployment directory
  - which is exactly what `deploy.sh`'s systemd unit sets via
  `WorkingDirectory=`. The one exception, `persist_env_vars()`'s
  `ENV_FILE_PATH`, does use `Path(__file__)` - Nuitka gives compiled
  modules a synthetic-but-consistent `__file__` inside the dist tree, so
  `parent.parent` still resolves to the dist root, matching the same
  `.env` the relative lookup above uses.
- **`-e ../protocol`** (the local `molly_tunnel_protocol` package):
  `pip install -r requirements.txt` inside the build venv installs it in
  editable mode, which is enough for Nuitka to find and compile it in -
  it only needs the package to be importable at build time.

## Rebuilding after a code change

Just re-run `./build_nuitka.sh` (it recreates its build venv each time)
and re-run `./deploy.sh` to push the new `dist/cli.dist/` out and restart
the service. There's no incremental-compile shortcut set up here; a full
rebuild takes a few minutes given the C-extension-heavy dependency list
(tree-sitter, pydantic-core, etc.), which is normal for Nuitka and not
specific to this project.

## Verifying a build before deploying

```bash
cd dist/cli.dist
cp /path/to/real/.env .        # or a throwaway test .env
./molly projects               # exercises app.config, app.storage - no server needed
./molly serve                  # then hit http://127.0.0.1:8000/ in another shell
```
