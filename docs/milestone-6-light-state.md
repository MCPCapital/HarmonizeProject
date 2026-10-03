# Milestone 6: Hue light-state management

Milestone 6 adds session-scoped capture and deterministic post-Ambilight
handling for the individual Hue lights in the exactly resolved Entertainment
area. It was developed on `m6-light-state` from accepted Milestone 5 commit
`66d5495`; the implementation checkpoint is `d88e7b7`.

## Implemented behavior

- Exact Entertainment-area light membership resolution.
- Static on/off, brightness, XY color, and valid color-temperature capture
  immediately before Hue Entertainment starts.
- Explicit OFF and daemon/service stop always apply off after a confirmed
  Entertainment stop; exceptional cleanup uses the configured restore/off
  policy with bounded per-light retries.
- Refusal to capture active dynamic scenes, timed effects, effects, or
  unsupported modes that cannot be replayed safely.
- Atomic mode-`0600`, non-secret session journals guarded by session, area, and
  light membership.
- No automatic application of stale crash journals; unresolved journals block
  another ON cycle until a human resolves them.
- Explicit `inspect`, `restore`, `off`, and `discard` recovery commands in
  `tools/harmonize_light_state.py`, with exact-area confirmation and a separate
  stale override.
- Cleanup failures remain visible in supervisor `ERROR` until acknowledged by
  a new OFF command.

The configuration key ambilight.exception_cleanup_behavior defaults to
restore and never changes explicit-stop behavior. The former
post_stream_behavior key is rejected to avoid ambiguous semantics. Accepted
Milestone 5 commit `66d5495` remains the rollback point for behavior without
light-state management.

## Validation

All 87 offline tests pass. Coverage includes static-state round trips, off mode,
journal permissions and symlink rejection, stale and mismatched sessions,
bounded partial failures, uncertain Entertainment stop, cleanup-error
visibility, area membership, and recovery-tool parsing.

The controlled live test on 2026-09-13 targeted only `TV area`, containing Hue
Play lights `TV Right` and `TV Left`. Read-only discovery confirmed
Entertainment inactive and no active dynamic scene or effect. Original states
were saved first in a separate mode-`0600` recovery journal.

The restore baseline was:

- `TV Right`: on, brightness `45.06`, XY `(0.17, 0.34)`.
- `TV Left`: off, stored brightness `39.92`, temperature `300` mirek.

ON reached `STREAMING`, and the user confirmed both lights followed video.
OFF returned to `IDLE`, restored the exact API values, removed the normal
journal, and left Entertainment inactive. The user confirmed the physical
appearance returned without a flash or other odd behavior.

A second cycle used `--inject-failure after_dtls_ready` with zero supervisor
retries. The error remained visible in `ERROR`; bounded cleanup restored the
same baseline, removed the journal, and left Entertainment inactive. The user
confirmed the expected physical state with no flash or lingering Ambilight.

For off-mode testing, both lights began in distinct visible static states. ON
reached `STREAMING`; after OFF, both light resources reported off, the
controller reached `IDLE`, Entertainment was inactive, and the journal was
absent. The user physically confirmed both lights were off.

The guarded recovery tool then restored and verified the original states:

- `TV Right`: on, brightness `1.58`, XY `(0.2826, 0.2853)`.
- `TV Left`: on, brightness `2.37`, XY `(0.422, 0.3607)`.

The known test backup was inspected and explicitly allowed despite exceeding
the stale window. The user confirmed the original physical appearance. Final
checks found Entertainment inactive and no journal, socket, Harmonize process,
or OpenSSL DTLS process.

## Required explicit-stop correction

After the initial validation, Milestone 6 was reopened because normal user OFF
had restored pre-session state. The corrected contract is:

- local OFF and daemon/service stop turn every light in the configured area off;
- startup/runtime failure applies ambilight.exception_cleanup_behavior,
  defaulting to restore;
- uncertain Entertainment stop applies neither policy and retains the journal.

The prior normal-restore observation above is historical evidence for the
restore mechanism, not the corrected explicit-OFF behavior.

Focused live correction validation on 2026-09-13 saved the original state in a
separate mode-0600 recovery journal, then set both TV area lights to visible
static states. ON reached STREAMING and the user confirmed both followed video.
Explicit OFF reached IDLE, left Entertainment inactive, removed the session
journal, and Hue GET reported both light resources powered off. The user
confirmed both remained completely dark until they were independently changed
for the next test.

Both lights were then independently set to visible states (right brightness
45.06 and left brightness 54.94). A zero-retry after_dtls_ready startup failure
latched ERROR; exceptional cleanup restored both visible states, removed the
journal, and left Entertainment inactive. The user physically confirmed the
restoration with no lingering Ambilight behavior.

Finally, the guarded recovery path restored the original both-off correction
baseline. The user confirmed the original appearance. Final checks found
Entertainment inactive and no journal, socket, Harmonize process, or OpenSSL
DTLS process. The corrected suite passes 89 offline tests.

## Manual recovery

1. Stop only the configured area with
   `tools/stop_entertainment.py --config <config>`.
2. Query Hue and require that exact area to report `inactive`.
3. Inspect any journal with
   `tools/harmonize_light_state.py inspect --config <config>`.
4. Restore only with the exact-area guard:
   `restore --config <config> --confirm-area "TV area"`. Use
   `--allow-stale` only after confirming the saved state is still appropriate.
5. Re-query every affected light and Entertainment status. Retain the journal
   after any partial restore and report the exact failed light and field.
6. Stop the daemon and verify its socket and Harmonize/DTLS processes are gone.

Never discard an unresolved journal merely to permit another ON cycle.
External changes made while Ambilight owns the lights cannot be distinguished
reliably from the stream; send Ambilight OFF before changing them elsewhere.
Dynamic scenes/effects are intentionally unsupported for restore, and future
gradient or segmented products require separate validation.
