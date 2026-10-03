# Harmonize project handoff

Updated 2026-09-15 after acceptance and closeout of Milestone 9.
`PROJECT.md`, milestone documents, tests, and Git history remain the
authoritative specification.

## Accepted state

- Milestones 0 through 9 are complete and accepted. Do not reopen them without
  an explicit owner request.
- Milestone 9 was completed on `m9-ambilight-quality`. The configurable
  performance implementation is commit `fff9ba1`; the closeout commit is the
  branch head recorded after this handoff update.
- Commit `7cac8ed` moved Hue status queries off the streaming-critical packet
  path while preserving single-flight session-loss detection and recovery.
- The complete offline suite passed 129 tests before deployment. The closeout
  is documentation-only, so the suite was not rerun.
- `master` has not been merged or changed.

## Public behavior and configuration

The backward-compatible public defaults remain:

- `ambilight.color_processing_mode = "legacy_hsv"`
- `ambilight.update_interval_seconds = 0.050`

`legacy_hsv` preserves the released v3.0.0 BGR-to-HSV-to-BGR output. The
`direct_rgb` mode is an explicit performance opt-in and is valid only when
`brightness_adjustment = 0`. The generic example retains the public defaults.

Local STATUS includes a non-secret `performance` object. Trusted-LAN HTTP
`/?harmonize=status` returns only current state plus
`color_processing_mode`, `update_interval_seconds`, and
`brightness_adjustment`; it does not expose credentials, bridge details,
filesystem paths, or other internal configuration.

## Installed appliance state

The owner Pi intentionally remains deployed from commit `fff9ba1` with:

- `color_processing_mode = "direct_rgb"`
- `update_interval_seconds = 0.033`
- `brightness_adjustment = 0`

Do not replace those personal settings with the public defaults. The evening
soak looked good, with no noticeable color, brightness, or light-behavior
problems. At closeout both `harmonize.service` and `harmonize-http.service`
were active/running with zero restarts. Runtime STATUS reported the settings
above; the current lifecycle state was IDLE after the owner observation.

Rollback snapshots from the deployment remain at
`/opt/harmonize/app.pre-fff9ba1` and
`/etc/harmonize/harmonize.toml.pre-fff9ba1`. Configuration-only rollback of
the performance options is `legacy_hsv` plus 0.050 seconds followed by a core
service restart.

The services run as the locked `harmonize` identity. Application and virtual
environment files are under `/opt/harmonize`, configuration is under
`/etc/harmonize`, private runtime state is under `/run/harmonize`, and
persistent light state is under `/var/lib/harmonize`. The stable capture path
remains the WARRKY `/dev/v4l/by-id` device. The trusted-LAN HTTP adapter still
listens on TCP port 8765 and maps only exact ON, OFF, and STATUS requests to the
owner-only Unix socket.

## Milestone 9 conclusions

- Instrumentation established the 640x480 YUYV, approximately 30 FPS capture
  baseline and measured frame age, analysis cost, update cadence, and packet
  gaps without per-frame logging.
- Moving the ten-second Hue HTTPS status query to an asynchronous single-flight
  monitor removed the recurring packet-gap tail. Recovery semantics remain
  intact and slow status requests no longer block packet sends.
- The 33 ms pacing trial increased effective update rate and remained stable.
  It is configurable and accepted for this Pi, while 50 ms remains the public
  compatibility default.
- Native V4L2 and OpenCV timestamp measurements found no meaningful
  steady-state stale-frame queue. Reducing the effective four buffers offered
  no normal-path benefit, so capture behavior was left unchanged.
- The brightness-zero `direct_rgb` path materially reduces analysis time but is
  not byte-for-byte output-equivalent to the legacy HSV round trip. It remains
  an explicit opt-in restricted to zero brightness adjustment. Controlled live
  viewing and the evening soak found no noticeable degradation.
- Smoothing, gamma, saturation, black-bar handling, dark-scene logic,
  scene-change processing, and other visual redesigns were not pursued merely
  to extend the milestone. They remain deferred unless future evidence and a
  separate owner request justify them.

Detailed measurements, experiment history, defaults, risks, and rollback are
in `docs/milestone-9-optimization.md`. Runtime configuration and HTTP status
reporting are documented in `README.md`, `harmonize.example.toml`, and
`docs/milestone-8-http.md`.

## Safety and scope

- `client.json` contains Hue credentials. Never display, log, diagnose, or
  commit its contents.
- Resolve and control only the configured Entertainment area named exactly
  `TV area`; preserve bounded cleanup and explicit OFF behavior.
- Do not reset, clean, stash, discard, or overwrite user work during takeover.
- Docker, AirPrint, and host CUPS remain outside routine Harmonize work unless
  a separately authorized milestone explicitly requires their validation.
- Do not resume Milestone 9 optimization without an explicit owner request.

## What the next agent must do first

Verify the branch and clean worktree, read this file, `PROJECT.md`, and the
relevant milestone documents, then confirm both services and STATUS without
exposing credentials. Milestone 9 is complete; the roadmap proceeds to the
separately authorized Milestone 10 boundary. Do not merge this topic branch to
`master` without explicit review and authorization.

### Status

Milestone 9 is complete and accepted on `m9-ambilight-quality` on 2026-09-15.
The public defaults remain legacy HSV and 50 ms. The owner Pi retains direct
RGB, 33 ms, and zero brightness adjustment. No additional visual-processing
optimization is pending as part of this milestone.
