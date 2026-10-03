# Milestone 4 headless lifecycle and reliability

## Runtime model

Harmonize now runs without terminal input. With a validated configuration it
starts one streaming session and continues until SIGTERM, SIGINT, a configured
diagnostic duration, or an unrecoverable error. Milestone 5 will add the
persistent IDLE controller and external ON/OFF/STATUS desired-state interface.

Start in the foreground:

    /home/pi/harmonize_env/bin/python harmonize.py \
      --config harmonize.toml

Stop by sending SIGTERM or SIGINT. Both signals enter one idempotent shutdown
coordinator. The controller closes DTLS, releases capture, sends stop to the
exact Entertainment area, updates health, and exits. Interactive area
selection, r/q commands, input(), and screen are no longer runtime
dependencies. The configured exact area or an explicit legacy group ID is
required.

The diagnostic duration option exercises the same shutdown path:

    /home/pi/harmonize_env/bin/python harmonize.py \
      --config harmonize.toml \
      --run-seconds 300

## Bounds and recovery

The example configuration defines explicit startup, shutdown, capture read,
capture backoff, transport retry, Hue status, and health intervals. Network
requests have a five-second timeout. DTLS handshake waits are five seconds.
The process-level shutdown bound is 15 seconds, containing shorter transport
and capture close bounds plus a final scoped Hue stop attempt.

Capture runs in a daemon worker that retains only the newest complete frame.
Failed reads release and reopen the original device index, file, or URL with
exponential backoff. A request to stop releases the OpenCV handle to unblock a
backend read and joins the worker within its component timeout.

The controller queries the exact configured area again immediately before
opening capture. Missing or duplicate exact names fail before Hue start.
During streaming it checks the area's status periodically. A dead DTLS child
or inactive Hue session enters RECOVERING. Recovery resolves the exact name
again, clears any stale owned session, starts that same area, establishes a
new binary DTLS process, and returns to STREAMING. Retries and backoff are
bounded; exhaustion exits with an actionable error and runs cleanup.

## Logs and health

Runtime logs are one compact JSON object per line with UTC timestamp, severity,
logger, event, message, and event fields. The configured username and client
key are redacted if they appear in any formatted field. OpenSSL arguments and
credential values are never logged.

The example writes run/harmonize-health.json atomically. It is ignored by Git
and contains no credentials. Fields include:

- state and state age
- ready and worker liveness
- configured area name
- ages of the newest captured frame and sent packet
- the current actionable error, if any

Ready is true only in STREAMING. A final IDLE or ERROR snapshot remains
available for systemd-adjacent diagnostics. The actual service unit and
watchdog integration remain Milestone 7.

The emergency cleanup command only resolves and stops the exactly configured
area:

    /home/pi/harmonize_env/bin/python tools/stop_entertainment.py \
      --config harmonize.toml

The command is an operational fail-safe, not the Milestone 5 Ambilight control
interface.

## Validation record

Validation occurred on 2026-09-13 against the configured two-channel "TV area":

- 51 offline tests passed, covering configuration bounds, exact area
  revalidation, every partial startup stage, idempotent stop, capture reopen,
  original device/file source retention, bounded capture close, transient and
  exhausted transport paths, binary packets, JSON logs, secret redaction, and
  atomic health output.
- Failure after capture readiness but before Hue start exited 2, released
  capture, and left the area inactive.
- Failure immediately after Hue start exited 2 and returned the area to
  inactive.
- Failure immediately after DTLS readiness exited 2, closed DTLS and capture,
  and returned the area to inactive.
- A real SIGTERM from STREAMING exited 0, reached IDLE, and completed Hue
  cleanup in about 1.1 seconds.
- A real SIGINT followed the same path, exited 0, reached IDLE, and completed
  Hue cleanup in about 1.1 seconds.
- Killing the real OpenSSL child was detected. After recovery was refined to
  clear stale bridge-side transport state, the final validation recovered on
  attempt 1 in about 1.3 seconds, returned to STREAMING, and later stopped
  cleanly.
- Externally stopping the active Hue session was detected. The controller
  restarted only the exact TV area on attempt 1, returned to STREAMING, and
  later stopped cleanly.
- A 300-second configured soak ran for 301.846 seconds including cleanup.
  Samples near 64, 126, 188, and 249 seconds all reported STREAMING, no error,
  and frame/packet ages below 0.05 seconds. It exited 0 through the duration
  shutdown path, wrote final IDLE/not-ready health, returned Hue to inactive,
  and left no Python or OpenSSL process.

After validation client.json remained mode 0600, docker.service remained active
and enabled, the containerized cupsd process remained present, and its localhost
port 631 endpoint returned HTTP 200. Host cups.service remained inactive and
disabled. The pi account cannot inspect the Docker API without sudo, so the
container health field was not available directly. No Docker container, Docker
configuration, printing service, package, or system service was changed.

Expected OpenCV warnings state that the live GStreamer source cannot report
video position and does not handle the requested buffer-size property. Frame
capture and the soak remained healthy despite those warnings.

## Rollback

The accepted pre-Milestone-4 rollback point is
b4474c2b827160047ddc3c37d7a670fe0b5b3c48 on modernize. Milestone 4 installs no
service or package. Repository rollback to that commit restores the interactive
Milestone 3 runtime. The ignored run/harmonize-health.json file may be removed
without affecting either version.
