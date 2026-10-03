# Harmonize project handoff

Updated 2026-09-13 after acceptance of Milestone 8. `PROJECT.md`, milestone
documents, tests, and Git history remain the authoritative specification.

## Accepted state

- Milestones 0 through 8 are complete and accepted. Do not reopen them without
  an explicit owner request.
- Accepted Milestone 7 implementation: `9842b8c` (`Deploy Harmonize as a
  systemd appliance`).
- All 97 offline tests and `systemd-analyze verify` passed for Milestone 7.
- Milestone 7 rollback tooling and instructions exist. The owner accepted the
  milestone with the uninstall/reinstall execution intentionally skipped.
- Milestone 8 was completed and accepted on `m8-http-interface` using
  the revised trusted-LAN HTTP requirements. The adapter accepts only the
  exact fixed ON/OFF/STATUS request targets on TCP port 8765.
- 11 focused Milestone 8 tests and the four existing local-control tests
  passed; Bash syntax and systemd unit verification also passed.
- Both services finished installed, enabled, active, and running with zero
  restarts. Final HTTP state was IDLE, both `TV area` lights were off, and a
  read-only Hue query reported the exact two-channel area inactive.

## Installed appliance state

At handoff, `harmonize.service` is loaded, enabled, active, and running. It
starts ready in IDLE and waits for an explicit ON request. The unit and its
operator/rollback instructions are in `deploy/harmonize.service` and
`docs/milestone-7-systemd.md`.

`harmonize-http.service` is also installed, enabled, active, and listening on
all IPv4 interfaces on TCP port 8765. It runs under the same locked identity
but its systemd sandbox hides configuration, credentials, and persistent
state. Operator and rollback instructions are in `docs/milestone-8-http.md`.

The service runs as the locked account `harmonize` (UID 997, primary GID 985,
shell `/usr/sbin/nologin`) with only the supplementary `video` group. Relevant
paths are:

- root-owned application and virtual environment under `/opt/harmonize`
- configuration under `/etc/harmonize` (`0750 root:harmonize`)
- private runtime directory `/run/harmonize` (`0700 harmonize:harmonize`)
- private state directory `/var/lib/harmonize` (`0700 harmonize:harmonize`)
- stable WARKKY capture path configured under `/dev/v4l/by-id`

The local control provider accepts `ON`, `OFF`, and `STATUS` through
`/run/harmonize/harmonize.sock`. The socket is owner-only (`0600`) inside the
private runtime directory. `tools/harmonize_control.py` is the existing client.
The desired-state/provider boundary remains independent of any automation
system. Explicit OFF and service stop turn every light in exactly `TV area`
off; exceptional cleanup may restore pre-session state as documented.

## Milestone 8 boundary

Milestone 8 is **Trusted-LAN HTTP Control**, defined in `PROJECT.md` by the
owner's revised requirements.

The adapter is a separate small HTTP service on IPv4 TCP port 8765. It accepts
only exact GET targets for `/?harmonize=on`, `/?harmonize=off`, and
`/?harmonize=status`; all missing, unsupported, duplicate, or extra request
input is rejected.

Fixed request values map directly to the existing owner-only Unix-socket
client. Do not construct shell commands from request input, add another
desired-state provider, or expose configuration, credentials, or persistent
state.

The separate systemd unit runs as `harmonize` so it can reach the private
socket. Its filesystem sandbox hides `/etc/harmonize` and
`/var/lib/harmonize`. Authentication and TLS are intentionally absent; this
adapter is explicitly for the owner's trusted LAN.

Live validation confirmed local and external STATUS, ON to STREAMING with both
`TV area` lights following video, and OFF to IDLE with both lights powered
off. The final read-only Hue query reported Entertainment inactive and sent no
action request. Setup, diagnostics, failure behavior, results, and rollback
are documented in `docs/milestone-8-http.md`.

## Safety and scope

- `client.json` contains Hue credentials. Never display, log, copy into
  diagnostics, or commit it. The repository file is ignored and mode `0600`;
  the installed credential is also private. Validate metadata only.
- Resolve and control only the configured Entertainment area named exactly
  `TV area`. Preserve bounded cleanup and leave Entertainment inactive after
  every live test.
- Do not reset, clean, stash, discard, or overwrite user work during takeover.
- Docker, AirPrint, and host CUPS are out of scope. Do not inspect, test,
  validate, modify, or report on them for Milestone 8.
- Do not begin Milestone 9 visual-quality work.

## What the next agent must do first

Before making any change, read this file, `PROJECT.md`,
`docs/milestone-8-http.md`, and the relevant tests and Git history. Verify
the branch and worktree, and confirm both services without exposing
credentials.

Milestone 8 is complete, accepted, and live-validated on
`m8-http-interface`. Do not reopen it without an explicit owner request. Only
begin Milestone 9 after separate explicit owner authorization.
