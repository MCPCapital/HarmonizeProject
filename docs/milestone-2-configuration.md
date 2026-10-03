# Milestone 2 configuration and dependency boundary

## Scope and result

Milestone 2 adds an offline, typed TOML configuration boundary and preserves the
existing harmonize.py manual runtime unchanged. Configuration validation does
not enumerate bridges, make network requests, open capture devices, start Hue
Entertainment, or modify lights. Live area resolution belongs to Milestone 3.

The accepted Pi environment is Ubuntu on aarch64 with Python 3.12.3. Its Python
packages are represented by requirements.txt (direct dependencies) and
requirements.lock (the complete observed package set). The environment also
depends on system components that Python package metadata cannot reproduce:

- OpenCV 4.10.0 was built locally under /usr/local for Python 3.12 with
  GStreamer, FFmpeg, and V4L2 enabled. The virtual environment's cv2 path is a
  link to /usr/local/lib/python3.12/site-packages/cv2.
- GStreamer 1.24.2 and its runtime plugins are supplied by Ubuntu.
- OpenSSL 3.0.13 supplies the current script's DTLS command-line transport.

OpenCV stays an explicit system boundary because installing a generic wheel
could remove required GStreamer support. Milestone 3 must retain the existing
build or create and test an equivalent aarch64 build procedure before replacing
it.

## Reproduce the Python layer

Create a Python 3.12 virtual environment without Docker:

    python3.12 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.lock
    .venv/bin/python -m pip check

The lock file deliberately excludes pip itself and OpenCV. After exposing the
accepted system OpenCV build to the virtual environment, verify the boundary:

    .venv/bin/python -c 'import cv2; print(cv2.__version__)'
    .venv/bin/python -c 'import cv2; print("GStreamer: YES" in cv2.getBuildInformation())'

Do not install or change CUPS or Docker while creating this environment.
Printing is supplied by the production airprint container; host CUPS remains
inactive and disabled by design.

## Configure Harmonize

Copy harmonize.example.toml to the ignored local path harmonize.toml. The
example contains ordinary settings only. In particular:

    [hue]
    entertainment_area = "TV area"
    credentials_file = "client.json"

The area name is case-sensitive configuration. Unattended validation requires a
non-empty value and never prompts. Manual compatibility mode permits the value
to be absent so the existing interactive selection can remain available during
the Milestone 3 integration. The current harmonize.py continues to provide its
legacy interactive operation throughout Milestone 2.

Other tables select the capture device/backend, desired-state provider,
Ambilight timing and sampling settings, post-stream restore/off behavior, and
logging level. Unknown keys are rejected to catch spelling errors. The only
provider accepted in this milestone is local; later milestones will implement
the command interface and additional provider adapters.

Validate the example entirely offline:

    python3.12 tools/validate_config.py \
      --config harmonize.example.toml \
      --mode unattended

This proves the configured name is syntactically valid. It does not prove that
the area exists. Milestone 3 will query Hue read-only, require exactly one exact
match for "TV area", and fail before streaming if the result is missing or
ambiguous.

## Preserve and protect Hue credentials

client.json remains the compatible credential format with required non-empty
username and clientkey fields. It stays separate from TOML, ignored by Git, and
its values are never included in validation output.

Unattended mode rejects a symlink, a non-regular file, or any group/other
permission bits. The existing file was observed at mode 0664; Milestone 2 did
not change it. Before unattended startup, the owner should make the reversible
permission correction:

    chmod 600 client.json

Manual validation accepts the existing permission mode with a warning, which
preserves legacy use:

    python3.12 tools/validate_config.py \
      --config harmonize.example.toml \
      --mode manual \
      --check-credentials

Once permissions are restricted, use --mode unattended --check-credentials.
Both checks are local and make no bridge request.

## Validation record

On 2026-09-13, the locked packages installed successfully into a fresh Python
3.12 virtual environment on this aarch64 Pi. pip check reported no broken
requirements, all direct imports succeeded, and the offline configuration and
credential test suite passed. The tracked unattended example also validated
with the exact configured area name "TV area".

The existing credential file was read only for shape and permission validation.
No value was printed. No Hue endpoint, capture device, CUPS unit, Docker
package, network, permission, or container was changed.

## Rollback

The prior accepted runtime remains at commit
de269dd388ddcc0d752105802b7933737fa7ec99. Milestone 2 installs no service or
system package and changes no existing credential. Rollback consists of
returning to that commit and continuing to run harmonize.py with the existing
environment and client.json. A locally copied harmonize.toml can be removed
without affecting legacy operation.
