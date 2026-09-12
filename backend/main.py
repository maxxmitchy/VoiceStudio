import os
import sys

# Ensure `backend/` is on sys.path so bare imports like `from core.config`
# work regardless of how uvicorn is invoked:
#   - `uvicorn main:app`           (cwd = backend/)
#   - `uvicorn backend.main:app`   (cwd = /app, Docker)
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# PyInstaller re-executes this entry module when the frozen backend binary is
# launched. Nested operation supervisors therefore dispatch here, before math,
# logging, FastAPI, torch, or any application initialization. Source launches
# use this same entry contract so frozen/source behavior cannot drift.
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--supervise":
    from core.contained_subprocess import supervisor_main

    raise SystemExit(supervisor_main(sys.argv[1:]))

# Rust clears CLOEXEC only for the backend exec. Re-arm PEP 446 immediately:
# nested supervisors receive this descriptor solely through explicit pass_fds,
# so a third-party close_fds=False child cannot hold the desktop drain barrier.
from core.contained_subprocess import secure_backend_drain_fd  # noqa: E402

secure_backend_drain_fd()

import math  # noqa: E402

# Windows: run every child process (ffmpeg, engine sidecars, yt-dlp, demucs, …)
# WITHOUT popping a console window. The backend itself is spawned console-less by
# the Tauri shell, so on Windows each console subprocess it launches would
# otherwise get a brand-new cmd window flashed on screen. Patch subprocess.Popen
# once, before anything spawns, so our 70+ call sites AND third-party libraries
# (imageio-ffmpeg, yt-dlp) are all covered. No-op off Windows. (#1178)
from core.win_subprocess import install as _install_no_window  # noqa: E402

_install_no_window()

# #564: also make the project's OWN `omnivoice` package importable from source
# when the venv's editable install is missing/broken (interrupted/offline
# `uv sync`, antivirus-quarantined `_editable_impl_omnivoice.pth`, …). Without
# this the backend boots fine and only fails at the first model call with
# `No module named 'omnivoice'`. The bootstrap now gates on omnivoice being
# importable too (re-syncing to re-lay the editable install); this is the
# runtime safety net. See core/omnivoice_path.py for the full rationale.
from core.omnivoice_path import ensure_omnivoice_importable
ensure_omnivoice_importable(_backend_dir)

# Triton is unavailable on Windows — disable torch.compile / dynamo / inductor
# to prevent TritonMissing errors at inference time. Must be set before torch
# is imported (it is lazily imported in services/model_manager.py). Uses
# setdefault so an explicit user-set value is never overridden, and is guarded
# to win32 so cross-platform default behavior is unchanged.
if sys.platform == "win32":
    os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")
    os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
    os.environ.setdefault("TORCHINDUCTOR_DISABLE", "1")

# The Intel Fortran runtime bundled with MKL (under numpy/scipy) installs a
# console CTRL handler that aborts the whole process with `forrtl: error
# (200): program aborting due to window-CLOSE event` when a Windows console
# CLOSE/LOGOFF/SHUTDOWN event reaches it — seen in the wild as backend crashes
# with exit code 2 / 0xC000013A mid-session (#1153 class). The RTL reads this
# at DLL init, so it must be set before torch/numpy import MKL; setdefault so
# an explicit user value wins. A no-op everywhere the Fortran RTL isn't
# handling console events (macOS/Linux), hence unconditional (and testable).
os.environ.setdefault("FOR_DISABLE_CONSOLE_CTRL_HANDLER", "1")

# The backend's stdout/stderr are pipes owned by the desktop shell that
# spawned it. If that shell exits while the backend survives (crash,
# relaunch, orphan), the pipes close — and the next write raises
# BrokenPipeError. transformers' tqdm weight-loading bar writes constantly,
# so an orphaned backend couldn't load the model at all (caught in the wild
# by the in-app diagnostic report). Wrap stdio so EPIPE is swallowed
# process-wide: logs are best-effort for a server, model loading is not.
# (utils.hf_progress.SafeFileWrapper — same wrapper the patched hub tqdm
# already uses for its own fp.)
from utils.hf_progress import SafeFileWrapper as _SafeStdio  # noqa: E402
from core.parent_liveness import arm_desktop_parent_watchdog  # noqa: E402

# Force UTF-8 stdio before wrapping (#1155): on Windows the spawned backend's
# stdout defaults to cp1252, and any library that prints user text (kittentts
# prints the full synth text on every generate) raised UnicodeEncodeError on
# Vietnamese/CJK/…, killing the request with a bogus 400. backslashreplace
# keeps even a non-UTF-8-able sink from ever raising.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:  # noqa: BLE001 — pythonw/frozen builds may lack reconfigure
        pass

# The desktop keeps the backend's stdin pipe open for its own lifetime. EOF is
# therefore a stable ownership signal that survives PID reuse and lets a child
# terminate even when the shell crashes before its normal process-tree teardown.
arm_desktop_parent_watchdog()

if not getattr(sys.stdout, "_is_safe_wrapper", False):
    sys.stdout = _SafeStdio(sys.stdout)
if not getattr(sys.stderr, "_is_safe_wrapper", False):
    sys.stderr = _SafeStdio(sys.stderr)

try:
    import dotenv

    dotenv.load_dotenv()
    # Also load .env from the project root (parent of backend/)
    _project_env = os.path.join(os.path.dirname(_backend_dir), ".env")
    if os.path.isfile(_project_env):
        dotenv.load_dotenv(_project_env, override=False)
    # Load the durable per-user config (the in-app Settings source of truth) so
    # env vars set once survive Tauri/Finder launches that don't inherit a shell
    # environment. This OVERRIDES launcher-injected defaults: the desktop app
    # injects a stale OMNIVOICE_CACHE_DIR from its own config before startup, so
    # without override a models dir changed in Settings was ignored forever (#480).
    from core.user_env import load_into_environ as _load_user_env
    _load_user_env()
except ImportError:
    pass

# ── cuDNN 8 library preload ─────────────────────────────────────────────
# Moved into _phase_a_build (`native_preload` step, early-bind refactor): the
# native dlopen/LoadLibrary belongs to the deferred heavy phase, and its one
# hard invariant — run before any ctranslate2/torch import — is preserved
# there (native_preload strictly precedes ml_imports).

# Route HF/Torch caches to a single external directory when requested.
_cache_dir = os.environ.get("OMNIVOICE_CACHE_DIR")
if _cache_dir:
    os.makedirs(_cache_dir, exist_ok=True)
    os.environ["HF_HOME"] = _cache_dir
    os.environ["HF_HUB_CACHE"] = _cache_dir
    os.environ["TORCH_HOME"] = _cache_dir

# ── Windows symlink fix ─────────────────────────────────────────────────────
# HuggingFace Hub creates NTFS symlinks in its cache to deduplicate blobs
# across model revisions.  On Windows, symlink creation requires either
# Developer Mode enabled or an elevated (Administrator) shell.  Without
# either, `snapshot_download` / `hf_hub_download` raises:
#   OSError: [WinError 1314] A required privilege is not held by the client
# Setting HF_HUB_DISABLE_SYMLINKS_WARNING silences the console spam, and the
# newer HF_HUB_DISABLE_SYMLINKS (huggingface_hub ≥ 0.21) forces file copies
# instead — slightly more disk but always works on first install.
if sys.platform == "win32":
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

# ── HF Xet → legacy LFS fallback ────────────────────────────────────────────
# huggingface_hub ≥ 1.5 routes large file downloads through the Xet content-
# addressed protocol (hf_xet runtime), which has its own internal progress
# reporting that bypasses our `tqdm` monkey-patch in `utils.hf_progress`.
# As a result the SetupWizard install rows show no byte progress while the
# download is actually running. Force the legacy LFS path until we add a
# proper hf_xet progress hook — this still streams via the standard tqdm
# wrapper that our patch intercepts. Override-able by the user.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# ── HF network timeouts ─────────────────────────────────────────────────────
# Bound HF network ops so a stalled metadata HEAD or a dead download socket
# RAISES (and surfaces as an error) instead of hanging the model-load worker
# forever — the root cause of the "demo voice spins forever, no error" report
# (most often hit on Windows behind a proxy / firewall / antivirus that wedges
# the multi-GB legacy-LFS transfer). HF_HUB_DOWNLOAD_TIMEOUT is a *per-read*
# timeout: it resets on every received chunk, so a slow-but-progressing
# download is never punished — only a genuinely dead socket trips it. Both are
# user-overridable for unusually slow links. Set before huggingface_hub is
# imported so its constants pick them up.
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "15")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")

# ── OS trust store for TLS (#976) ───────────────────────────────────────────
# Users behind a corporate/antivirus proxy that TLS-inspects HTTPS traffic get
# a raw "[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] ssl/tls alert handshake failure"
# on every model install — the TCP connection succeeds (a different failure
# mode from #984's TCP-level blocked-host case), but the proxy re-signs the
# certificate with its own root CA, which the OS trusts (Windows CryptoAPI/
# SChannel) and Python's bundled `certifi` CA list does not. `inject_into_ssl`
# patches `ssl.SSLContext` process-wide to verify against the OS trust store
# instead, which is the actual fix (not just a nicer error message). Must run
# here — at MODULE level, before huggingface_hub/requests/httpx do any network
