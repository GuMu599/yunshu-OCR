# WorkBuddy Portable Runtime Bootstrap Design

## Goal

Remove the WorkBuddy skill package's dependency on the packaging machine's absolute
Yunshu-OCR repository path. A user should be able to download the WorkBuddy ZIP,
upload it on Windows, macOS, or Linux, and let the skill prepare a verified local
runtime on first use. Later PDF conversion and page verification must work offline.

This change preserves the existing product contract:

- the user continues to work with the original PDF;
- the Agent reads the bound Markdown first;
- uncertain or conflicting content is checked against the corresponding PDF page;
- PDF conversion, OCR, Markdown generation, and page rendering do not call an LLM or
  consume LLM Token quota;
- WorkBuddy's later reading and answer generation may still consume platform quota.

## Accepted Approach

Use a lightweight Skill plus a managed runtime bootstrap.

The WorkBuddy ZIP contains only its instructions, metadata, and portable launcher.
The launcher downloads a fixed source release and fixed model release on first use,
verifies both with SHA-256, creates an isolated virtual environment, and stores the
result in the operating system's standard user cache. It then launches the existing
`tools/pdf-reading/pdf2md.py` helper with the managed environment.

This is preferred over embedding the runtime in the Skill ZIP because it keeps the
upload small and avoids WorkBuddy file-count or file-type restrictions. It is also
preferred over shipping three standalone native applications because the latter adds
substantial build, signing, dependency, and release maintenance before the core path
has been validated on all three operating systems.

The result is portable and self-preparing, but it is not a dependency-free single
binary. First use requires Python 3.10 or newer, network access, sufficient disk space,
and permission to create a user-local cache and virtual environment.

## Fixed Release Inputs

The bootstrap uses immutable release coordinates embedded in the launcher:

| Input | URL | Size | SHA-256 |
|---|---|---:|---|
| Source | `https://github.com/GuMu599/yunshu-OCR/releases/download/v1.0.0/yunshu-OCR-v1.0.0-source.zip` | 412019 bytes | `4f47c511fe771e80ddecebaf075a00d236ae5daff356290095533402850873a7` |
| Models | `https://github.com/GuMu599/yunshu-OCR/releases/download/models-v1/pdf2md-models-v1.zip` | 185346805 bytes | `daa85d380551a93f0464950181c3bc29ab16525a55b3a6664108183aa49c9fb0` |

Downloads use a size limit, stream to a temporary file, and are published only after
the expected byte count and SHA-256 match. ZIP extraction rejects absolute paths,
parent traversal, symlinks, and undeclared layout. A failed or interrupted install
must not replace a previously usable runtime.

The repository's `models/models.lock.json` release coordinates are updated from the
obsolete `cancelGuMu/yunshu-OCR` location to `GuMu599/yunshu-OCR`. The bootstrap also
passes the fixed model URL explicitly so the immutable v1.0.0 source archive remains
usable even if its embedded manifest contains the old repository name.

## Package Layout

The generated artifact becomes:

```text
dist/yunshu-ocr-workbuddy.zip
├── SKILL.md
├── manifest.yaml
└── scripts/
    └── yunshu_pdf.py
```

The package must not contain:

- `references/yunshu-ocr-root.txt`;
- `.yunshu-ocr-root` or any other hidden marker;
- a drive-letter, UNC, home-directory, or repository absolute path;
- model files, virtual environments, caches, or generated PDF output.

`python skills/install.py workbuddy [--dest ...] [--force]` remains the packaging
interface. Its JSON output no longer reports or asks the user to preserve the local
repository path. It reports only the artifact and upload instruction.

## Runtime Location and Resolution

The shared launcher resolves the runtime in this order:

1. `YUNSHU_OCR_ROOT`, when explicitly set and valid;
2. a valid legacy repository marker, for existing Codex, Claude Code, or universal
   installations created by earlier versions;
3. a parent checkout containing `tools/pdf-reading/pdf2md.py`;
4. the managed runtime cache, installing it when absent.

An explicitly set but invalid `YUNSHU_OCR_ROOT` is an error. The launcher must not
silently ignore a user's override and download another copy.

The managed cache root is:

| Platform | Cache root |
|---|---|
| Windows | `%LOCALAPPDATA%/yunshu-ocr` |
| macOS | `~/Library/Caches/yunshu-ocr` |
| Linux/Unix | `$XDG_CACHE_HOME/yunshu-ocr`, otherwise `~/.cache/yunshu-ocr` |

Versioned contents are isolated so future upgrades do not mutate an older working
installation:

```text
<cache>/
├── downloads/
├── logs/
├── runtime/v1.0.0/
│   ├── pdf2md/
│   ├── models/
│   └── tools/pdf-reading/pdf2md.py
├── venv/v1.0.0-py<major><minor>/
└── state/v1.0.0-py<major><minor>.json
```

The state file records the source and model release identifiers and hashes, selected
Python executable/version, dependency mode, successful model verification, and
completion time. Cache paths are computed at runtime; no generated-machine path is
stored in the Skill package.

## Bootstrap and Execution Flow

For every existing command (`ensure`, `locate`, `render`, or `render-page`) the
launcher follows one flow:

1. Validate Python 3.10 or newer and resolve a repository or managed runtime.
2. If the managed runtime is complete, execute immediately with its virtual
   environment's Python.
3. If it is absent, acquire a version-specific install lock and recheck because
   another process may have completed installation.
4. Download and verify the fixed source archive, safely extract it into a staging
   directory, and validate the expected helper and requirement files.
5. Create a versioned virtual environment.
6. Upgrade packaging tools inside that environment and install dependencies:
   - use `requirements-lock.txt` only on the verified Windows amd64/Python 3.13
     combination;
   - use `requirements.txt` on other supported combinations until per-platform lock
     files are produced.
7. Run `python -m pdf2md.models install --source-url <fixed-model-url>` and then
   `python -m pdf2md.models verify` inside the staged runtime.
8. Write the completion state and atomically publish the staged runtime.
9. Execute the originally requested PDF command.

Only first-time setup and an explicit repair or future version change require network
access. Once the state, helper, virtual environment, and model files are valid, normal
PDF processing does not perform a network request.

The install lock has a bounded wait and a clear timeout error. Temporary downloads and
staging directories may be removed after failure; a completed versioned runtime is
never deleted merely because a later repair attempt fails.

## Agent-Facing Behavior

The WorkBuddy `SKILL.md` changes its setup guidance:

- do not tell the user to clone, keep, move, or regenerate from an external repository;
- explain that first use downloads a verified local runtime and may take several
  minutes because the model package is about 185 MB;
- explain that later conversion is offline and reuses the local cache;
- on setup failure, surface the launcher's exact stage and log path;
- retain the existing `ensure -> Markdown -> locate -> render -> render-page ->
  adjacent page` verification chain;
- retain the original PDF as authoritative when Markdown and PDF conflict.

The human `README.md` and AI-facing `AI_README.md` must describe the same behavior and
the same boundaries. They must not claim that all three operating systems have been
fully runtime-verified until real tests exist.

## Errors and Recovery

The launcher returns machine-readable JSON to stderr for bootstrap failures, including
`ok: false`, a stable error code, the failed stage, a concise message, and the log path
when one exists.

Required failure classes are:

- `python_unsupported`: Python is older than 3.10;
- `cache_unavailable`: the user cache cannot be created or written;
- `download_failed`: network or HTTP failure;
- `archive_integrity`: size or SHA-256 mismatch;
- `archive_unsafe`: invalid ZIP member or layout;
- `venv_failed`: virtual environment creation failed;
- `dependency_failed`: dependency installation failed;
- `model_failed`: model installation or verification failed;
- `install_busy`: another installer did not finish within the bounded wait;
- `runtime_invalid`: a completed cache no longer contains required files;
- `override_invalid`: `YUNSHU_OCR_ROOT` is set but invalid.

Retrying the same PDF command retries an incomplete first-time installation. Advanced
users can set `YUNSHU_OCR_ROOT` to a valid checkout to bypass managed installation.
No broad filesystem permission is requested; WorkBuddy needs access only to the Skill,
the selected PDF, its output directory, and the user-local cache.

## Code Boundaries

`skills/shared/yunshu_pdf.py` remains the single launcher source copied into all four
Skill variants. It owns runtime discovery, cache selection, bootstrap orchestration,
and subprocess dispatch. Small focused functions separate path policy, archive
verification, safe extraction, environment creation, state validation, and error
formatting so they can be tested without downloading production assets.

`skills/install.py` owns only Skill installation and WorkBuddy ZIP assembly. It must
not perform runtime or model installation while packaging.

The existing `pdf2md.models` module remains authoritative for model archive extraction,
per-file verification, publishing, and rollback. The launcher delegates model setup to
that module rather than reimplementing its model rules.

## Verification Strategy

Implementation follows tests first. The focused test suite must cover:

- Windows, macOS, Linux/XDG cache path selection through patched platform/environment
  inputs;
- explicit override, legacy marker, parent checkout, and managed cache resolution
  order;
- fixed source/model release URL, size, and SHA-256 constants;
- source archive size/hash rejection and safe-extraction traversal rejection;
- staged installation, state creation, offline reuse, interrupted setup, retry, and
  invalid-cache behavior with local fixtures and mocked subprocesses;
- dependency selection: the exact lock only for Windows amd64/Python 3.13 and portable
  requirements elsewhere;
- WorkBuddy ZIP exact layout with no marker, hidden file, or absolute machine path;
- installer JSON and README/AI_README guidance;
- unchanged PDF/Markdown binding and page fallback regression tests.

A generated production ZIP is inspected after the tests. Its member names and text
contents are scanned for the current drive path, repository path, username, hidden
files, and the removed root marker.

Current completion claims are intentionally bounded:

- Windows behavior is verified with the real repository and local test environment.
- macOS and Linux path/bootstrap policy is unit-tested and should be exercised in CI.
- Until a real first-use install and PDF conversion pass on macOS and Linux, public
  documentation says “cross-platform path compatible” rather than “verified on all
  three platforms.”

## Out of Scope

- An installation questionnaire or accuracy selector.
- Lower-accuracy conversion modes.
- Bundling the 185 MB model archive in the Skill ZIP.
- Shipping native signed applications or an embedded Python interpreter.
- Automatic Python installation when Python 3.10+ is absent.
- Claiming that Agent answer generation itself is Token-free.
- Changing the PDF/Markdown binding, page-number semantics, or PDF-authoritative
  fallback rules.
