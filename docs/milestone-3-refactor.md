# Milestone 3 refactor and validation

## Architecture

harmonize.py is now a thin entry point. Runtime work is divided into components
with one resource owner:

| Component | Responsibility and ownership |
| --- | --- |
| harmonize_core.cli | Legacy-compatible arguments, optional TOML configuration, deterministic/manual selection, and operator commands |
| harmonize_core.hue | One bridge HTTP session, read-only area queries, exact name/group resolution, and explicit start/stop actions |
| harmonize_core.capture | One OpenCV capture handle and source-preserving reset requests |
| harmonize_core.analysis | Legacy x/z position mapping, edge sampling, HSV brightness behavior, and RGB calculation for one complete frame |
| harmonize_core.protocol | Deterministic binary HueStream header, channel, and repeated-byte RGB encoding |
| harmonize_core.transport | One binary-mode OpenSSL DTLS subprocess with handshake readiness and bounded close |
| harmonize_core.controller | Single worker owning capture reads, analysis, packet sends, lifecycle state, and ordered cleanup |

The controller opens capture and reads a complete first frame before requesting
Hue streaming. It then starts Hue Entertainment, waits for an observable DTLS
handshake, and enters STREAMING. No frame or color globals are shared. Operator
reset requests are events applied by the capture-owning worker between reads.
If the source dimensions change after reset, the sampling bounds are rebuilt.

Cleanup closes DTLS, releases capture, and requests Hue stop. Once any start
request is attempted, a stop request is required even when the start response
is lost or malformed. Cleanup continues if one release step fails.

## Area selection and CLI compatibility

The version 2.4.2 flags remain accepted: -v, -g, -b, -i, -s, -w, -f, -l, and
-a. Manual mode retains legacy group selection and interactive selection when
no area is configured. A configured exact name takes precedence.

The new command form for deterministic selection is:

    ./harmonize.py --config harmonize.toml --unattended

Unattended configuration requires hue.entertainment_area and never asks for an
area. Read-only startup validation can exercise the same selection path without
capture or streaming:

    ./harmonize.py +      --config harmonize.example.toml +      --unattended +      --check-area

Two compatibility differences are intentional and need review with the
milestone:

- Fixed startup sleeps were replaced by capture/DTLS readiness. The legacy -w
  value now bounds how long the interactive CLI initially waits for controller
  readiness; it no longer delays startup by a fixed duration.
- Automatic bridge registration and the cloud discovery fallback were removed
  from the runtime path. Existing client.json operation is preserved.
  Registration should become an explicit tool rather than an implicit startup
  side effect. The legacy -b flag remains accepted, but deterministic bridge-ID
  use currently also requires -i.

The visual algorithm intentionally retains the prior behavior, including x/z
position mapping, RGB conversion, the HSV value adjustment, repeated-byte
16-bit channel values, sequence byte zero, and the single-light channel-one
optimization that bypasses brightness adjustment.

## Validation completed without controlling lights

On 2026-09-13:

- The accepted Milestone 2 commit ee4bbc0 passed before refactoring.
- Forty offline tests passed in /home/pi/harmonize_env.
- Exact, missing, case-mismatched, and duplicate area-name behavior passed.
- Deterministic packet bytes, mapping, brightness, single-light behavior,
  capture source reset, transport byte writes, and partial-startup cleanup
  passed.
- A live read-only mDNS query found one physical Hue bridge advertising one
  IPv4 and three IPv6 addresses. Discovery now treats those addresses as one
  bridge and selects its IPv4 address.
- A live read-only query resolved exactly one area named "TV area" with two
  channels and reported Entertainment status inactive. A reserved unknown name
  failed with an actionable message using the same response. No Entertainment
  action was sent.
- The refactored application passed --unattended --check-area without a prompt
  and resolved "TV area" as legacy group 200.
- The combined preflight captured one 720x480 frame, analyzed both configured
  channels, and built one unsent 66-byte HueStream packet. It did not start
  Entertainment or DTLS.
- client.json validated at mode 0600. Docker remained active and host CUPS
  remained intentionally inactive.

Expected OpenCV GStreamer warnings reported that video position and buffer-size
properties are unsupported by this live source. Frame capture itself succeeded.

## Active validation completed

After explicit operator approval on 2026-09-13, the refactored CLI started the
configured TV area using the current capture. The OpenSSL handshake reached
observable readiness, and a concurrent read-only bridge query reported
Entertainment status active. The first run exposed an input-loop race in which
q requested shutdown correctly but the CLI displayed another prompt before the
worker finished. Cleanup still succeeded and the bridge reported inactive.

The prompt race was corrected and the 41-test offline suite passed. The same
approved active test was repeated. The bridge again reported active during the
binary stream; one q exited with status zero; and the immediate read-only query
reported inactive. No fallback stop request was needed. Only the exactly
resolved two-channel TV area was passed to the start, packet, and stop paths.

Milestone 3 does not implement exact pre-stream light-state restoration; that is
Milestone 6. The stop action released Entertainment control. The physical light
appearance cannot be measured from the Pi, and lights can retain their final
streamed color until the operator selects another Hue scene.

## Rollback

The pre-refactor rollback point is accepted commit
ee4bbc076c4c7f2dc89ecac615fbc32215b8d6ff on modernize. No system package,
service, Docker workload, CUPS state, or tracked credential is changed by this
refactor.
