# Gokapi-FileShare

[English](README.md) | [中文](README_CN.md)


Two small, independent file-sharing services for handing files to friends in mainland China from a Shenzhen ECS box — a browsable folder, and expiring links with an admin UI. Each is its own Docker Compose service with no shared database or cloud dependency.

Deliberately reachable by bare IP, not a domain — mainland China requires ICP filing for anything served at a domain name, and a bare IP sidesteps that entirely.

## The two apps

| App | Port | What it's for | Source |
|---|---|---|---|
| [`fileshare/`](fileshare/) | 8080 | Browsable folders — the top level is not listed for visitors, so someone can only open a folder or file whose exact link they were given (and everything inside that folder), and an optional shared viewing password (`VIEW_PASS`) can be required before anything opens; each row has a copy-direct-link button and, for files, a download button; clicking a name opens the file in the browser — plus a password-gated management page (upload / rename / delete / copy-link). Image files show a small thumbnail. Layout adapts from phones up to 1120px wide | Custom Python (stdlib only) |
| [`gokapi/`](gokapi/) | 9001 | Expiring links with a real admin UI, encrypted at rest | [Gokapi](https://github.com/Forceu/Gokapi) |

`fileshare` replaced [Filebrowser](https://github.com/filebrowser/filebrowser), then [Alist](https://github.com/AlistGo/alist) — Filebrowser archives 2026-09-01 with no further releases, and Alist ended up being more than this needed. `gokapi` was added afterward to cover one-off private links with real expiry, a role a since-removed companion app (`quickshare-sz`) used to fill.

**Gokapi's bare address redirects away on purpose.** Opening `http://<host>:9001/` sends you to Gokapi's GitHub page — it has no public home page, and its `RedirectUrl` setting (in `gokapi/config/config.json` on the box) is still the default. That is not a fault. The admin login is at `http://<host>:9001/admin`; shared files use their own download links.

## Running one

Each app directory is self-contained:

```bash
cd fileshare        # or gokapi
cp .env.example .env    # fileshare only — edit in real values
docker compose up -d --build
```

**gokapi** doesn't use `.env` — its admin account is created on first boot via its own `/setup` wizard in the browser, not environment variables. Its default `docker-compose.yml` pulls the upstream `f0rc3/gokapi` image directly; if that registry is blocked on your network (see below), use `docker-compose.china.yml` instead.

### The mainland China Docker Hub wrinkle

Official images (`python:3.12-alpine`, `alpine:latest`) pull fine through China-side Docker registry mirrors. Third-party namespaced images — like `f0rc3/gokapi` — get a `403` from the `docker.m.daocloud.io` mirror, and the once-common `hub-mirror.c.163.com` mirror is dead (its hostname doesn't even resolve anymore). GitHub's release-asset CDN (`release-assets.githubusercontent.com`) is also unreachable directly from mainland China.

The workaround, wired up as `gokapi/docker-compose.china.yml`:

1. On a machine with normal internet access — **not** the target server — run `gokapi/fetch-binary.sh` to download the Gokapi release binary.
2. `scp` the resulting `gokapi/bin/` directory to the server.
3. `docker compose -f docker-compose.china.yml up -d --build` — this builds a thin local image wrapping the binary instead of pulling a prebuilt one.

### Translating the public pages (Shenzhen box only)

The Shenzhen deployment serves a mainland Chinese audience, so its public download/password pages are translated to Simplified Chinese via [`gokapi/custom/public.js`](gokapi/custom/public.js) — Gokapi's supported no-rebuild customization hook (it auto-loads any `custom/public.js` it finds, mounted at `/app/custom` in `docker-compose.china.yml`). Its `PublicName` config value is also set to `深圳文件快传` instead of an English name. This is scoped to that one deployment on purpose — other boxes running this repo keep the English UI unless you copy `custom/public.js` over and mount it the same way.

Gokapi caches `custom/public.js` for 2 days, so after editing it on the server, bump `custom/version.txt` (a plain integer, e.g. `echo 2 > version.txt`) and restart the container — this changes the script's URL and forces every client to fetch the new version instead of a stale cached copy.

### Deleting every Gokapi file at once

Gokapi's admin page only has a per-file delete button. [`gokapi/clear-all.sh`](gokapi/clear-all.sh) clears a whole box in one go through Gokapi's API — run it from your Mac, from the repo root:

```bash
bash gokapi/clear-all.sh sg      # Singapore box
bash gokapi/clear-all.sh sz      # Shenzhen box
bash gokapi/clear-all.sh sg -y   # skip the confirmation question
```

It lists every stored file, asks you to type `yes`, deletes them all (every share link stops working — there is no undo), then reports how many are left. It reads `SG_GOKAPI_URL` + `SG_GOKAPI_API_KEY` (or the `SZ_` pair) from the gitignored `.env` at the repo root; create the key in the admin page's API Keys menu with permission to view and delete files. Requires `curl` and `jq`.

## Docs

Four reference pages, published as standalone HTML (also mirrored in [`docs/`](docs/) here — English only, whichever README you're reading):

- **[File Share Cheat Sheet](https://claude.ai/code/artifact/e0ffbb05-7912-46d4-9e32-88af1983508e)** — the original quick-reference for fileshare
- **[IP Change Checklist](https://claude.ai/code/artifact/4572cf93-e3fb-4301-9ac8-b621ca557c24)** — what to do within a minute of the server's IP changing
- **[Where Your Files Live](https://claude.ai/code/artifact/cf65ae65-3f4d-4419-9363-641fc6804a09)** — storage paths, add/remove commands, and retention per app
- **[New Box, Same Stack](https://claude.ai/code/artifact/0375cdf1-bd99-4319-a3db-c5ff5ffdd205)** — replicating both apps onto a fresh Ubuntu box

## Security notes

- Every credential in this repo's compose files is a placeholder read from a **gitignored** `.env` — real values never enter git history. The master copy of every password (fileshare's upload login and both boxes' Gokapi admin logins) is the gitignored `.env` at the root of the local clone on Alan's Mac. A forgotten Gokapi admin password can't be read back from the box (only a hash is stored) — reset it with `gokapi --deployment-password <new>` while the container is stopped, then save the new value in that `.env`. One exception as currently deployed: on the Shenzhen box, `fileshare`'s compose file has its username and password written in directly rather than read from a `.env` — that edited copy exists only on the box, not in this repo.
- `gokapi`'s data directory is encrypted at rest (Level 1 — local key, so the container still restarts unattended after a crash or reboot without manual intervention).
- `fileshare` viewing passwords: `VIEW_PASS` (optional) is one shared password for the whole site, and each top-level folder can have its own password, set on the management page, which replaces the shared one for that folder. Entering one sets a 30-day cookie for that scope; changing a password signs out everyone who used it. After 5 wrong tries from one address (viewing or admin), that address is refused for 10 minutes. Passwords still travel over plain HTTP and folder passwords are stored as plain text on the box, so this keeps out casual visitors and scanners rather than a determined attacker.
- `fileshare` never serves dot-files, never overwrites on upload (a second `a.pdf` is saved as `a (1).pdf`), and refuses a rename or new folder that would collide with an existing name.
- `fileshare` folder expiry: a top-level folder can be given a number of days on the management page; when the time is up the folder and everything in it is deleted automatically, with no undo.
- `fileshare` stores files unencrypted, as plain filesystem paths — access control is entirely "does the link/password, whichever the app uses."
