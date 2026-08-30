# Gokapi-FileShare

Three small, independent file-sharing services for handing files to friends in mainland China from a Shenzhen ECS box — a browsable folder, one-off private links, and expiring links with an admin UI. Each is its own Docker Compose service with no shared database or cloud dependency.

Deliberately reachable by bare IP, not a domain — mainland China requires ICP filing for anything served at a domain name, and a bare IP sidesteps that entirely.

## The three apps

| App | Port | What it's for | Source |
|---|---|---|---|
| [`fileshare/`](fileshare/) | 8080 | Browsable directory listing + password-gated upload page | Custom Python (stdlib only) |
| [`quickshare-sz/`](quickshare-sz/) | 9000 | Private one-off links — no listing, the link is the only way in | Custom Python (stdlib only), local clone of [quickshare](https://github.com/zzpy20/quickshare) |
| [`gokapi/`](gokapi/) | 9001 | Expiring links with a real admin UI, encrypted at rest | [Gokapi](https://github.com/Forceu/Gokapi) |

`fileshare` and `quickshare-sz` replaced [Filebrowser](https://github.com/filebrowser/filebrowser), then [Alist](https://github.com/AlistGo/alist) — Filebrowser archives 2026-09-01 with no further releases, and Alist ended up being more than this needed. `gokapi` was added afterward as a maintained, feature-richer alternative to `quickshare-sz`, run side-by-side for comparison rather than as a replacement.

## Running one

Each app directory is self-contained:

```bash
cd fileshare        # or quickshare-sz, or gokapi
cp .env.example .env    # fileshare / quickshare-sz only — edit in real values
docker compose up -d --build
```

**gokapi** doesn't use `.env` — its admin account is created on first boot via its own `/setup` wizard in the browser, not environment variables. Its default `docker-compose.yml` pulls the upstream `f0rc3/gokapi` image directly; if that registry is blocked on your network (see below), use `docker-compose.china.yml` instead.

### The mainland China Docker Hub wrinkle

Official images (`python:3.12-alpine`, `alpine:latest`) pull fine through China-side Docker registry mirrors. Third-party namespaced images — like `f0rc3/gokapi` — get a `403` from the `docker.m.daocloud.io` mirror, and the once-common `hub-mirror.c.163.com` mirror is dead (its hostname doesn't even resolve anymore). GitHub's release-asset CDN (`release-assets.githubusercontent.com`) is also unreachable directly from mainland China.

The workaround, wired up as `gokapi/docker-compose.china.yml`:

1. On a machine with normal internet access — **not** the target server — run `gokapi/fetch-binary.sh` to download the Gokapi release binary.
2. `scp` the resulting `gokapi/bin/` directory to the server.
3. `docker compose -f docker-compose.china.yml up -d --build` — this builds a thin local image wrapping the binary instead of pulling a prebuilt one.

## Docs

Four reference pages, published as standalone HTML (also mirrored in [`docs/`](docs/) here):

- **[File Share Cheat Sheet](https://claude.ai/code/artifact/e0ffbb05-7912-46d4-9e32-88af1983508e)** — the original quick-reference for fileshare + quickshare-sz, predates gokapi
- **[IP Change Checklist](https://claude.ai/code/artifact/4572cf93-e3fb-4301-9ac8-b621ca557c24)** — what to do within a minute of the server's IP changing
- **[Where Your Files Live](https://claude.ai/code/artifact/cf65ae65-3f4d-4419-9363-641fc6804a09)** — storage paths, add/remove commands, and retention per app
- **[New Box, Same Stack](https://claude.ai/code/artifact/0375cdf1-bd99-4319-a3db-c5ff5ffdd205)** — replicating all three apps onto a fresh Ubuntu box

## Security notes

- Every credential in this repo's compose files is a placeholder read from a **gitignored** `.env` — real values live only on the deployed server, never in git history.
- `gokapi`'s data directory is encrypted at rest (Level 1 — local key, so the container still restarts unattended after a crash or reboot without manual intervention).
- `fileshare` and `quickshare-sz` store files unencrypted, as plain filesystem paths — access control is entirely "does the link/password/token, whichever the app uses."
