# Watchdog

Small service that watches the Gluetun stack and restarts qBittorrent (and friends) only when a restart actually helps.

## What it does

| Situation | Action |
|---|---|
| Gluetun down/unhealthy (kill switch working) | Nothing. qBittorrent staying idle is intended |
| Gluetun just came back (also re-armed if its start time changes between two checks) | Waits `parent_healthy_grace` seconds |
| Child started *before* Gluetun's current start (stale network namespace: "Up" but no connectivity) | Restarts the children |
| qBittorrent WebUI unreachable or `connection_status=disconnected` for `bad_after` seconds | Restarts the children |
| qBittorrent login fails (wrong password) | Nothing, shown as unknown |
| Too many restarts (`max_restarts_per_hour`; only real restarts count after a process restart) | Gives up, tells you, stops looping |

Starts in **dry run**: it only logs what it would do. Web page: `http://mediaserver:8099`. Events live in SQLite in `/appdata/watchdog`. Optional ntfy notifications via `NTFY_URL`.

## Deploy

```bash
sudo mkdir -p /appdata/watchdog && sudo chown -R 1000:100 /appdata/watchdog
cd /compose/watchdog          # copy this folder here
cp config.example.yml /appdata/watchdog/config.yml
cp .env.example .env          # fill in QBIT_USER / QBIT_PASS (never commit .env)
docker compose build && docker compose up -d
```

Then edit `/appdata/watchdog/config.yml`: set the qBittorrent URL (it must be reachable from the watchdog's network; since qBittorrent lives inside Gluetun's namespace, that is usually `http://gluetun:8080` if both share a Docker network, or `http://<host-ip>:<published-port>`), and add other containers that share Gluetun to `children`.

Via the OMV compose plugin: paste `compose.yml`, put the env in the env box, and Down → Up.

## Go live

1. Leave `dry_run: true` for a few days. Check the Events table for `dry_run` lines that look wrong.
2. Test on purpose: `docker restart gluetun`, wait ~2 min, confirm the page reports the stale namespace (dry run) and that a real restart of qBittorrent fixes it.
3. Set `dry_run: false`, restart the watchdog.

## Unverified (test before trusting)

- docker-socket-proxy: verified on the real stack that `POST: 0` blocks restarts (its config denies every non-GET unless `POST` is on), so `POST: 1` is required. Trade-off: with `CONTAINERS: 1` + `POST: 1` the proxy also allows creating/deleting containers (path-prefix match), which is effectively root on the host if the watchdog were compromised. Mitigated by an isolated network, no published proxy port, and a UI with no write actions.
- qBittorrent API: `connection_status` values and whether the WebUI answers while the VPN is down (here, unreachable counts as failing, but only after Gluetun has been healthy for the grace period).
- Whether Gluetun's Docker health status is reliable on your setup (`docker inspect gluetun --format '{{.State.Health.Status}}'`).
- Port 8099 free; `docker compose build` works on the server (only the unit tests were run, against mocks).
- Forwarded port after a VPN reconnect: handled by Gluetun's `VPN_PORT_FORWARDING_UP_COMMAND` (verified on ProtonVPN: it retries until qBittorrent is back and then sets the new port), not by the watchdog.

## Tests

```bash
pip install -r requirements.txt pytest && python -m pytest
```
