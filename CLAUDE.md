# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**SPECTRA** (product name; internal codename WSA2) — a macOS/Windows audio measurement app by WAYAUDIO: real-time spectrum analysis, speaker/room Transfer Function, and broadcast stereo loudness. PyQt5 desktop app. **The entire application is a single file: `wayaudo2.py` (~17,800 lines).** The other `.py` files are tooling (license generation, manual/PDF builders).

## Run / build / version

```bash
python3 wayaudo2.py                 # run the app (deps: PyQt5 numpy scipy sounddevice soundfile)

bash build_silicon.sh               # macOS arm64  → dist/WSA2.app + WSA2_AppleSilicon.dmg
bash build_intel.sh                 # macOS x86_64 (needs a dedicated x86_64 Python venv, see memory)
# Windows: push a v* tag → GitHub Actions (.github/workflows/build-windows.yml), or `pyinstaller WSA2_Windows.spec`

bash bump_version.sh 1.6            # bumps _APP_VERSION + comment + WSA2.spec + build_intel.sh + version_info.txt
```

- Version source of truth: `_APP_VERSION` constant (`wayaudo2.py:100`). Footer/About/startup log derive from it. **Always bump via `bump_version.sh`** — it edits multiple files. RELEASE_NOTES.md is updated by hand.
- Code signing/notarization is automatic when env vars `SPECTRA_SIGN_ID` and `SPECTRA_NOTARY_PROFILE` are set (see `SIGNING.md`); otherwise the build is unsigned.

## Testing (no formal suite)

There is no pytest suite. Verification is done with **headless/offscreen Python snippets** run via `python3`. Two rules are mandatory:

- **Never let a test write the user's real settings/captures.** Always isolate with env vars, or you will overwrite the user's calibration (this has happened):
  ```bash
  QT_QPA_PLATFORM=offscreen WSA2_SETTINGS_PATH=/tmp/x.json WSA2_CAPTURES_PATH=/tmp/c.json python3 ...
  ```
  These vars are read at `wayaudo2.py:333-334` (`_SETTINGS_PATH`, `_CAPTURES_PATH`).
- A full `MainWindow` segfaults under `offscreen` (native window code, pre-existing limitation). Test isolated mechanisms (reparenting, engine subscribe, signal wiring) rather than instantiating the whole window. `python3 -c "import ast; ast.parse(open('wayaudo2.py').read())"` is the quick syntax gate.

### Self-verification — verify your own work without asking the user for screenshots
The user does NOT want to screenshot the app every time. Verify what you can yourself:

1. **`python3 selfcheck.py`** — headless harness. Imports the module (structure gate), renders key widgets (`OctaveCanvas`, `FFTCanvas`, `TFIRCanvas`, `ShowModeWindow`, splash, `draw_info_box`, …) to PNGs in `/tmp/wsa2_selfcheck/`, and runs logic asserts (`fmt_delay`, `ms_to_m`, smoothing). **Then `Read` the PNGs to eyeball the result** — this is how you confirm a visual change really happened. `python3 selfcheck.py <substr>` runs a subset. **When you add/change a renderable widget, add a `check()` for it** so it's covered + regression-guarded.
2. **Individual widget render** — anything that's a `QWidget` (not the full `MainWindow`) can be instantiated offscreen, fed synthetic data, and `.grab()`-ed to a PNG you then `Read`. This is the core trick; `selfcheck.py` just formalizes it.
3. **Logs — you read them directly; the user does NOT send anything.** For things that need the real app / live audio / hardware (which only the user can launch), the user just **runs the app and does the action** — then **you `Bash`/`Read` the session log yourself** (it's on this machine): newest of `~/Library/Logs/WSA2/wsa2_<ts>.log` (e.g. `ls -t ~/Library/Logs/WSA2/wsa2_*.log | head -1`). Grep `[DIAG]` for the structured heartbeat/snapshots. `_diag(tag, **kv)` (`wayaudo2.py` near the logging setup) writes greppable `[DIAG] tag k=v` lines; a ~10s heartbeat in `_render_frame` logs `view/run/spl/extra/show`. Uncaught exceptions already log full tracebacks (crash handler). Run the app with `WSA2_DEBUG=1` to also stream logs to the console. **Add `_diag(...)` calls at new state transitions** so behavior is verifiable from the log. Do NOT ask the user to send the log or a screenshot — read it yourself.

## Architecture (the parts that span multiple reads)

### Shared audio engine — one stream per device, many subscribers
`AudioEngine` (`:1826`) owns one `_DeviceStream` per physical device. Tabs call `engine.subscribe(device_idx, channels, sample_rate, force_latency=None)` → a `Subscription` (`:1707`) emitting two signals:
- **`chunk_ready`** — `{ch: array}` rolling `fft_size` buffer, throttled ~60fps (16ms). For spectrum/FFT consumers.
- **`raw_ready`** — continuous frames, no throttle. For sample-accurate integration (loudness, LEQ).

This is why two tabs can measure the same device simultaneously. **Exceptions that bypass the engine and stay isolated:** the signal generator output (`_sig_stream`) and the TF internal-loopback duplex (`TFDuplexThread`, `:8761`). Adapter classes `_EngineSyncSource` / `_EngineMultiSource` / `_EngineChannelSource` (`:1896`–`:2038`) wrap `subscribe` to present the legacy thread API (`start`/`frame_ready`/`chunk_ready`) that older tab code expects.

`force_latency='high'` re-opens the shared device stream at higher latency (used while TF runs, to keep duplex IO buffers aligned). Spectrum/Stereo alone stay low-latency.

### Producer/consumer render pattern (important for smooth painting)
Audio callbacks must not paint. The pattern is: the chunk handler computes results into a `_pending` field under a `QMutex`; a **fixed 30fps `QTimer` (`MainWindow._render_frame`, started at `:14103`)** pulls the latest `_pending` and pushes to canvases, dropping intermediate frames. Painting decoupled from callback jitter = no stutter. Any new live view must follow this (e.g. the TF-tab RTA uses its own `_rta_render_t` timer + `_rta_pending`; its `_on_rta_chunk` only stores, never paints).

### The three tabs
- **Spectrum** = `MainWindow` itself (`:14033`). FFT/octave/spectrogram canvases (`FFTCanvas` `:2123`, `OctaveCanvas` `:2588`, `SpectrogramCanvas` `:2966`). `_process_audio` (`:16484`) is the producer; `view_mode` selects which canvas is fed.
- **Transfer Function** = `TransferFunctionWindow` (`:9716`), instantiable as embedded tab or standalone window (`embedded=False`). Shared Reference + multiple Measurement cards (`_MeasCard` `:7904`); magnitude/phase/IR canvases.
- **Stereo Loudness** = `StereoLoudnessPage` (`:13653`) — vectorscope, loudness radar, LUFS via `LoudnessMeter`/`_KWeightFilter`.

Tabs can pop out into separate windows (`_TFPopoutWindow`/`_SpectrumPopoutWindow`/`_StereoPopoutWindow` near `:13980`) by **reparenting** the existing toolbar/body widgets (not rebuilding) — audio keeps running because the engine is shared. There is also a split "동시 보기" mode. See memory `project_smaart_view_layer_plan` before touching popout/split.

### Licensing
Ed25519 is the live scheme: public key `_LIC_PUBKEY` (`:108`) verifies; the private key is **not in the repo** (`.gitignore`). `verify_license` (`:168`) tries Ed25519 then falls back to legacy HMAC (`_LIC_SECRET`, 3 old keys only). Issue keys with `generate_license.py` (CLI) or `wsa2_license_tool.py` (GUI, keeps a ledger). Operational details and key rotation: `LICENSING.md`.

## Conventions

- **Styling via design tokens, not inline styles.** Theme accessor `T(key)` (`:494`); size tokens `FS_*`/`CF_*`, radius `RADIUS_*` (`:498`–`:507`); stylesheet helpers `ss_text`/`ss_input`/`ss_spin`/`ss_pill_btn` (`:1216`+). Match these when adding UI.
- **Capture curves are solid lines** (dashed was explicitly rejected); distinguish by color/width. Brand gradients are **static-cached only** — never render gradients live per frame (perf).
- **macOS specifics:** custom dark titlebar applied via `ctypes` (`_setup_macos_titlebar`); the app quits with `os._exit` to avoid a PyQt5 finalization SIGSEGV. Float-over-fullscreen popups use the FullScreenAuxiliary + addChildWindow pattern — do not use `setWindowState`/`setGeometry` for those.

## Project tracking & memory

- **`ISSUES.md` is the master todo/bug tracker** (todos, next-version `[v1.7]` items, docs, release). Check it first.
- Persistent cross-session context lives in Claude memory at `~/.claude/projects/-Users-yuncheollee-WSA2/memory/` (`MEMORY.md` index + `project_*.md` detail files). These hold code locations, past decisions, and verification checklists that aren't in the repo.
- Release policy: work accumulates on the current dev version (e.g. v1.6) — **do not bump/build/tag until the user explicitly says to build.**
- Git branch: development happens on **`develop`** (the GitHub default branch; renamed from `release/v1.0` on 2026-07-04). All versions since v1.0 accumulate on this one branch — the branch name is just a label and does not track `_APP_VERSION`. `main` is a separate stale branch.
