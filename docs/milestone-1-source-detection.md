# Milestone 1: Source Activity Detection

## Safety boundary

This milestone observes the USB capture path and local HDMI-CEC availability. It does not contact or control the Hue bridge. It must not modify host-level CUPS, the production airprint container, or any other Docker workload.

## Capture hardware inventory

- Capture device: MacroSilicon WARRKY USB 3.0
- USB identity: vendor 345f, model 2130
- Driver: uvcvideo
- Primary capture node: /dev/video0
- Companion node: /dev/video1
- Stable primary path:
  `/dev/v4l/by-id/usb-MACROSILICON_WARRKY_USB_3.0_<CAPTURE_SERIAL>-video-index0`
- Harmonize-compatible access: OpenCV device index 0 with the GStreamer backend
- The stable by-id path does not open through OpenCV's automatic GStreamer pipeline on this installation. Stable selection will need either index resolution before opening or an explicit pipeline.
- User pi belongs to the video group.
- No process held /dev/video0 or /dev/video1 during the initial inventory.

GStreamer reports MJPEG formats through 1920x1080 and YUY2 formats through 1920x1080. Relevant examples include:

- MJPEG 1920x1080 at 10, 20, 25, 30, or 50 FPS
- MJPEG 1280x720 at 10, 20, 30, 50, or 60 FPS
- YUY2 1920x1080 at 5 or 10 FPS
- YUY2 1280x720 at 10 or 20 FPS
- YUY2 720x480 at 10, 20, 30, or 60 FPS

An unconstrained v4l2src probe negotiated MJPEG 1280x1024 at 60 FPS. The current Harmonize-style OpenCV/GStreamer path negotiates decoded 720x480 frames and reports 60 FPS.

## Repeatable probe

Run the probe from the project virtual environment under an outer timeout:

    timeout 25s /home/pi/harmonize_env/bin/python tools/capture_probe.py \
      --label CONDITION --duration 15

The probe saves no frames. It reports device-open success, reported format, successful and failed reads, first-frame latency, effective frame rate, read timing, interarrival timing, and observed shapes. Pixel-derived aggregate metrics are disabled by default. If frame delivery cannot distinguish active and inactive states, add --content-metrics; this still saves no frames.

An outer timeout is required because a driver-level OpenCV read can block beyond the requested duration when frames stop arriving.

## Initial unclassified observation

At 2026-09-13T18:59:14Z, the current physical HDMI/TV state had not yet been confirmed:

- Open succeeded through GStreamer.
- Reported format was 720x480 at 60 FPS.
- 276 frames succeeded and zero reads failed in 5.010 seconds.
- Effective rate was 55.091 FPS.
- First frame arrived in 1.562 ms.
- Median interarrival time was 18.122 ms; 95th percentile was 18.222 ms; maximum was 31.602 ms.
- No resolution or shape change occurred.
- Content metrics were not collected.

This sample proves continuous frame delivery in the current state. It does not yet prove that frame delivery distinguishes useful HDMI video from standby behavior.

## Controlled active-source observation

At 2026-09-13T19:02:03Z, the TV was on and the HDMI source was confirmed actively playing:

- Open succeeded through GStreamer.
- Reported format was 720x480 at 60 FPS.
- 828 frames succeeded and zero reads failed in 15.011 seconds.
- Effective rate was 55.161 FPS.
- First frame arrived in 1.478 ms.
- Median interarrival time was 18.124 ms; 95th percentile was 18.217 ms; maximum was 31.041 ms.
- No resolution or shape change occurred.
- Content metrics were not collected in the first run.

A matching 15-second content-metrics run at 2026-09-13T19:09:39Z used confirmed moving video:

- 828 frames produced 827 temporal comparisons.
- Median temporal mean absolute difference was 0.718 and the 95th percentile was 3.998.
- 308 comparisons were near-identical, a fraction of 0.372430.
- Mean sampled luma had a median of 41.501 and a 95th percentile of 54.584.
- Minimum luma was 0.0 and maximum temporal difference was 61.633, including capture startup.

Moving video therefore differs strongly from the standby fallback, but paused or intentionally static active content remains a possible false-negative case.

## Controlled source-standby observation

At 2026-09-13T19:06:13Z, the TV remained on while the HDMI source was confirmed off or in standby:

- The non-content probe opened successfully and delivered 829 frames with zero failed reads in 15.026 seconds.
- Reported format remained 720x480 at 60 FPS with no shape change.
- Effective rate was 55.169 FPS and median interarrival was 18.117 ms.
- Frame delivery, timing, and format were effectively indistinguishable from active playback.

Because lower-level signals were insufficient, a second 15-second run collected aggregate content metrics without saving frames:

- 829 frames produced 828 temporal comparisons.
- Median and 95th-percentile temporal mean absolute difference were both 0.0.
- 825 comparisons were near-identical, a fraction of 0.996377.
- Mean sampled luma had a median and maximum of exactly 62.027.
- Minimum luma was 0.0 and maximum temporal difference was 62.027, consistent with a brief startup transition into a fixed fallback frame.

The WARRKY adapter therefore continues normal frame delivery in standby but appears to emit a static fallback image. Device-open state, read success, frame timing, and resolution cannot distinguish active playback from standby on their own.

## Topology finding

The production HDMI path is:

    Roku Ultra
      -> HDMI splitter
           -> television
           -> WARRKY USB capture device -> Raspberry Pi

The splitter outputs are independent. Turning off the television does not stop the Roku output presented to the capture branch. Normal use returns the Roku to its Home screen before TV shutdown, and the Roku can later display its animated aquarium screensaver while the TV remains off.

Consequences:

- Valid, changing capture frames can continue indefinitely while the television is off.
- Video/frame-content activity is not, by itself, a reliable proxy for TV power state in this topology.
- Roku Home, screensaver, black-frame, image-hash, logo, or other content-specific recognition is intentionally excluded as brittle.
- Further content comparison and capture-transition experiments cannot answer the TV-power question and were stopped.

## Diagnostic matrix

| Condition | Observation | TV-power value |
| --- | --- | --- |
| HDMI source actively playing | 828/828 frames; stable 720x480 at 55.161 FPS; moving content | None by itself |
| HDMI source off or in standby | 829/829 frames; same format/timing; static fallback | Can identify this source state, but not TV state |
| TV off, Roku remains active | Roku continues valid HDMI through the independent capture branch and can animate its screensaver | Capture remains active despite TV off |
| Capture transitions | Can describe Roku/capture changes only | Not pursued as a TV-power detector |

The standby measurement remains useful for understanding the adapter, but it must not drive the production TV-power decision.

## HDMI-CEC diagnostic

Ubuntu has kernel CEC support:

- /dev/cec0 maps to vc4-hdmi-0 and DRM connector card1-HDMI-A-1.
- /dev/cec1 maps to vc4-hdmi-1 and DRM connector card1-HDMI-A-2.
- The vc4 and cec kernel modules are loaded.
- Both Pi HDMI connectors report disconnected and disabled with zero-byte EDID.
- A temporary, uninstalled cec-ctl 1.26.1 query reported physical address f.f.f.f, logical-address mask 0x0000, and zero logical addresses on both adapters.
- The WARRKY USB device exposes UVC video, USB audio, and HID interfaces. It exposes no CEC adapter.
- The CEC nodes are attached to the Pi's disconnected HDMI outputs, not to the USB capture input.

The existing splitter topology provides no CEC path to the Pi. Whether the splitter passes CEC between its HDMI source and television ports does not help because the Pi is connected only through USB capture, and that device does not transport CEC. Direct television power queries over HDMI-CEC are therefore unavailable with the existing wiring and Ubuntu device topology.

A future physical connection from a Pi HDMI port or dedicated supported CEC adapter into the television's CEC bus could change this conclusion and would require a new topology-specific validation. No such hardware change is required for the initial design.

## Milestone decision

1. Automatic capture-based TV-power detection is not viable with the current topology.
2. Direct HDMI-CEC television power detection is not available with the current wiring.
3. Content-specific heuristics must not be used to infer TV power.
4. The first production trigger should be an explicit desired-state command independent of capture activity.
5. The Ambilight lifecycle must accept desired state through a modular provider boundary.

The future control surface should support:

- Ambilight ON
- Ambilight OFF
- Ambilight STATUS

A small local API, Unix socket, or command interface can provide this control. Homebridge/HomeKit can later expose it as an Ambilight switch, and later automation may supply a reliable TV/Roku state. HomeKit integration is outside Milestone 1 and is not implemented here.

The controller should normalize every trigger into desired enabled/disabled state plus source and timestamp. Its lifecycle state machine should respond to that normalized state without knowing whether it came from CEC, Homebridge, a local command/API, or another automation source.

## Recommendation

Proceed with explicit manual enable/disable control as the initial production design. Keep the capture stream responsible for Ambilight color data only after enablement. Preserve a provider interface so reliable automation can be added later without changing Hue session, capture, cleanup, or light-restoration logic.

CEC should remain an optional future provider that is disabled in the present topology. Milestone 2 should define the configuration and dependency boundary for providers and the local control surface, but must not implement HomeKit integration without separate authorization.

## Remaining unknowns

- Which local control transport best balances simplicity, systemd operation, and Homebridge access.
- Whether Homebridge already has a reliable Roku/TV state source suitable for later automation.
- Whether future hardware changes will place a Pi-supported CEC adapter on the television's CEC bus.
- How competing or stale desired-state commands should be prioritized and expired.
