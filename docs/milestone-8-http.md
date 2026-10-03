# Milestone 8: trusted-LAN HTTP control

## Interface

The adapter listens on all IPv4 interfaces on TCP port `8765` and accepts only
these exact GET request targets:

```text
/?harmonize=on
/?harmonize=off
/?harmonize=status
```

ON and OFF return `{"command":"ON","state":"accepted"}` (or OFF). STATUS
returns the supervisor's current actual state, for example `{"state":"IDLE"}`.
Missing values, unsupported values, alternate paths, duplicate parameters, and
extra parameters return HTTP 400 without reaching the control socket. Non-GET
methods return HTTP 405. An unavailable daemon returns HTTP 503.

There is intentionally no authentication or TLS. Port 8765 must be reachable
only from the owner's trusted LAN. The installer does not alter host firewall
or router settings.

The adapter does not invoke a shell. It runs as the locked `harmonize` account
and calls the existing bounded local-control client for fixed ON, OFF, and
STATUS operations through `/run/harmonize/harmonize.sock`. Its systemd sandbox
hides `/etc/harmonize` and `/var/lib/harmonize`, including Hue credentials and
the light-state journal.

## Install and operate

Install this layer over the accepted Milestone 7 appliance from the repository
root:

```console
sudo ./deploy/install-http.sh
```

The guarded installer accepts files already present when they are
byte-identical to this repository revision, including the adapter and this
document copied by a fresh core installation. It refuses to overwrite any
differing file, and repeated installation from the same revision is safe.

Check it locally without changing desired state:

```console
curl --fail-with-body 'http://127.0.0.1:8765/?harmonize=status'
systemctl status harmonize-http.service
```

The systemd unit requests and starts after `harmonize.service`. It restarts
after unexpected adapter failures. A temporarily unavailable control socket is
reported to callers and never converted into another command.

## Rollback

From the same repository revision used for installation:

```console
sudo ./deploy/uninstall-http.sh
```

The guarded rollback stops and disables only `harmonize-http.service`, then
removes only its recognized unit, adapter, and documentation files. It does
not stop or modify the core Harmonize service, configuration, credentials,
state, or account.

## Validation record

Milestone 8 validation on 2026-09-13 produced these results:

- 15 focused offline HTTP and deployment tests passed. They cover installer
  handling of absent, identical, differing, and symlink destinations; exact target
  mapping, real loopback HTTP requests through a temporary Unix-socket
  provider, concise status, GET-only behavior, rejection of unsupported or
  extra input, unavailable/rejected/invalid daemon responses, unit hardening,
  and guarded deployment boundaries.
- The four existing local-control tests passed unchanged.
- Bash syntax checks passed for installation and rollback, and
  `systemd-analyze verify` passed for both Harmonize units.
- Installation created and enabled `harmonize-http.service`. Both it and
  `harmonize.service` finished enabled, active, and running with zero
  restarts. The adapter listened on `0.0.0.0:8765`.
- Local STATUS returned `{"state":"IDLE"}`. Testing from another device on
  the trusted LAN reached port 8765; the owner confirmed STATUS, ON, and OFF
  all passed, ON activated Ambilight, and OFF powered off both `TV area`
  lights.
- The final HTTP status was IDLE. A credential-safe read-only Hue query
  resolved exactly `TV area` with two channels, reported Entertainment
  inactive, and sent no Entertainment action request.

No Homebridge component or unrelated service was inspected or modified. The
full offline suite was not rerun; validation stayed within the focused
Milestone 8 scope.
