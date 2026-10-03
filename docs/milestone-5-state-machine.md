# Milestone 5 desired-state controller

## Runtime and commands

Harmonize now starts as a persistent control daemon in `IDLE`. Startup resolves
`TV area` read-only and creates the local command socket, but capture, Hue
Entertainment, and DTLS remain closed until desired state becomes enabled.

Start the foreground daemon:

    /home/pi/harmonize_env/bin/python harmonize.py \
      --config harmonize.toml

Use the separate client from another shell:

    /home/pi/harmonize_env/bin/python tools/harmonize_control.py \
      ON --config harmonize.toml
    /home/pi/harmonize_env/bin/python tools/harmonize_control.py \
      STATUS --config harmonize.toml
    /home/pi/harmonize_env/bin/python tools/harmonize_control.py \
      OFF --config harmonize.toml

ON waits until actual state is `STREAMING`; OFF waits until cleanup reaches
`IDLE`. The default wait is 30 seconds and can be changed with
`--wait-seconds` or bypassed with `--no-wait`. STATUS returns immediately.

The local API is an owner-only Unix socket at the configured
`control.socket_path`, mode `0600`. There is no TCP listener. Filesystem access
is the authentication boundary for this milestone. The daemon refuses to
replace a non-socket path or a socket used by another daemon, removes a stale
socket safely, and unlinks its own socket during shutdown.

## State and ownership

A provider publishes a normalized value containing enabled/disabled, source,
and monotonic timestamp plus a separate policy. The supervisor owns
arbitration and creates a fresh Milestone 4 lifecycle controller for every ON
cycle. The lifecycle controller continues to own capture, exact-area Hue
requests, DTLS, streaming, and cleanup. Provider code has no access to those
resources.

Normal operation is:

    IDLE -> STARTING -> STREAMING -> STOPPING -> IDLE

Controller recovery also exposes `ERROR` and `RECOVERING`. A controller failure
runs its scoped cleanup, then the supervisor retries with exponential delay up
to `control.recovery_attempts`. Exhaustion leaves the daemon responsive in
`ERROR`, with desired state still visible. A new explicit ON retries; OFF clears
the request and returns to fail-safe `IDLE`. A STARTING controller is bounded by
the configured startup timeout.

STATUS and the atomic health file expose:

- desired enabled state, source, and age
- actual lifecycle state
- current transition endpoints, reason, and elapsed time
- daemon liveness/readiness
- recovery attempt and current error

Every desired-state resolution and lifecycle transition is a structured JSON
log event. Transition logs include the previous state, next state, reason,
source, desired value, and elapsed time.

## Arbitration policy

Provider policies are resolved by highest numeric priority. Equal priorities
use the newest timestamp, then a stable source-name tie break. The explicit
local provider has priority 100 and is immediate. A local command persists for
the daemon lifetime until another local command replaces it; state is not
persisted across process restarts, so restart begins fail-safe disabled.

Future automatic providers should use a lower priority and the ordinary
configuration values for stale expiry, ON debounce, and OFF grace. Automatic
changes must remain stable for the configured interval before taking effect.
A provider that stops refreshing its state is discarded after its stale
interval. If no valid provider remains, desired state becomes disabled from
source `fail_safe` and active streaming is cleaned up.

No automatic provider is enabled in Milestone 5. HDMI-CEC and Homebridge are
not imported or required, and capture activity is not used as a power signal.
A future adapter only publishes normalized state; it does not change the
supervisor or resource lifecycle.

## Validation record

Validation on 2026-09-13 produced 69 passing offline tests. Milestone 5 coverage
includes fake-clock filtering, provider precedence, stale fail-safe behavior,
automatic debounce and grace, interchangeable fake providers, a fake Hue
controller, repeated state cycles, bounded STARTING, failure recovery and
exhaustion, socket permissions and collision safety, command parsing, and
completed-state waits. All Milestone 3 and 4 characterization and reliability
tests continue to pass.

A real initial-state test started the daemon with `TV area` inactive. STATUS
reported desired disabled from `fail_safe`, actual `IDLE`, alive and ready, with
no error. The socket was mode `0600`. Explicit OFF changed the source to `local`
and remained IDLE. SIGINT exited zero and removed the socket.

Three approved live cycles then ran against only the configured two-channel
`TV area`. Every ON completed at STREAMING with desired enabled/source local,
and every streaming STATUS agreed. Every OFF passed through STOPPING and
completed at IDLE with no error while the daemon stayed alive. Read-only Hue
queries after cleanup reported the area inactive. Final SIGINT exited zero and
left no active Entertainment session.

OFF currently performs the accepted pre-Milestone-6 Entertainment cleanup. It
does not claim to restore or turn off normal light state; that behavior remains
explicitly scoped to Milestone 6.

## Rollback

The accepted pre-Milestone-5 rollback point is
`13670ff705bfd83deb75796aca1ca5ab892a76d3` on `modernize`. Milestone 5 installs
no package, service, network listener, or Homebridge component. Repository
rollback to that commit restores the Milestone 4 run-until-signal behavior.
