# Milestone 7: systemd appliance deployment

## Installed layout

The deployment is native to Ubuntu and does not use a container. The installer
creates a locked `harmonize` system account whose only supplementary group is
`video`, then installs these paths:

- `/opt/harmonize/app`: root-owned application snapshot
- `/opt/harmonize/venv`: root-owned copy of the validated Python environment
- `/etc/harmonize/harmonize.toml`: `0640 root:harmonize` configuration
- `/etc/harmonize/client.json`: `0600 harmonize:harmonize` Hue credentials
- `/var/lib/harmonize`: private persistent light-state journal directory
- `/run/harmonize`: private runtime, health, and control-socket directory
- `/etc/systemd/system/harmonize.service`: hardened service unit

The capture configuration uses the WARKKY device's stable
`/dev/v4l/by-id/...-video-index0` name. The service resolves the Entertainment
area named exactly `TV area` before accepting control commands. Its
`ExecStartPost` readiness check means a successful `systemctl start` does not
return until the owner-only control socket answers `STATUS`.

## Install

From the repository root, with the validated environment at
`/home/pi/harmonize_env` and the local ignored credential file still mode
`0600`:

```console
sudo ./deploy/install-systemd.sh client.json
```

The installer deliberately refuses to replace an existing unit, account,
application directory, or configuration directory. This Pi had none of those
targets before Milestone 7, so no backup was needed.

## Operate

The service starts at boot in `IDLE`. It does not start Ambilight until an
explicit provider requests ON.

```console
sudo systemctl start harmonize.service
sudo systemctl stop harmonize.service
sudo systemctl restart harmonize.service
systemctl status harmonize.service
journalctl -u harmonize.service --no-pager
```

Send local commands as the service identity so the private socket remains
owner-only:

```console
sudo -u harmonize /opt/harmonize/venv/bin/python /opt/harmonize/app/tools/harmonize_control.py STATUS --config=/etc/harmonize/harmonize.toml
sudo -u harmonize /opt/harmonize/venv/bin/python /opt/harmonize/app/tools/harmonize_control.py ON --config=/etc/harmonize/harmonize.toml
sudo -u harmonize /opt/harmonize/venv/bin/python /opt/harmonize/app/tools/harmonize_control.py OFF --config=/etc/harmonize/harmonize.toml
```

Explicit OFF and service stop leave every light in `TV area` powered off.
Exceptional startup/runtime cleanup retains the configured restore policy.

## Recovery and rollback

systemd restarts an unexpected failure after five seconds and limits repeated
starts to three per minute. It does not restart after a clean operator stop.
Inspect `systemctl status` and the journal before clearing a persistent fault.

To restore the exact pre-Milestone-7 host state, run from the same repository
revision whose unit is installed:

```console
sudo ./deploy/uninstall-systemd.sh
```

The guarded uninstaller refuses an unrecognized unit or account. On success it
disables and stops only `harmonize.service`, removes only the paths listed
above, deletes the dedicated account, reloads systemd, and leaves the original
ignored repository `client.json` untouched. Reinstall with the install command
afterward if appliance operation is still wanted.

## Validation record

Milestone 7 was tested on the Raspberry Pi 5 with the configured WARKKY capture
device and only the Hue Entertainment area `TV area`:

- 97 offline tests passed, including deployment invariants, stable capture-path
  handling, and readiness retry/timeout behavior.
- `systemd-analyze verify deploy/harmonize.service` passed without errors.
- The enabled service ran as the locked `harmonize` identity with only its
  primary group and supplementary `video` access. Application files were
  root-owned; configuration, credentials, runtime, and state permissions
  matched the layout above.
- `systemd-analyze security` reported exposure level `2.4 OK`.
- IDLE used about 38--40 MiB service memory and seven to ten tasks. STREAMING
  used about 45 MiB current/49 MiB peak service memory, 13 tasks, and about 32%
  of one CPU in the observed sample.
- Area resolution completed unattended, and the control socket became usable
  before `systemctl start` returned.
- ON reached STREAMING and both lights visibly followed captured video. OFF and
  service stop left both lights visibly off; recent logs show bounded capture,
  Hue, state-journal, and supervisor cleanup without credential values.
- A forced main-process `SIGKILL` produced one restart after the configured
  five-second delay (`NRestarts=1`) and returned to active/running without a
  tight loop.
- A focused clean stop completed in 0.186 seconds. A later stop from STREAMING
  completed successfully in about 1.3 seconds and applied `off` to two lights.
- One earlier restart required systemd's stop timeout and SIGKILL. Immediate
  focused repetition did not reproduce it; the anomaly is retained here for
  future soak testing rather than hidden.
- The service finished installed, enabled, active, and running. Full reboot
  behavior remains part of the project's final validation milestone.
- Guarded uninstall tooling and the reinstall procedure exist, but the owner
  accepted Milestone 7 with live uninstall/reinstall validation intentionally
  skipped.

Docker, AirPrint, and host CUPS were explicitly outside Milestone 7 scope. They
were not inspected and do not require routine Harmonize milestone checks unless
a future change directly causes a relevant unexpected system-wide issue.
