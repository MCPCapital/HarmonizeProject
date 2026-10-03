# Harmonize Modernization Project

## Objective

Turn Harmonize into an appliance-like Ambilight service on this Raspberry Pi 5 running Ubuntu. The service should run unattended, detect whether the HDMI/video source is worth illuminating, start and stop Hue Entertainment streaming automatically, and restore the affected lights or turn them off afterward. Docker, the production airprint container, other Docker workloads, and host-level CUPS are outside the Harmonize project scope and must not be intentionally modified or disrupted.

This roadmap is the persistent tracker for that work. Implementation stops at every milestone boundary for review and explicit authorization.

## Current Baseline

- Hardware: Raspberry Pi 5, 64-bit ARM.
- Operating system: Ubuntu with Linux 6.8.0-1064-raspi observed during initial discovery.
- Python: 3.12.3 in both the system interpreter and /home/pi/harmonize_env.
- Computer vision: OpenCV 4.10.0 with GStreamer 1.24.2, FFmpeg, and V4L2 support; NumPy 1.26.4.
- Capture: /dev/video0 and /dev/video1 exist, along with Pi codec devices. User pi belongs to the video group. Milestone 1 found capture activity independent of TV power in the current splitter topology.
- Harmonize: upstream v2.4.2 at commit 51b4f52; no Harmonize process or systemd service was running during discovery.
- Hue: client.json exists only as a local ignored file in the current checkout. The current file is not tracked and its content hash does not match historical client.json blobs. Older upstream history did track files at that path before removing it, so history must never be treated as a safe place for credentials.
- Docker: docker.service was active and enabled at the Milestone 0 baseline. The existing airprint container is the production print service and printing is working normally. User pi cannot read the Docker API socket, so container health and other workloads require an authorized read-only validation method.
- Host CUPS: cups.service is inactive and disabled by design because printing is provided by airprint. Do not install, enable, start, reconfigure, or otherwise modify host-level CUPS.
- Deployment: the application currently depends on an interactive terminal or screen session and uses no native service unit.
- Architecture: harmonize.py combines discovery, Hue API access, capture, analysis, HueStream encoding, DTLS transport, threading, and interactive lifecycle control in one process.

## Project Principles

- Reliability before new features.
- Preserve a known-working state at every milestone.
- Make small, reviewable commits.
- Do not mix unrelated milestones in one change.
- Docker, the airprint container, and other Docker workloads are out of scope. Do not intentionally modify, restart, reconfigure, or disrupt them, and leave host-level CUPS untouched.
- Routine Docker and airprint health checks are not required at every milestone. Perform targeted read-only checks only when the work could reasonably affect Docker, printing, networking, system services, or shared appliance resources.
- Do not expose Hue credentials or other secrets.
- Prefer measurement and testing over assumptions about the hardware.
- Preserve working Harmonize behavior before trying to improve its visual output.
- Every milestone must have a clear rollback point.
- Stop at milestone boundaries for review before proceeding.

## Repository and Branch Strategy

- origin is the working fork: https://github.com/quexionjb/HarmonizeProject.git
- upstream is the source project: https://github.com/MCPCapital/HarmonizeProject.git
- Local master tracks origin/master and remains the clean fork baseline.
- modernize is the integration branch for this roadmap.
- Use focused topic branches such as m1-source-detection when a milestone benefits from isolated experiments or review.
- Merge or fast-forward only reviewed milestone work into modernize.
- Record the accepted commit SHA at each boundary and optionally add an annotated milestone tag.
- Pull upstream changes deliberately: fetch upstream, inspect the diff, test on a topic branch, and merge only after confirming that appliance behavior and local safety are preserved.
- Never commit client.json, environment files, private keys, local credential configuration, logs, PID files, sockets, virtual environments, or Python caches.

## Rollback Philosophy

Each milestone begins from a known commit and ends at a separately reviewable commit. Before installing files outside the repository, capture the current file, package, service, permissions, and workload state needed to reverse the operation. Repository rollback should normally mean checking out the previous accepted commit or reverting the milestone commit. System rollback must restore prior service units and configuration and reload systemd when needed. If the work could reasonably affect Docker or printing, rollback validation must also compare airprint and other Docker workloads with their recorded baselines. Host-level CUPS must remain untouched. Avoid irreversible migrations; credential and configuration changes require a documented recovery path.

## Target Controller Architecture

The future daemon separates desired state from lifecycle execution:

    Desired-state providers
      - local command/API
      - Homebridge/HomeKit adapter (future)
      - HDMI-CEC provider (future, unavailable in current wiring)
      - other automation providers
                |
                v
      normalized desired state
      enabled/disabled + source + timestamp
                |
                v
      Harmonize lifecycle controller
      IDLE -> STARTING -> STREAMING -> STOPPING -> IDLE
                |
                v
      capture, Hue session, DTLS, and light-state components

The lifecycle controller must not contain provider-specific logic. It accepts a desired state and exposes actual state, transition progress, and errors. The initial production control surface should support Ambilight ON, Ambilight OFF, and Ambilight STATUS through a small local API or command interface. Homebridge may later map that interface to an Ambilight switch without becoming a required Harmonize dependency.

Automatic providers must be optional and replaceable. Manual control must remain available when no reliable automatic TV-state signal exists. Provider arbitration, authentication, stale-command handling, and fail-safe behavior will be specified before implementation.

## Hue Integration Testing Policy

Hue validation proceeds in controlled stages:

- Milestone 2 uses offline configuration, schema, and credential-path tests. It defines the non-secret setting hue.entertainment_area = "TV area" but does not require a live bridge.
- Milestone 3 begins with a read-only live query that resolves the configured area name to exactly one bridge resource. A missing or ambiguous area must fail with an actionable error before Entertainment streaming starts.
- Milestone 3 then performs a separately approved manual start/stream/stop test against only the configured TV area after offline component tests pass.
- Milestone 4 exercises live partial-startup cleanup, DTLS/bridge recovery, signals, and bounded shutdown under an approved failure-injection procedure.
- Milestone 5 validates explicit ON/OFF/STATUS lifecycle cycles against the configured area after provider and state-machine tests pass offline.
- Milestone 6 performs controlled live light-state capture and restore/off tests with a recorded manual recovery procedure.
- Milestone 10 repeats end-to-end Hue validation, including missing-area, temporary network failure, service restart, cleanup, and post-Ambilight light state.

Every live-Hue test requires a stated scope, expected light behavior, cleanup path, and rollback point. Record the selected Entertainment area and pre/post state without logging credentials. Confirm streaming is stopped after each test, including failed tests. Do not contact or control the bridge merely to validate parsing or other behavior that can be tested offline.

# Milestones

## Milestone 0 — Repository and Safety Baseline

### Objective

Create a safe Git foundation and a Pi-specific modernization roadmap without changing Harmonize runtime behavior.

### Why it matters

Credentials and unrelated appliance workloads must be protected before experiments or refactoring begin. A recorded upstream baseline and small commits provide a dependable recovery point.

### Planned work

- [x] Verify origin, upstream, and master tracking.
- [x] Confirm the current local client.json is untracked and compare it safely with historical blobs.
- [x] Expand .gitignore for credentials, secret-bearing local configuration, virtual environments, caches, logs, and runtime files.
- [x] Create modernize from upstream v2.4.2 commit 51b4f52.
- [x] Commit repository housekeeping separately.
- [x] Record the observed Pi, capture, Python, OpenCV, airprint/Docker, and intentionally inactive host-CUPS baseline.
- [x] Create and commit this roadmap.
- [x] Push modernize to origin and record whether Git authentication permits it.

### Acceptance criteria

- [x] client.json remains present locally, unchanged, untracked, and ignored.
- [x] Local master tracks origin/master.
- [x] modernize contains a focused repository-housekeeping commit.
- [x] PROJECT.md contains objectives, work, acceptance criteria, risks, and status for every milestone.
- [x] No capture experiment, Hue request, service installation, host-CUPS change, or Docker change has occurred.
- [x] The push outcome is reported at the milestone review.

### Risks/unknowns

- Upstream history previously contained client.json files, so historical credentials may have existed even though the current credential is distinct.
- GitHub connector access and local Git command authentication are separate; local GitHub CLI authentication is now configured and modernize tracks origin/modernize.
- User pi cannot access the Docker socket directly. This does not create a recurring milestone check requirement; when relevant work could reasonably affect Docker or printing, use an authorized read-only validation method.
- Docker and the airprint container are protected external workloads, not Harmonize deliverables. Their configuration, operation, and maintenance remain outside this roadmap.
- Host CUPS is intentionally inactive and disabled; changing that state would conflict with the production airprint architecture.

### Status

Complete. The baseline commits are on origin/modernize.

## Milestone 1 — Determine Reliable TV/Source Activity Detection

### Objective

Determine whether the installed capture and HDMI topology exposes a reliable TV-power signal, evaluate direct HDMI-CEC, and define a safe explicit-control fallback when automatic detection is unavailable.

### Why it matters

The Roku can keep valid HDMI video flowing to the capture branch while the television is off. Appliance control must use actual desired state rather than infer TV power from brittle content assumptions.

### Planned work

- [x] Record USB identity, driver, V4L2 capabilities, supported formats, resolutions, and frame rates for /dev/video0.
- [x] Measure frame availability, read latency, timestamps, resolution, and device state with active Roku video.
- [x] Measure the capture device with the HDMI source off or in standby.
- [x] Document the independent Roku → splitter → TV/capture topology and TV-off behavior.
- [x] Stop content comparison once capture activity was proven independent of TV power.
- [x] Exclude Roku Home, screensaver, black-frame, image-hash, and other content-specific heuristics.
- [x] Inventory Pi HDMI connectors, CEC nodes, kernel support, physical addresses, and USB capture interfaces.
- [x] Determine whether the existing wiring exposes the television's CEC bus to the Pi.
- [x] Build a repeatable, non-recording capture diagnostic and record results.
- [x] Define explicit ON/OFF/STATUS control and a modular desired-state provider boundary as the production fallback.
- [x] Avoid Hue bridge contact and control throughout the milestone.

### Acceptance criteria

- [x] Active-source and source-standby capture behavior are repeatably characterized.
- [x] The TV-off/Roku-active topology limitation is documented without content-specific workarounds.
- [x] Capture activity is classified as unreliable for TV-power detection in this topology.
- [x] Direct HDMI-CEC is classified as unavailable with the current physical wiring.
- [x] The recommended explicit-control design is independent of capture and future trigger source.
- [x] No Hue state, host CUPS service, airprint container, or other Docker workload was changed.
- [x] Findings and the rollback commit are recorded before Milestone 2.

### Risks/unknowns

- A future Pi HDMI or dedicated CEC connection to the television would create a different topology requiring new validation.
- Homebridge may or may not already expose a reliable Roku/TV state suitable for later automation.
- The local control transport and provider arbitration rules remain Milestone 2 design decisions.
- /dev/video numbering stability still matters for capture operation even though capture no longer supplies TV power state.

### Status

Complete. Direct CEC and capture-based TV-power detection are unavailable in the current topology. Explicit modular desired-state control is recommended. Stop for review before Milestone 2.

## Milestone 2 — Establish Configuration and Dependency Boundaries

### Objective

Create a reproducible Python environment and a validated configuration layer while safely preserving existing Hue credentials.

### Why it matters

The current manually assembled environment and script-level options are difficult to reproduce, audit, deploy, and recover.

### Planned work

- [x] Inventory imports and system dependencies, including OpenCV/GStreamer and the OpenSSL DTLS requirement.
- [x] Choose and document a reproducible Python dependency specification compatible with aarch64 Ubuntu and Python 3.12.
- [x] Define ordinary non-secret configuration for capture selection, detection/provider settings, timings, logging, post-stream behavior, and hue.entertainment_area = "TV area"; the area value comes from configuration and is not a hard-coded application constant.
- [x] Require unattended mode to resolve one configured default Entertainment area deterministically, without input() or any other prompt.
- [x] Preserve legacy/manual interactive area selection when practical, while treating it as an explicit compatibility mode rather than a service fallback.
- [x] Keep credentials in a separate protected file with restrictive permissions.
- [x] Preserve direct use of the existing client.json with a reversible permission-hardening path.
- [x] Add validation with useful errors and no secret values in logs.
- [x] Document setup without requiring Docker.
- [x] Verify that installation steps leave host CUPS untouched and do not alter airprint or other Docker packages, services, networks, containers, or permissions.

### Acceptance criteria

- [x] The documented non-secret example includes hue.entertainment_area = "TV area" with exact capitalization.
- [x] Unattended configuration validation requires a non-empty default area and never prompts.
- [x] Offline tests cover missing configuration and legacy/manual fallback without contacting the bridge.
- [x] Live area existence and uniqueness validation is explicitly deferred to the approved Milestone 3 bridge test.
- [x] A fresh environment can be created from version-controlled instructions and dependency metadata.
- [x] Non-secret configuration has a documented example.
- [x] Secret storage is ignored, permission-checked, and compatible with current credentials.
- [x] Startup fails clearly on invalid configuration without contacting unintended bridges.
- [x] Existing manual Harmonize operation remains available unchanged.
- [x] Rollback restores the prior environment/configuration path.

### Risks/unknowns

- OpenCV 4.10.0 is a documented system boundary because the accepted local build supplies required GStreamer support; a generic wheel is not an equivalent replacement.
- Entertainment-area names can be renamed or duplicated on the bridge; live resolution must reject zero or multiple exact matches.
- A future stable Hue resource ID may be stored as an optional resolved value, but the configured human-readable default remains ordinary configuration.
- During Milestone 2 the compatible client.json was mode 0664, so unattended validation correctly required the documented chmod 600 correction. The owner applied that correction after accepting the milestone; Milestone 4 validation confirmed mode 0600.
- GStreamer plugin availability may vary across Ubuntu updates.

### Status

Complete on branch m2-config-boundaries. Offline typed configuration, credential
validation, reproducible Python dependency metadata, tests, and setup/rollback
instructions are present. The legacy runtime and credentials remain unchanged.
Live Hue area existence/uniqueness validation is deferred to Milestone 3 as
planned. Stop for review before Milestone 3.

## Milestone 3 — Refactor Harmonize Without Changing Behavior

### Objective

Separate the monolithic script into testable components while preserving the current Ambilight algorithm and manual behavior.

### Why it matters

Clear ownership of resources is required to fix races, recover safely, and add automation without changing visual behavior accidentally.

### Planned work
- [x] Add Hue area resolution that maps the exact configured name TV area to one Entertainment configuration before any start request.
- [x] Keep legacy/manual interactive selection available when practical, but prohibit area prompts in unattended mode.

- [x] Establish components for capture, Hue bridge/API control, frame/color analysis, HueStream packet construction, DTLS transport, and controller lifecycle.
- [x] Replace shared mutable globals with explicit state and ownership.
- [x] Replace fixed startup sleeps with readiness/error signaling.
- [x] Synchronize frame and color data consistently.
- [x] Make capture reset safe relative to active reads and preserve file/URL inputs.
- [x] Use binary-safe HueStream transport and add packet-level tests.
- [x] Make cleanup safe after failures at every partial startup stage covered offline.
- [x] Run a separately approved read-only live test confirming TV area exists and test an unknown configured name for a clear pre-stream error.
- [x] Run a separately approved manual start/stream/stop test scoped to TV area and verify cleanup afterward.
- [x] Create characterization tests for light-position mapping, RGB encoding, brightness behavior, and packet layout.
- [x] Run the refactored application manually against the same capture and Hue setup only under an approved test procedure.

### Acceptance criteria

- [x] Each named component has a narrow interface and clear resource ownership.
- [x] Existing CLI behavior and Ambilight sampling are preserved or differences are documented and approved. Milestone 3 was accepted with its documented setup-path differences.
- [x] Packet construction is binary-safe and covered by deterministic tests.
- [x] Thread startup and capture reset no longer depend on arbitrary sleeps; bounded shutdown work remains Milestone 4.
- [x] Unattended area-check execution resolves TV area deterministically with no prompt.
- [x] Missing or ambiguous configured areas fail before streaming with an actionable message naming the configured value.
- [x] The approved live Hue test confirms streaming starts and stops only for the resolved TV area.
- [x] Manual end-to-end operation succeeds before automation begins.
- [x] The pre-refactor commit ee4bbc0 remains a tested rollback point.

### Risks/unknowns

- Existing text-mode OpenSSL piping may conceal protocol behavior that must be characterized before replacement.
- Renaming or duplicating TV area after configuration must produce a safe startup failure rather than an interactive prompt or arbitrary selection.
- Correcting obvious bugs could change observable brightness or color output; compatibility comes first in this milestone.
- Hardware-only behavior cannot be fully covered by unit tests.

### Status

Accepted and integrated into modernize at b4474c2. The component refactor, 41
offline tests, read-only exact/unknown Hue validation, unattended area check,
and combined capture/analysis/unsent-packet preflight pass. The approved active
test confirmed "TV area" changed from inactive to active during the binary
stream, one q stopped the refactored application with exit status zero, and an
immediate read-only query confirmed inactive cleanup. The user also confirmed
the lights visually followed the video correctly.

## Milestone 4 — Headless Lifecycle and Reliability

### Objective

Make Harmonize run indefinitely without a terminal, with deterministic startup, shutdown, cleanup, recovery, and logging.

### Why it matters

An appliance service must survive routine errors and obey operating-system lifecycle requests without leaving capture or Hue resources stuck.

### Planned work

- [x] Remove runtime dependence on input(), screen, interactive reset/quit commands, and interactive Entertainment-area selection.
- [x] Handle SIGTERM and SIGINT through a single idempotent shutdown path.
- [x] Bound network, capture, subprocess, and thread shutdown waits.
- [x] Revalidate the configured Entertainment area during startup and recover safely if it was renamed, removed, or became ambiguous.
- [x] Exercise approved live partial-startup and shutdown failures and verify Entertainment streaming is stopped afterward.
- [x] Clean up correctly after failures before and after Hue streaming begins.
- [x] Implement capture reopen with backoff and the original configured source.
- [x] Detect and recover failed DTLS and Hue stream sessions.
- [x] Add structured, severity-based, journald-friendly logging with secret redaction.
- [x] Define health and liveness indicators usable by systemd and diagnostics.
- [x] Run an extended manual soak test before adding automatic source control.

### Acceptance criteria

- [x] The application starts and stops without a terminal.
- [x] SIGTERM and SIGINT produce clean, bounded shutdown.
- [x] Injected partial startup failures release every acquired resource.
- [x] Capture and transport failures recover or exit with an actionable status.
- [x] Logs identify state and failures without credential material.
- [x] Headless startup never waits for Entertainment-area input.
- [x] Live failure-injection results demonstrate cleanup of the configured TV area without leaving an active session.
- [x] The 301.846-second soak-test result and pre-milestone rollback commit are recorded.

### Risks/unknowns

- Hue API operations are bounded at five seconds but can still fail independently of DTLS; exhausted recovery exits and performs scoped cleanup.
- Capture reopen with backoff is covered with injected failures. Physical USB re-enumeration was not forced because it could disrupt the appliance; a device that disappears permanently produces continuing degraded health until shutdown.
- DTLS recovery deliberately cycles the owned Entertainment session to clear stale bridge state, causing a brief visible interruption.
- The live GStreamer backend warns that video position and buffer-size properties are unsupported, but sustained capture remained healthy.

### Status

Accepted and integrated into modernize at 13670ff. Fifty-one offline tests,
three live partial-startup failures, real SIGTERM and SIGINT shutdown, live
DTLS and Hue session recovery, structured health/log validation, and a
301.846-second headless soak passed. Every active test finished with the exact
"TV area" inactive and no lingering Harmonize or OpenSSL process.

## Milestone 5 — Automatic Ambilight State Machine

### Objective

Keep the controller running continuously while starting and stopping Hue Entertainment according to a normalized desired state supplied by a modular trigger provider.

### Why it matters

The lifecycle must behave consistently whether desired state comes from manual local control, future Homebridge automation, future CEC hardware, or another provider.

### Planned work

- [x] Implement IDLE → STARTING → STREAMING → STOPPING → IDLE with explicit error/recovery transitions.
- [x] Define a provider interface that emits enabled/disabled desired state with source and timestamp.
- [x] Implement a small local command or API surface for Ambilight ON, OFF, and STATUS.
- [x] Keep provider-specific logic outside capture, Hue, DTLS, cleanup, and light-state components.
- [x] Define precedence, authentication, stale-command expiry, and fail-safe behavior for multiple providers.
- [x] Make automatic providers optional; do not require HDMI-CEC or Homebridge.
- [x] Apply debounce and grace periods to automatic providers while keeping explicit commands deterministic.
- [x] Expose desired state, actual lifecycle state, transition progress, provider source, and errors.
- [x] Log every transition with reason and elapsed time.
- [x] Test state sequences with a fake clock, fake provider, and fake Hue controller.
- [x] Run approved live ON/OFF/STATUS cycles against the configured TV area and confirm each final state.
- [x] Validate repeated explicit ON/OFF cycles before enabling any automatic provider.
- [x] Defer Homebridge/HomeKit integration until separately authorized.

### Acceptance criteria

- [x] An ON command starts one Hue Entertainment session and reaches STREAMING.
- [x] An OFF command reaches IDLE after complete cleanup. Normal light-state restore/off behavior remains explicitly deferred to Milestone 6.
- [x] STATUS distinguishes desired state, actual state, transition state, and errors.
- [x] The same lifecycle tests pass with interchangeable fake providers.
- [x] Provider loss or stale state follows a documented fail-safe policy.
- [x] The Harmonize controller remains alive in IDLE.
- [x] Failures transition predictably and never skip required cleanup.
- [x] Live lifecycle tests affect only the configured TV area and leave its Entertainment session stopped.
- [x] Homebridge is not a runtime dependency of the core daemon.

### Risks/unknowns

- The local API uses a mode-0600 Unix socket and no network listener; its authentication boundary is operating-system filesystem access by the service user.
- Explicit local state has priority 100 and persists for the daemon lifetime. Future automatic sources must use lower priorities and refresh before their configured stale timeout.
- Automatic provider flapping is contained by configurable ON debounce and OFF grace; no automatic provider is enabled yet.
- Hue sessions started elsewhere may still conflict with ownership assumptions; lifecycle operations remain scoped to the exact configured area.

### Status

Accepted and integrated into modernize at 66d5495. Sixty-nine offline tests and
a real read-only IDLE/OFF check passed. Three approved live ON/STATUS/OFF cycles
each created one fresh controller, reached STREAMING, cleaned up to IDLE, and
kept the daemon responsive between cycles. Final read-only Hue status was
inactive. Homebridge/HomeKit and all automatic providers remain deferred.

## Milestone 6 — Hue Light State Management

### Objective

Capture pre-stream Hue state for safe exceptional cleanup while ensuring explicit user OFF leaves every configured-area light powered off.

### Why it matters

Automatic streaming should not leave household lighting in an unwanted state after signal loss, shutdown, or recoverable failure.

### Planned work

- [x] Identify every Hue resource affected by the selected entertainment configuration.
- [x] Determine which state fields can be read and restored reliably through the Hue v2 API for the current static Hue Play resources.
- [x] Capture state immediately before taking control and associate it with the session.
- [x] Make explicit OFF and daemon/service stop turn every configured-area light off; retain configurable restore/off only for exceptional cleanup.
- [x] Use restore as the default exceptional-cleanup policy after reliability is demonstrated.
- [x] Define behavior when lights change externally during streaming.
- [x] Implement guarded handling for process crash, bridge loss, partial restore, and stale saved-state scenarios, including live startup-failure cleanup verification.
- [x] Ensure saved state contains no credentials and has safe lifecycle/permissions.
- [x] Run approved live restore and off tests only against lights in the resolved TV area.
- [x] Record pre-test state and verify post-test state after normal stop and injected failure.
- [x] Test against controlled fake light states and document the live recovery procedure.

### Acceptance criteria

- [x] Explicit OFF and daemon/service stop leave every affected light powered off.
- [x] Restore accurately handles representative on/off, brightness, and color states supported by the selected lights.
- [x] Partial failures are logged and retried or surfaced without infinite loops.
- [x] Stale state cannot unexpectedly overwrite newer household changes.
- [x] Live Hue integration tests prove both restore and off behavior and leave no active Entertainment session.
- [x] A documented manual recovery procedure exists.
- [x] The pre-state-management behavior remains a rollback option.

### Risks/unknowns

- Entertainment mode and normal Hue state can expose different resource models.
- Gradient products may require grouped and per-segment considerations.
- Perfect restoration may be impossible for dynamic scenes or concurrent external control.
- Crash recovery needs careful rules to avoid applying stale state.

### Status

Complete on branch m6-light-state and awaiting review after the required
explicit-stop correction. Explicit OFF and daemon/service stop now have a fixed
off disposition, while ambilight.exception_cleanup_behavior controls only
exceptional cleanup and defaults to restore. All 89 offline tests pass. Focused
live validation proved that explicit OFF left both TV area lights dark until an
independent change, while an injected after-DTLS-ready startup failure restored
the visible pre-failure states. The original test baseline was restored and
Entertainment finished inactive with no journal, socket, Harmonize process, or
DTLS process. Detailed evidence is in docs/milestone-6-light-state.md.
Milestone 7 is in progress on branch `m7-systemd-appliance`.

## Milestone 7 — systemd Appliance Deployment

### Objective

Install Harmonize as a native, boot-started Ubuntu service with least-privilege hardware access and safe restart behavior.

### Why it matters

systemd provides lifecycle, logging, dependency ordering, and recovery needed for unattended operation without adding Docker as a dependency.

### Planned work

- [x] Exclude Docker, AirPrint, and host CUPS inspection and validation from this milestone per explicit owner direction; no work in this milestone requires them.
- [x] Choose an unprivileged service identity and grant only required video-device and configuration access.
- [x] Create a hardened service unit with explicit working directory, restart policy, timeouts, readiness, and signal handling.
- [x] Use stable capture-device identification rather than assuming /dev/video0.
- [x] Route logs to journald and document inspection commands.
- [x] Order startup after network-online without changing unrelated services.
- [x] Configure the service with the default TV area and verify startup cannot enter an interactive selection path.
- [x] Install through a reversible, non-overwriting procedure; the observed baseline contained no targets requiring backup.
- [x] Enable boot start and test clean stop, restart, failure restart, shutdown, and readiness. Full reboot remains part of final validation; uninstall/reinstall was intentionally deferred by the owner at acceptance.
- [x] Measure CPU and memory in IDLE and STREAMING; device access worked through the stable capture path.
- [x] Keep Harmonize native; no Docker deployment was added.

### Acceptance criteria

- [x] Harmonize is installed, enabled for automatic boot startup, and running as an unprivileged user. A full reboot exercise remains in final validation.
- [x] It runs under a locked identity with only required video, configuration, runtime, and state access.
- [x] Restart policy handles a forced failure after a five-second delay without a tight loop.
- [x] journald contains useful, secret-free lifecycle logs.
- [x] Shutdown releases Hue and capture resources within configured timeouts and turns both configured-area lights off.
- [x] Start and restart deterministically resolve the configured TV area without prompting; boot startup is configured and its full reboot exercise remains in final validation.
- [x] Docker, AirPrint, and host CUPS checks are not applicable to this milestone under the owner's explicit scope override and were not performed.
- [x] Guarded uninstall tooling documents restoration of the exact pre-install service state; uninstall/reinstall execution was intentionally skipped at owner acceptance.

### Risks/unknowns

- Device enumeration and network readiness can differ at boot.
- Service hardening options may restrict OpenSSL, DNS/mDNS, or device access unexpectedly.
- A single normal-restart test reached the 25-second stop timeout; an immediate focused clean-stop repetition completed in 0.186 seconds and later STREAMING shutdown completed normally. Preserve this as a soak-test observation.

### Status

Complete and accepted on `m7-systemd-appliance`. The native service is
installed, enabled, and running; stable capture identity and least-privilege
access are working. All 97 offline tests and systemd unit validation pass. Live
ON/OFF and service-stop behavior are visually confirmed, and forced-failure
restart works with bounded backoff. Guarded rollback tooling and instructions
exist, but uninstall/reinstall execution was intentionally skipped at owner
acceptance. A complete reboot exercise remains in final validation. Docker,
AirPrint, and host CUPS were explicitly out of scope and were not inspected.
Detailed evidence is in `docs/milestone-7-systemd.md`.

## Milestone 8 — Trusted-LAN HTTP Control

### Objective

Provide a deliberately small HTTP interface on TCP port 8765 that maps three
fixed trusted-LAN requests to Harmonize's existing desired-state boundary.

### Why it matters

Simple LAN clients need a stable way to request ON, OFF, and current status
without gaining direct access to Harmonize's private Unix socket or credentials.

### Planned work

- [x] Listen on TCP port 8765 and accept only exact GET requests for
  `/?harmonize=on`, `/?harmonize=off`, and `/?harmonize=status`.
- [x] Map fixed request values directly to the existing owner-only Unix socket;
  never construct or execute shell commands from request input.
- [x] Return concise results and explicit HTTP errors for invalid input,
  unavailable local control, and invalid daemon responses.
- [x] Run under a least-privilege systemd boundary without exposing Hue
  credentials or the persistent light-state journal.
- [x] Preserve explicit OFF semantics: every light in `TV area` must be off.
- [x] Add offline tests for exact command mapping, status, invalid input,
  unavailable service/socket behavior, and deployment boundaries.
- [x] Document setup, diagnostics, trusted-LAN exposure, and full rollback.
- [x] Perform controlled live HTTP validation of STATUS, ON, and OFF.
- [x] Keep unrelated services and Milestone 9 outside this milestone.

### Acceptance criteria

- [x] HTTP ON causes Harmonize to reach STREAMING and the configured `TV area` lights visibly follow captured video.
- [x] HTTP OFF causes Harmonize to reach IDLE and every configured-area light remains powered off.
- [x] HTTP STATUS accurately reports the current Harmonize supervisor state.
- [x] Missing, unsupported, duplicate, or extra input cannot invoke a command.
- [x] The interface listens on TCP port 8765 without authentication, as an
  explicitly trusted-LAN service.
- [x] Request input is never passed to a shell, and the adapter cannot access
  Harmonize credentials or persistent state.
- [x] Adapter failures and an unavailable Harmonize service are bounded, visible, and do not leave a stuck Entertainment session.
- [x] Setup and rollback can be completed from the documentation.
- [x] Offline and live results are recorded, Entertainment finishes inactive, and only `TV area` is affected.

### Risks/unknowns

- The interface is intentionally unauthenticated, so host and network policy
  must keep port 8765 limited to the trusted LAN.
- ON and OFF acknowledge socket acceptance rather than waiting for lifecycle
  completion; clients should query STATUS when they need resulting state.
- A Harmonize restart temporarily removes its Unix socket; the adapter must
  report that condition without retrying or changing desired state.

### Status

Complete and accepted on `m8-http-interface` on 2026-09-13. The HTTP adapter
is installed, enabled, and live-validated on TCP port 8765. The working
external control interface is `/?harmonize=on`, `/?harmonize=off`, and
`/?harmonize=status`. Both services are active and running; final state is
IDLE with the exact two-channel `TV area` reporting Entertainment inactive.

## Milestone 9 — Ambilight Quality Improvements

### Objective

Evaluate visual improvements only after reliable unattended operation is proven.

### Why it matters

Quality work should be measurable and reversible, and must not destabilize lifecycle behavior or hide regressions from the refactor.

### Planned work

- [ ] Capture repeatable reference clips and baseline latency, CPU use, update rate, and representative color output.
- [ ] Evaluate temporal color smoothing.
- [ ] Correct and make brightness limiting behavior explicit.
- [ ] Evaluate saturation and gamma correction.
- [ ] Evaluate black-bar detection and improved edge sampling regions.
- [ ] Define dark-scene behavior.
- [ ] Evaluate scene-change response.
- [ ] Make update rate configurable within Hue bridge limits.
- [ ] Introduce each improvement separately with objective comparisons and an off switch.

### Acceptance criteria

- [ ] Appliance lifecycle tests continue to pass with every enabled enhancement.
- [ ] Each accepted option has documented defaults, bounds, performance cost, and rollback.
- [ ] Measured latency and CPU use remain within agreed Pi 5 limits.
- [ ] Visual changes are compared against the preserved baseline.
- [ ] Enhancements can be disabled independently.

### Risks/unknowns

- Smoothing can improve stability while increasing perceived latency.
- Black-bar and dark-scene logic can misclassify intentional content.
- Higher analysis cost can interfere with Docker, printing, or capture timing.
- Subjective improvements require consistent test content and viewing conditions.

### Status

Not started.

## Milestone 10 — Final Validation and Documentation

### Objective

Prove the complete appliance behavior across normal operation, failures, reboot, and coexistence, then document operation and recovery.

### Why it matters

The project is complete only when it can be maintained and recovered without reconstructing decisions from source code or terminal history.

### Planned work

- [ ] Test a full Pi reboot and automatic service startup.
- [ ] Test TV/source on and verify automatic streaming.
- [ ] Test source standby/off and the configured light-state result.
- [ ] Test TV off while the source remains active.
- [ ] Test repeated on/off cycles and brief signal interruptions.
- [ ] Test temporary capture failure and reconnection.
- [ ] Test exact resolution of TV area and the actionable failure for a missing or ambiguous configured area.
- [ ] Verify every live test and service stop leaves Hue Entertainment streaming disabled.
- [ ] Verify only the configured Entertainment area and its affected lights change during controlled tests.
- [ ] Test temporary Hue/network failure where practical and safe.
- [ ] Test service stop, start, restart, failure restart, SIGTERM, and shutdown.
- [ ] Verify that the airprint container remains healthy and complete a working-print check.
- [ ] Verify Docker service and every other recorded workload against baseline; confirm host CUPS was not modified.
- [ ] Record idle/streaming CPU, memory, temperature, frame rate, and recovery timing.
- [ ] Document installation, configuration, credentials, operation, logs, troubleshooting, updates from upstream, backup, and rollback.
- [ ] Perform a clean-install rehearsal or equivalent reproducibility review.
- [ ] Record the final accepted commit and release/tag.

### Acceptance criteria

- [ ] Every end-to-end scenario has a recorded result and any failure has an explicit disposition.
- [ ] Repeated source cycles do not leak processes, threads, file descriptors, Hue sessions, or unwanted light state.
- [ ] Reboot and service recovery require no terminal interaction.
- [ ] Airprint printing and all other Docker workloads remain functional according to recorded baselines; host CUPS remains untouched.
- [ ] A new operator can install, configure, diagnose, update, and roll back using the documentation.
- [ ] Credentials are absent from Git history, logs, examples, and diagnostic bundles produced by the modernization work.
- [ ] The full Hue validation matrix passes for area resolution, streaming lifecycle, recovery, and post-Ambilight state.
- [ ] Installation documentation explains the default area setting, exact-name matching, legacy/manual selection, and failure recovery.
- [ ] The final release has a clear previous known-good rollback point.

### Risks/unknowns

- Some network and bridge failures may be difficult to reproduce safely.
- Reboot ordering can expose races not visible in interactive testing.
- Airprint validation may require a physical print test, and Docker health inspection requires an authorized read-only access method.
- Long-duration reliability may reveal thermal or resource contention not seen in short tests.

### Status

Not started.
