# Milestone 9: Ambilight quality optimization plan

## Purpose and scope

This document is the persistent test plan and experiment log for Milestone 9.
It supplements the Milestone 9 roadmap in `PROJECT.md`. Update it as work
progresses so future sessions can identify the control behavior, measurements,
approved experiments, rejected ideas, rollback choices, and current accepted
configuration.

The goal is to improve responsiveness and reduce latency where worthwhile while
preserving the visual character and appliance reliability of the released
v3.0.0 implementation. This milestone favors measured, incremental,
independently reversible changes over broad algorithm changes.

The subjective starting point is intentionally conservative:

- The current Ambilight effect already looks good.
- Responsiveness and latency are higher priorities than visual redesign.
- Historical brightness behavior remains part of the control, even where its
  semantics are mathematically unusual.
- Letterboxed content is common, but black-bar handling is justified only if
  measurements show that bars affect the configured sampling regions.
- An optimization that is not measurably or noticeably better while looking at
  least as good as v3.0.0 should be rejected.

## Released control and discovery baseline

The control is released v3.0.0 at commit
`6aec8cca7afbaf05c3923f79afac5108799cb1a4`. The Milestone 9 topic branch is
`m9-ambilight-quality`.

### Sampling

Each Hue Entertainment channel has an independently calculated rectangular
sampling region. Hue `x` maps horizontally, Hue `z` maps vertically with its
sign inverted, and Hue `y` is ignored. The sample distance is:

```text
int(sample_breadth * (frame_width / 2 + frame_height / 2))
```

That distance extends in all four directions from the mapped channel position,
with the result clipped to the frame edges. The deployed `sample_breadth` is
`0.15`.

At the previously measured 720x480 capture format, the distance is 90 pixels.
A typical channel placed at the left or right midpoint therefore samples a
side region approximately 90x180 pixels after edge clipping. The algorithm
does not divide the frame into one half per light; each channel is evaluated
independently from its Hue coordinates.

For the current two-light left/right arrangement, ordinary top and bottom
letterboxing probably does not intersect midpoint sampling regions. Bars could
strongly affect vertically positioned channels, however, so actual channel
geometry and frame/bar boundaries must be measured before implementing
black-bar handling.

### Brightness and output

Current multi-light processing is:

1. Convert the complete BGR frame to HSV.
2. Add the configured brightness adjustment to HSV value, clipping the upper
   end at 255.
3. Convert the adjusted frame back to BGR and then to RGB.
4. Arithmetic-mean red, green, and blue independently within each channel's
   sampling region.
5. Divide each 8-bit mean by two using integer truncation.
6. Repeat that byte as the high and low bytes of the HueStream 16-bit RGB
   component.
7. Send one RGB triplet per channel through the Entertainment DTLS stream.

There is no separate streamed Hue brightness field. Perceived brightness
results from RGB magnitude. Dark pixels and black bars therefore reduce the
regional channel means directly. Averaging different colors can also reduce
saturation.

The historical divide-by-two encoding limits the greatest streamed component
to 32,639 of 65,535, approximately half the available numeric range. The
deployed `brightness_adjustment` is `0`. Positive adjustment values brighten
HSV value rather than acting as a maximum-brightness percentage. Negative
values are accepted by configuration but fail against the unsigned NumPy value
array instead of reliably darkening the image.

These confusing semantics are part of the current good-looking baseline.
Brightness cleanup or full-range output is a later controlled visual
experiment, not an initial correction.

### Timing and latency

The released v3.0 control and backward-compatible public default use
`update_interval_seconds = 0.05`, applied after each completed packet send.
Its nominal ceiling is therefore 20 updates per second. A passive live
observation during discovery measured system UDP output consistent with
approximately 19 Hue updates per second. At Milestone 9 closeout, the owner Pi
explicitly opts into `0.033`; that device-specific choice does not change the
public default.

The capture worker continuously drains its OpenCV source, retains only the
newest application-level frame, and wakes the controller when a newer
generation is available. Earlier controlled capture work measured about 55
frames per second at 720x480 using the Harmonize-style GStreamer path. The
deployed service now uses the direct V4L2 backend and does not log its
negotiated resolution or frame rate, so those live values remain to be
measured.

During the discovery observation, OpenCV/V4L2 rejected
`CAP_PROP_BUFFERSIZE=0`. The application discards superseded frames, but
capture-device, kernel, or backend buffering below that boundary remains an
unknown. End-to-end video-to-photon latency has not yet been measured. The
explicit 50 ms pacing alone can delay the next update by up to approximately
50 ms, or approximately 25 ms on average for randomly timed visual changes.

Other latency sources include HDMI/capture conversion, frame acquisition and
decode, whole-frame color conversion, regional analysis, synchronous DTLS
pipe writes, LAN/bridge processing, and light rendering. A synchronous Hue
status query in the controller can also introduce an occasional packet gap at
its configured interval.

### Runtime cost

The discovery sample found substantial Raspberry Pi 5 headroom while
STREAMING:

- Harmonize Python averaged about 59% of one CPU core and roughly 95 MiB RSS.
- The OpenSSL DTLS child used negligible CPU and roughly 8 MiB RSS.
- The service cgroup used roughly 118 MiB current and 143 MiB peak memory.
- The four-core host load average was below 1, with roughly 3 GiB RAM
  available and a temperature near 49 degrees Celsius.
- No service restart or recovery event occurred.

Capture and decode appear to dominate CPU use. Packet construction and OpenSSL
transmission are not promising optimization targets by themselves.

## Optimization experiment sequence

Only one meaningful variable should change in each experiment. Do not make a
trial setting the new default until its measurements and visual comparison have
been reviewed.

### Step 1 - Instrumentation and 50 ms control

Add lightweight instrumentation sufficient to measure:

- negotiated capture resolution and reported FPS;
- capture-frame arrival timing;
- frame age when analysis begins;
- analysis duration;
- packet/update interval and effective packet rate;
- skipped or replaced application-level frames where practical;
- unusually long packet gaps;
- CPU and RSS; and
- service stability and recovery events.

Establish a measured control with
`update_interval_seconds = 0.05`. Do not change visual processing in this
step. Instrumentation must avoid per-frame INFO logging or other measurement
overhead large enough to perturb the pipeline.

### Step 2 - 33 ms pacing

Change only `update_interval_seconds` to `0.033`, targeting approximately 30
updates per second. Compare directly with the 50 ms control:

- actual update rate and packet consistency;
- frame age and analysis duration;
- CPU and RSS;
- Hue/DTLS errors and unusually long gaps;
- service stability; and
- subjective responsiveness and visual quality.

Do not automatically make 33 ms the permanent default. Restore `0.05` after
the trial unless the result is explicitly accepted.

### Step 3 - 20 ms pacing, only if justified

Test `update_interval_seconds = 0.020` only if the 33 ms trial is completely
stable and its results suggest that a higher send rate could provide a further
benefit. Compare 20 ms directly with 33 ms, not only with the original 50 ms
control. Reject it if increased traffic or CPU produces no meaningful
responsiveness improvement.

### Step 4 - Capture and frame-age investigation

Use the instrumentation to determine whether frames reaching Harmonize are
already stale because of capture-device, V4L2, or backend buffering. The
application already retains its newest available frame, so do not redesign
that mechanism without evidence.

If measurements demonstrate meaningful lower-level buffering, test one
controlled low-buffer alternative, such as a supported V4L2 setting or a
drop-enabled GStreamer pipeline. Preserve the current direct V4L2 path for
immediate rollback.

### Step 5 - Brightness-zero analysis fast path

Because the deployed brightness adjustment is zero, investigate bypassing the
whole-frame BGR-to-HSV-to-BGR round trip only when the adjustment is exactly
zero. Accept this optimization only if deterministic characterization tests
show that final HueStream RGB bytes remain byte-for-byte identical to the
released algorithm. Its purpose is CPU reduction, not a visual change, and the
legacy path must remain available during evaluation.

### Step 6 - Black-bar measurement

Measure actual channel geometry and sampling-region overlap with representative
letterboxed frames. Do not implement black-bar detection merely because bars
are present somewhere in the frame.

Test black-bar-aware sampling only if measurements show meaningful overlap.
Any implementation must be optional, robust against intentionally dark scenes,
and able to restore the legacy fixed-region behavior independently.

## Deferred visual experiments

Do not prioritize the following until timing and capture optimization have
been completed and evaluated:

- temporal smoothing;
- gamma correction;
- saturation adjustment;
- full-range brightness/output redesign;
- major sampling-region changes;
- scene-change processing; and
- dominant-color or max-pixel selection.

Temporal smoothing is particularly low priority because it adds latency, which
conflicts with the current goal. Aggressive dominant-color selection risks
overreacting to subtitles, isolated highlights, and noise. Brightness,
saturation, gamma, and major region changes all have a higher risk of making
the current good-looking output worse and therefore require separate opt-in
controls and visual comparisons.

## Comparison content

Where practical, compare each candidate with the same representative scenes
and viewing conditions:

- fast scene cuts and action;
- slow pans;
- dark scenes;
- bright scenes;
- strong left/right color contrast; and
- letterboxed content.

Reference material must not be committed unless its licensing and repository
size are appropriate. Record enough identifying information to repeat a test
without storing protected content.

## Safety and acceptance rules

For every experiment:

- preserve released v3.0.0 behavior as the control;
- change one meaningful variable at a time;
- measure before and after;
- keep the change small and reversible;
- provide an off switch or direct rollback where practical;
- preserve systemd lifecycle, local Unix-socket control, HTTP control, and
  HomeKit integration;
- never expose Hue credentials;
- leave Docker, AirPrint, host CUPS, and unrelated services untouched; and
- avoid visual complexity merely because it is technically possible.

The acceptance question is: does this make Harmonize measurably or noticeably
more responsive while still looking as good as the released version? If not,
retain the simpler released behavior.

## Experiment log

Add one entry for each control measurement or experiment. Do not rewrite prior
results; append corrections or follow-up entries so the decision history
remains clear.

### Entry template

```text
Date:
Experiment/step:
Commit:
Configuration:
Test content/conditions:
Measurements:
Subjective observation:
Result: accepted | rejected | inconclusive
Rollback/default decision:
Notes/follow-up:
```

### Recorded entries

#### 2026-09-15 - Step 1 instrumentation and 50 ms control

- **Commit:** `671476c` (`Instrument Ambilight streaming performance`)
- **Configuration:** topic-branch application with the released capture,
  sampling, brightness, packet, and 50 ms pacing settings. A temporary config
  used separate `/tmp` control, health, and light-state paths; installed files
  were not replaced.
- **Test conditions:** current HDMI movie playback and the same physical
  capture, two-channel `TV area`, bridge, Pi, and LAN later used for Step 2.
  The released appliance was put in IDLE through its normal interface while
  this isolated process owned capture and Entertainment streaming.
- **Capture:** V4L2 negotiated 640x480 YUYV at a reported and measured 30.0
  FPS. OpenCV rejected the requested zero buffers and reported four buffers.
  Stable capture interarrival means were 33.315 ms, with p95 values around
  34 ms.
- **Measurements:** four stable 10-second windows, excluding the first warm-up
  window, averaged 17.601 updates/s. Mean packet interval was 56.819 ms
  (median 56.588 ms, mean-window p95 57.530 ms). Mean frame age at analysis
  start was 17.275 ms (mean-window p95 31.564 ms). Mean analysis duration was
  6.111 ms. Each stable window contained one long packet gap, with observed
  maxima of 83.5--96.2 ms, coincident with the synchronous 10-second Hue
  status-check cadence.
- **Resource sample:** 15 one-second `pidstat` samples averaged 58.87% of one
  CPU and 96,583 KiB RSS. OpenSSL remained negligible in the prior discovery
  measurement and was not separately sampled in this trial.
- **Stability:** no capture recovery, Hue error, DTLS error, or controller
  recovery occurred. The bounded run shut down cleanly, stopped Entertainment,
  and powered off both area lights.
- **Subjective observation:** not independently measurable by the agent. The
  visual algorithm and output encoding were unchanged.
- **Result:** accepted as the instrumented 50 ms control.
- **Rollback/default decision:** released 50 ms pacing remains the tracked and
  installed default.
- **Notes:** earlier 720x480/~55 FPS results described a different GStreamer
  path. The deployed-style direct V4L2 path actually used for these comparisons
  is 640x480/30 FPS.

#### 2026-09-15 - Step 2 33 ms pacing

- **Commit:** `671476c`; pacing was changed only in a temporary trial config.
- **Configuration:** identical to the Step 1 control except
  `update_interval_seconds = 0.033`.
- **Test conditions:** same sequential live setup and playback as Step 1.
- **Measurements:** five stable 10-second windows, excluding the first warm-up
  window, averaged 26.230 updates/s. Mean packet interval was 38.129 ms
  (median 37.935 ms, mean-window p95 38.733 ms). Mean frame age at analysis
  start was 16.587 ms (mean-window p95 31.141 ms). Mean analysis duration was
  4.491 ms. Each stable window again contained one status-check-related long
  gap, with observed maxima of 64.4--78.8 ms. Capture remained 30.0 FPS with a
  33.315 ms mean interarrival.
- **Resource sample:** 15 one-second `pidstat` samples averaged 71.00% of one
  CPU and 99,192 KiB RSS.
- **Comparison with control:** update rate increased 49.0%, while median packet
  interval fell 18.653 ms. CPU increased 12.13 percentage points of one core
  (20.6% relative) and RSS increased 2,609 KiB. Mean frame age fell only
  0.688 ms because both trials already select the newest frame from a 30 FPS
  source. The lower observed analysis mean is content/scheduling dependent and
  must not be interpreted as a pacing optimization.
- **Stability:** no capture recovery, Hue error, DTLS error, or controller
  recovery occurred. Shutdown and light cleanup completed normally. The
  released appliance was then returned to STREAMING with its unchanged 50 ms
  installed configuration and still reported zero service restarts.
- **Subjective observation:** not independently measurable by the agent. No
  visual-processing code changed.
- **Result:** accepted as evidence that 33 ms is stable and worthwhile for
  further controlled use, but not yet accepted as the permanent default.
- **Rollback/default decision:** the temporary 33 ms config was discarded;
  tracked and installed configuration remain at 50 ms.
- **Notes:** this trial supports continued evaluation of 33 ms. It does not
  establish video-to-photon latency or prove a visible improvement. Step 3
  (20 ms) and all later experiments remain unstarted.

### Step 1-2 comparison

| Measurement | 50 ms control | 33 ms trial | Interpretation |
| --- | ---: | ---: | --- |
| Effective update rate | 17.601 Hz | 26.230 Hz | 49.0% higher |
| Mean packet interval | 56.819 ms | 38.129 ms | 18.690 ms shorter |
| Median packet interval | 56.588 ms | 37.935 ms | 18.653 ms shorter |
| Mean frame age | 17.275 ms | 16.587 ms | 0.688 ms lower |
| Mean-window frame-age p95 | 31.564 ms | 31.141 ms | effectively unchanged |
| Mean analysis duration | 6.111 ms | 4.491 ms | scene/scheduling dependent |
| CPU, one core | 58.87% | 71.00% | 12.13 points higher |
| RSS | 96,583 KiB | 99,192 KiB | 2,609 KiB higher |
| Capture | 640x480 YUYV, 30.0 FPS | same | directly comparable |
| Errors/recovery | none | none | both stable |
| Long gaps | one per 10 s window | one per 10 s window | status-query cadence |

The evidence supports 33 ms as the next candidate for continued use and
subjective comparison. It does not justify changing the released default yet:
the source is only 30 FPS, mean frame age changed very little, the visible
video-to-light latency was not measured, and the agent cannot judge appearance.
The periodic Hue status request is now a measured jitter source worth retaining
as an observation for later work, outside Steps 1 and 2.

#### 2026-09-15 - Extended 33 ms subjective observation

- **Commit:** `671476c`; pacing changed only in the isolated temporary config.
- **Activation:** the released appliance was placed in IDLE through its normal
  HTTP OFF command. The instrumented topic-branch daemon then used the same
  capture device, bridge, and `TV area` with separate `/tmp` control, health,
  and journal paths and `update_interval_seconds = 0.033`.
- **Duration and timing:** STREAMING ran for 302.427 seconds. After warm-up,
  effective update rate stayed approximately 24.81--24.95 Hz, mean packet
  intervals were approximately 40.12--40.30 ms, mean frame age was
  approximately 15.69--17.31 ms, and mean analysis duration was approximately
  6.46--6.65 ms. Capture remained stable at approximately 30.016 FPS.
- **Stability:** no capture, Hue, DTLS, controller, or recovery error occurred.
  Every stable 10-second window still contained one long packet gap, generally
  approximately 69--90 ms. Explicit OFF completed normally, stopped
  Entertainment, and powered off both area lights. The temporary daemon then
  exited cleanly.
- **Subjective observation:** slight preference for 33 ms, but inconclusive /
  not clearly distinguishable from 50 ms. Both settings felt snappy, and no
  flicker, color degradation, or brightness degradation was observed at 33 ms.
- **Result:** inconclusive subjective improvement with no observed visual
  regression. This supports retaining 33 ms as a candidate, but does not by
  itself justify changing the default.
- **Rollback/default decision:** the released appliance was returned to
  STREAMING with its unchanged installed 50 ms configuration. It remained
  active/running with zero service restarts.
- **Notes:** no tracked or installed visual-processing setting changed, and no
  20 ms test or later experiment began.

### Periodic Hue status-query gap analysis

The recurring gap is caused by a synchronous network request in the controller
thread that also analyzes frames and transmits packets:

1. After sending and timestamping a packet, `HarmonizeController.run` checks
   whether `hue_status_interval_seconds` (currently 10 seconds) has elapsed.
2. It calls `self.hue.resolve_name(self.area.name)` before it can reach the
   next configured pacing wait or process another frame.
3. `HueBridge.resolve_name` calls `list_entertainment_resources`.
4. That method performs a blocking HTTPS GET of
   `/clip/v2/resource/entertainment_configuration` through
   `HueBridge._request` and `requests.Session.request`, with the normal
   five-second request timeout.
5. Only after the complete response is received and parsed can the streaming
   loop continue.

Eight separate read-only live timings returned `active` every time. The first
request, which included connection setup, took 190.783 ms. The following seven
connection-reused requests took 25.086--41.835 ms, averaging 30.596 ms with a
29.920 ms median. This agrees with the excess above ordinary packet intervals:
the extended 33 ms observation normally sent every approximately 40 ms but
showed one approximately 69--90 ms interval per status-check window. The
earlier 50 ms control showed the same pattern at approximately 84--96 ms.

The query has an important lifecycle purpose: because UDP/DTLS packet writes do
not acknowledge that the Entertainment area remains active, it detects a
bridge-side stopped or displaced session and enters the existing transport/Hue
recovery path. Simply deleting the query is the smallest code change but is not
the safest behavior because Harmonize could continue sending while the bridge
no longer applies its stream.

The proposed minimal safe fix is a single-flight asynchronous status monitor:

- Run at most one read-only Entertainment status request at a time on a small
  dedicated daemon worker.
- Give that worker its own `HueBridge` / `requests.Session` so the shared
  startup, recovery, and cleanup session is never used concurrently.
- Have the packet loop poll an in-memory completed result without blocking.
- Preserve current semantics: an inactive status or request failure enters the
  existing recovery path; an active status schedules the next check.
- Stop and boundedly join the monitor before controller cleanup, and discard
  stale results across recovery/session generations.
- Keep the same 10-second interval and existing HTTP timeout initially so only
  scheduling, not policy, changes.

Expected effect: remove the recurring 25--42 ms network wait from the
streaming-critical thread. At 33 ms, ordinary packet timing should remain near
40 ms instead of showing a network-caused approximately 69--90 ms tail every
10 seconds. Average update rate would improve only slightly because this is one
request per 10 seconds; the meaningful gain is reduced worst-case jitter.
Bridge-side session-loss detection should remain equivalent, delayed only
until the next nonblocking packet-loop poll after the query completes.
Startup, recovery policy, explicit OFF behavior, and Hue cleanup should remain
unchanged. The additional thread and session have negligible expected steady
CPU/memory cost.

Before implementation, tests should cover:

- a deliberately slow active-status response while packet sends continue at
  the configured cadence;
- single-flight behavior so checks never overlap;
- active, inactive, timeout, malformed-response, and request-error results;
- preservation of the existing recovery behavior for inactive/error results;
- stale-result rejection after a recovery or new session generation;
- stop during an in-flight check, bounded join, and session closure;
- no shared `requests.Session` use between monitoring and lifecycle actions;
- metrics showing that the 10-second long gap disappears at both 50 and 33 ms;
- the complete offline suite plus controlled live ON, sustained STREAMING,
  explicit OFF, service shutdown, and a deliberate bridge/session-loss test.

The analysis above was completed before implementation approval. Step 3 and all
later Milestone 9 experiments remain unstarted.

### Prioritization decision after subjective comparison

Based on the stable but inconclusive 33 ms comparison, Milestone 9 will
prioritize end-to-end latency reduction over increasing refresh rate. The
highest-value next investigation is removing measured critical-path delay and
reducing frame age; a higher packet rate alone is secondary because 33 ms was
not clearly distinguishable from 50 ms and reduced measured frame age by less
than 1 ms in the controlled trials. The 50 ms setting remains the safe/default
state unless later evidence supports changing it.

### 2026-09-15 - Asynchronous Hue status monitor implementation

The approved minimal status-query fix is implemented without changing capture,
sampling, brightness, packet content, or the configured 50 ms pacing:

- A dedicated daemon worker owns an independent HueBridge and
  requests.Session.
- The packet loop dispatches at most one status request and polls only completed
  in-memory results. It never waits for the HTTPS response.
- Status results carry a streaming-session generation. Stale results are
  discarded, and the monitor is stopped and replaced around recovery.
- Active, inactive, and request-error semantics are unchanged. Inactive or
  failed checks still enter the existing Hue/DTLS recovery path.
- The original policy is preserved: the next ten-second interval starts when
  the previous check completes.
- Monitor shutdown is bounded at 5.5 seconds, just beyond the existing
  five-second Hue request timeout, and its HTTP session is closed by its worker.

Focused tests use a deliberately blocked status query and confirm packet sends
continue, a second request cannot overlap it, shutdown is bounded, stale
generation results are ignored, unexpected worker errors become HarmonizeError,
inactive status triggers the existing recovery sequence, and the independent
Hue session is closed. The complete suite passed 122 tests in 2.701 seconds.

The final live trial used the existing isolated 50 ms configuration, 640x480
YUYV capture at approximately 30.02 FPS, and unchanged TV area mapping. Four
consecutive ten-second metric windows reported:

| Measurement | Observed range |
| --- | ---: |
| Effective update rate | 17.603--17.984 Hz |
| Mean packet interval | 55.880--56.808 ms |
| Maximum packet interval | 57.730--58.921 ms |
| Mean frame age | 16.877--17.168 ms |
| Mean analysis duration | 5.348--6.272 ms |
| Long packet gaps above 75 ms | 0 in every window |
| Hue, DTLS, capture, or recovery errors | none |

Before this fix, the 50 ms control produced one approximately 84--96 ms status
query gap per ten-second window. The final trial removed that recurring tail:
all four windows stayed below 59 ms. The test daemon shut down cleanly, closed
capture and Entertainment streaming, and completed light cleanup. The installed
release was then returned to its unchanged 50 ms configuration and verified
STREAMING with its service active/running and zero restarts.

This validates removal of the synchronous query from the streaming-critical
path under the observed live conditions. It is not a direct video-to-photon
latency measurement, and the short trial does not replace longer appliance
soak testing. No 20 ms pacing or visual-quality experiment was performed.

### Handoff checkpoint

- **Branch/implementation:** m9-ambilight-quality; async Hue status-monitor
  optimization completed at 7cac8ed.
- **33 ms conclusion:** stable and free of observed flicker, color, or
  brightness degradation, with a slight subjective preference over 50 ms, but
  inconclusive and not reliably distinguishable. It is not the default.
- **Status-monitor conclusion:** moving the ten-second HTTPS query off the
  packet thread removed the recurring measured packet tail. Four final 50 ms
  live windows had zero gaps above 75 ms and maxima below 59 ms.
- **Installed appliance:** the v3.0.0 installation was not changed by these
  experiments. It currently runs the released 50 ms version and was verified
  STREAMING with the service active/running and zero restarts.
- **Next priority:** investigate capture-path and end-to-end latency before
  pursuing a higher refresh rate. The live source negotiated V4L2 at 640x480,
  YUYV, 30 FPS. A request for zero capture buffers was rejected and OpenCV
  reported four buffers. Determine how much capture buffering and frame
  acquisition contribute to frame age, and seek a reversible reduction without
  destabilizing capture.
- **Boundary:** that capture experiment has not started. Do not change capture,
  pacing, sampling, brightness, smoothing, gamma, saturation, black-bar logic,
  or the deployed appliance until the next experiment is explicitly approved.

The next agent should begin by reading PROJECT.md and this document in full.

#### 2026-09-15 - Step 4 capture-path latency investigation

- **Commit/configuration:** documentation-only investigation on
  `m9-ambilight-quality`; the installed v3.0.0 application, visual algorithm,
  brightness, sampling, 50 ms pacing, and deployment were not changed. The
  appliance was placed in normal IDLE through its HTTP control while isolated
  probes owned the capture device, then returned to STREAMING.
- **Question and measurement boundary:** the existing Harmonize frame-age
  metric starts when `VideoCapture.read()` returns. It measures time waiting in
  the application's newest-frame slot, but cannot measure age already accrued
  in the capture card, USB transfer, kernel, or OpenCV backend. A native V4L2
  MMAP probe therefore compared each `VIDIOC_DQBUF` timestamp with
  `CLOCK_MONOTONIC` at dequeue. The device marked its timestamps monotonic and
  start-of-exposure (SOE). OpenCV 4.10.0's `CAP_PROP_POS_MSEC` exposed the same
  timestamps and allowed the native result to be checked through the deployed
  backend.
- **Relevant backend behavior:** OpenCV's V4L2 implementation defaults to four
  requested buffers. `CAP_PROP_BUFFERSIZE=0` is not a valid low-buffer request
  for that implementation, explaining the previously observed rejection; it
  left the effective default at four. This WARRKY/`uvcvideo` device accepted
  both four buffers and an explicit one-buffer request and reported those
  counts back correctly. See the
  [OpenCV V4L2 source](https://github.com/opencv/opencv/blob/4.x/modules/videoio/src/cap_v4l.cpp)
  and the
  [Linux V4L2 buffer timestamp specification](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/buffer.html).
- **Native steady-state result:** at the deployed-style 640x480 YUYV, 30 FPS
  format, 300 measured frames after a 30-frame warm-up had no sequence gaps.
  Four requested/allocated buffers produced 29.747 ms median age, 29.830 ms
  p95, and 29.847 ms maximum. One requested/allocated buffer produced 29.746
  ms median, 29.827 ms p95, and 29.834 ms maximum.
- **OpenCV steady-state result:** matching 150-frame checks reported 30.355 ms
  median / 30.455 ms p95 / 31.084 ms maximum with the default four buffers,
  versus 30.303 ms / 30.409 ms / 30.927 ms with one buffer. The median
  difference was 0.052 ms and is not meaningful. Because the timestamp source
  is SOE, the approximately 30 ms primarily covers acquisition and delivery of
  one 30 FPS frame; it is not evidence of a four-frame backlog.
- **Controlled stall result:** after an artificial 200 ms pause in reads, the
  four-buffer path immediately returned frames aged 197.794, 164.989, 132.140,
  and 99.260 ms, then returned to approximately 30 ms. The one-buffer path
  returned one 197.838 ms frame, then returned directly to approximately 30 ms.
  Thus buffer count matters after a reader stall, but not while the dedicated
  Harmonize capture worker drains continuously. The application's latest-frame
  slot also lets the capture worker replace these queued frames rapidly; the
  four stale reads completed in about 2 ms total in this deliberately induced
  case.
- **Interpretation:** current capture buffering is not adding meaningful
  steady-state stale-frame latency. Four allocated buffers are capacity, not a
  standing four-frame queue. The measured lower-bound capture contribution is
  about 30 ms from SOE to userspace. Combining this non-simultaneous result with
  the earlier approximately 17 ms mean application frame age suggests roughly
  47 ms from capture SOE to analysis start under typical conditions, before
  analysis, packet pacing/transmission, bridge processing, and lamp rendering.
  That sum is an estimate, not a new end-to-end measurement, and excludes any
  latency before the capture device's SOE timestamp.
- **How directly latency can be measured:** V4L2 timestamps directly measure
  capture SOE-to-dequeue age on this driver, and OpenCV exposes them for a
  possible future aggregate metric. They cannot establish HDMI-event-to-light
  latency. A defensible end-to-end measurement requires a controlled visible
  source transition plus a common-clock observation of the source/reference
  and Hue output, such as a high-frame-rate camera or photodiodes/data logger.
  Harmonize's current clocks and metrics alone cannot infer that interval.
- **Smallest safe reduction experiment:** no steady-state buffer reduction is
  justified by these results. If resilience to rare capture-worker stalls is
  considered worth testing, the smallest backend experiment is to replace the
  rejected zero-buffer request with an explicit one-buffer request only in an
  isolated topic-branch daemon. Keep every other setting unchanged and compare
  V4L2/OpenCV timestamp age, capture interarrival and sequence gaps,
  application frame age, packet cadence, CPU/RSS, reconnect behavior, and a
  sustained live STREAMING/explicit-OFF cycle against the effective
  four-buffer control. Include a controlled reader-stall test. Do not deploy or
  make it the default without review.
- **Risks:** with one buffer, capture cannot continue into spare queued buffers
  while userspace owns or converts the sole dequeued buffer. That can trade
  shorter backlog recovery for dropped frames, lower throughput, new jitter,
  driver-specific instability, or worse recovery behavior under CPU pressure.
  `CAP_PROP_BUFFERSIZE` support is backend/device-specific. A native timestamp
  also does not include upstream HDMI/capture-hardware delay, and SOE-to-dequeue
  age must not be mislabeled full end-to-end latency.
- **Rollback:** retain the present effective four-buffer V4L2 behavior. For an
  approved isolated one-buffer trial, rollback is the one-line buffer request
  reversal followed by capture reopen; the installed release remains untouched.
- **Result:** accepted as an investigation result: no meaningful normal-path
  stale-frame queue was found, while a bounded backlog effect was demonstrated
  only after an induced reader pause. A backend/capture-path implementation is
  intentionally stopped for owner review.
- **Final state:** the released appliance returned to STREAMING with the same
  service PID, active/running status, and zero restarts.

#### 2026-09-15 - Step 5 brightness-zero analysis fast-path experiment

- **Commit/configuration:** offline characterization on
  `m9-ambilight-quality` using OpenCV 4.10.0 and the released analysis
  semantics. The candidate changed only the zero-adjustment path: it omitted
  the BGR-to-HSV-to-BGR round trip but retained the BGR-to-RGB conversion,
  sampling bounds, arithmetic regional means, integer conversion, and legacy
  HueStream encoding. No application implementation or installed file was
  changed.
- **Equivalence method:** every one of the 16,777,216 possible 8-bit BGR input
  colors was passed through the released `adjust_brightness(frame, 0)` path.
  The released result and unchanged input were compared both as raw pixels and
  after each component's legacy integer divide by two. A uniform sampling
  region preserves each tested color through `cv2.mean`, so an encoded
  component mismatch is also a deterministic final HueStream-byte
  counterexample, independent of channel geometry.
- **Equivalence result:** the zero-adjustment HSV round trip changed at least
  one raw component for 14,396,589 colors. After legacy divide-by-two encoding,
  10,616,708 colors (63.2805% of the complete color space) still differed in
  at least one output component. For example, BGR `(0, 1, 60)` round-tripped to
  `(0, 2, 60)`; a uniform region therefore changes the encoded RGB result from
  `(30, 0, 0)` to `(30, 1, 0)`. This disproves byte-for-byte equivalence.
- **Performance method:** the released and candidate paths were warmed up and
  timed in alternating order over 40 blocks of 50 calls each (2,000 calls per
  path). Input was a deterministic NumPy PCG64 seed `20260915` 640x480 BGR
  frame. Two representative 84x168 edge regions modeled the two-light sampling
  workload. The benchmark was isolated by placing the released appliance in
  normal IDLE; no capture, Hue stream, or installed code participated.
- **Performance result:** the released path measured 4.8614 ms mean, 4.8619 ms
  median, and 4.9015 ms p95 per frame. The candidate measured 0.1960 ms mean,
  0.2016 ms median, and 0.2346 ms p95. It was 24.8 times faster and saved
  4.6654 ms mean analysis time on this synthetic workload. The selected random
  frame happened to produce equal final regional bytes, but the exhaustive
  solid-color counterexamples show that equality is not guaranteed.
- **Interpretation:** the HSV round trip accounts for nearly all measured
  analysis cost and is a meaningful CPU/critical-path optimization target.
  However, bypassing it changes the released visual/output algorithm even when
  `brightness_adjustment` is zero. The experiment therefore fails Step 5's
  explicit byte-for-byte acceptance requirement; performance benefit cannot
  override that compatibility boundary.
- **Result:** rejected. Do not add the brightness-zero fast path under the
  current no-visual-change requirement.
- **Verification:** the unchanged complete offline suite passed 122 tests in
  2.513 seconds after the experiment.
- **Rollback/default decision:** no rollback was needed because no tracked
  analysis code or installed release was modified. Retain the legacy HSV path.
  Any future attempt to remove it must be treated as a separately approved
  visual/output experiment with representative viewing comparisons, not as a
  transparent optimization.
- **Final state:** the released appliance returned to STREAMING with the same
  service PID, active/running status, and zero restarts. Step 6 black-bar
  measurement remains unstarted pending review.

#### 2026-09-15 - Step 5 live candidate follow-up and option design

- **Configuration:** temporary topic-branch fast path with
  `brightness_adjustment = 0`; capture, two-channel sampling, packet encoding,
  Hue status policy, and 50 ms pacing were unchanged. The installed v3.0.0
  appliance was placed in normal IDLE while the isolated daemon used the prior
  `/tmp` M9 control, health, and light-state paths. Installed files were not
  replaced.
- **Offline gate:** one focused characterization test pinned the candidate's
  intentionally different result, and the complete suite passed 123 tests in
  2.705 seconds before live activation.
- **Duration and objective result:** the candidate remained STREAMING for
  266.421 seconds and produced 26 complete ten-second metric windows. Mean
  analysis time stayed between 0.619 and 0.677 ms (window p95 0.666--0.774 ms),
  effective update rate stayed between 19.532 and 19.629 Hz, and mean packet
  interval stayed between 51.115 and 51.198 ms. Mean application frame age was
  16.768--17.648 ms; capture remained 30.014--30.024 FPS. Every window had
  zero packet gaps above 75 ms, and the largest observed packet interval was
  52.797 ms. No capture, Hue, DTLS, controller, or recovery error occurred.
- **Prior-control comparison:** the asynchronous-status 50 ms control measured
  5.348--6.272 ms mean analysis, 17.603--17.984 Hz, and 55.880--56.808 ms mean
  packet intervals. The live candidate therefore removed roughly 4.7--5.6 ms
  from analysis and from the effective post-send pacing cycle. This comparison
  used the same hardware and configuration but was not an immediately
  alternating A/B run, so scene-dependent differences remain possible.
- **Subjective observation (owner):** **visually acceptable / no noticeable
  degradation**. The owner reported no noticeable problem with colors,
  brightness, or light behavior.
- **Cleanup/final state:** explicit candidate OFF completed normal capture,
  Entertainment, and light cleanup; the isolated daemon then exited cleanly.
  The installed released visual path was restored to STREAMING with the same
  service PID, active/running status, and zero restarts. The temporary
  candidate implementation was removed from the working tree.
  The restored 122-test offline suite passed in 3.113 seconds.
- **Revised result:** the fast path remains non-equivalent by deterministic
  byte comparison, but the measured performance improvement was material and
  its differences were not noticeable or objectionable in this live trial.
  It is suitable for an explicit opt-in implementation, not a transparent
  replacement for released behavior.
- **Recommended configuration:** add
  `ambilight.color_processing_mode = "legacy_hsv" | "direct_rgb"`.
  `legacy_hsv` must remain the schema default and the explicit tracked
  deployment value so missing/older configuration preserves v3.0.0 output.
  `direct_rgb` selects the tested fast path and must be rejected during config
  validation unless `brightness_adjustment == 0`; it must never silently
  disable a nonzero brightness adjustment. Do not add a CLI override, which
  would make accidental activation easier.
- **Recommended implementation boundary:** thread the validated mode through
  `AmbilightConfig`, `RuntimeOptions`, `HarmonizeController`, and
  `FrameAnalyzer`; branch only in multi-light frame analysis. Keep
  `adjust_brightness` and the legacy branch intact. Emit the selected mode once
  in structured startup logging. Tests should prove the absent/default setting
  retains the lossy legacy witness bytes, the opt-in produces the characterized
  direct bytes, invalid mode/nonzero-adjustment combinations fail closed, and
  positive brightness plus historical single-light behavior remain unchanged.
- **Recommendation/default decision:** implement `direct_rgb` as an explicit
  opt-in, but keep `legacy_hsv` as the permanent compatibility default. A later
  separately approved deployment may choose `direct_rgb` explicitly for this
  appliance based on the successful live trial. No permanent implementation or
  deployed setting change has been made pending review.

### 2026-09-15 - Configurable performance options implementation

The owner approved implementing the measured performance choices explicitly,
while preserving released behavior as the compatibility defaults:

- `ambilight.color_processing_mode` accepts only `legacy_hsv` and
  `direct_rgb`. An absent setting defaults to `legacy_hsv`, which retains the
  v3.0.0 BGR-to-HSV-to-BGR behavior. `direct_rgb` is rejected during offline
  configuration validation unless `brightness_adjustment == 0`.
- `ambilight.update_interval_seconds` remains configurable. Its default and
  legacy value remain `0.05`; `0.033` is the measured faster option.
- The generic example explicitly uses `legacy_hsv` and `0.05`. This Pi's
  device-specific deployment profile explicitly selects `direct_rgb`, zero
  brightness adjustment, and `0.033` seconds.
- The selected color path, brightness adjustment, and update interval are
  threaded into each controller instance. A structured `analysis_configured`
  startup event records those three safe values plus frame dimensions.
- Local STATUS includes a `performance` object with only
  `color_processing_mode`, `update_interval_seconds`, and
  `brightness_adjustment`. Trusted-LAN HTTP STATUS projects only current state
  and that whitelisted object; it does not expose credentials, bridge details,
  filesystem paths, or other internal configuration.
- The asynchronous single-flight Hue status monitor from commit `7cac8ed`
  remains unchanged. Capture buffering, sampling geometry, packet encoding,
  and light-state/lifecycle behavior are also unchanged.

Focused tests distinguish the known lossy legacy witness from direct RGB,
verify default and opt-in parsing, reject unknown modes and nonzero-brightness
direct RGB, pin the deployment profile, and validate the exact HTTP status
shape plus malformed-status rejection. The complete offline suite passed 129
tests in 3.142 seconds. Deployment configuration validation, Bash syntax for
all four deployment/rollback scripts, and `systemd-analyze verify` for both
units also passed.

Rollback is configuration-only after installation: set
`color_processing_mode = "legacy_hsv"` and
`update_interval_seconds = 0.05`, then restart `harmonize.service`. Both code
paths remain tested and available. The implementation does not merge to
`master`.

## Milestone 9 closeout - 2026-09-15

Milestone 9 is complete and accepted on `m9-ambilight-quality`. The final
owner-observed evening soak used the deployed combination of
`color_processing_mode = "direct_rgb"`, `update_interval_seconds = 0.033`, and
`brightness_adjustment = 0`. It looked good, with no noticeable problem in
colors, brightness, or light behavior. This extends the earlier controlled
visual trial from a short observation to normal evening viewing and records the
subjective result as **visually acceptable / no noticeable degradation**.

The compatibility boundary remains deliberate:

- Public and absent-setting defaults are `legacy_hsv` and 0.050 seconds. The
  generic example retains those settings and therefore preserves released
  v3.0.0 processing and pacing.
- The owner Pi remains explicitly configured for `direct_rgb`, 0.033 seconds,
  and zero brightness adjustment. Closeout does not change that deployment
  back to the public defaults.
- `direct_rgb` is not output-equivalent to the legacy HSV round trip. It is an
  opt-in performance/visual tradeoff, is valid only at zero brightness
  adjustment, and keeps the tested legacy path available for compatibility and
  immediate configuration-only rollback.
- The asynchronous Hue status monitor is retained. It removed the recurring
  synchronous network delay from the packet path while preserving the existing
  inactive/error recovery policy.
- The effective four-buffer V4L2 capture behavior is retained. Native and
  OpenCV timestamp measurements found no meaningful steady-state stale-frame
  queue, and reducing buffers showed no normal-path benefit worth the added
  dropped-frame, jitter, and recovery risk.
- 33 ms pacing remains an explicit option, not the public default. It increased
  measured update cadence, remained stable, and completed the evening soak
  without observed visual problems.

Runtime reporting is part of the accepted interface. Local STATUS carries a
`performance` object, and trusted-LAN HTTP STATUS returns only current state
plus `color_processing_mode`, `update_interval_seconds`, and
`brightness_adjustment`. The options and response shape are documented in
`README.md`, `harmonize.example.toml`, and `docs/milestone-8-http.md`; no
credentials or other sensitive configuration are exposed.

No further smoothing, gamma, saturation, dominant-color, black-bar,
dark-scene, scene-change, or other visual-processing experiment is justified
merely to extend this milestone. Those ideas remain deferred unless a future
observation and separate owner authorization establish a concrete need.

This closeout changes documentation only. The previously recorded 129-test
implementation validation remains applicable, and the automated suite was not
rerun as requested. At closeout the installed performance settings still
reported `direct_rgb`, 0.033 seconds, and brightness zero; both services were
active/running with zero restarts. The owner had left the lifecycle in IDLE
after the soak, and closeout did not change runtime state or configuration.
