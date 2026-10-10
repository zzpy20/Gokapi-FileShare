# Gokapi-FileShare: working notes

Context for continuing work in this repo. Until 2026-10-11 the work below was done from a
session opened in the sibling repo `/Users/alan/Projects/Shenzhen-Reality` (the proxy that
runs on the same two boxes), so that session's history is not visible from here. This file
carries over what it knew.

This repo is public. Never write a password, API key, share-folder name or home IP into any
tracked file, this one included.

## What runs where

| Service | Box | Address | Source |
|---|---|---|---|
| `fileshare` | Shenzhen (`ssh sz`) | `http://47.107.139.170:8080/admin` | `fileshare/` |
| `gokapi` (Chinese public pages) | Shenzhen (`ssh sz`) | `http://47.107.139.170:9001/admin` | `gokapi/` + `docker-compose.china.yml` |
| `gokapi` (upstream image, v2.2.4) | Singapore (`ssh sg`) | `http://singapore.1000600.xyz:9001/admin` | `gokapi/docker-compose.yml` |

- On the boxes the files live in `/root/fileshare` and `/root/gokapi`. Shared files are in
  `/root/fileshare/shared`.
- Both boxes also run the Shenzhen-Reality proxy containers. `toggle.sh both down` in that
  repo stops only the proxy; the file services keep running.
- The Singapore box is a spot instance, so its IP can change; the hostname follows it. The
  Shenzhen IP is an EIP. `docs/ip-change-checklist.html` covers what to update.
- Both services are plain HTTP.

## Passwords

- The master copy of every credential is the gitignored `.env` at the repo root (mode 600).
  Keys: `SZ_FILESHARE_URL`, `SZ_FILESHARE_UPLOAD_URL`, `SZ_FILESHARE_USER`,
  `SZ_FILESHARE_PASS`, `SZ_FILESHARE_VIEW_PASS` (empty), `SZ_GOKAPI_URL`, `SZ_GOKAPI_USER`,
  `SZ_GOKAPI_PASS`, `SZ_GOKAPI_API_KEY`, and the same five `SG_GOKAPI_*`.
- Read values from it in scripts; do not print them.
- Exception: `/root/fileshare/docker-compose.yml` on the Shenzhen box has `UPLOAD_USER` and
  `UPLOAD_PASS` written in directly, so it differs from the repo's `${...}` version. Do not
  copy the repo's compose file over it.
- Per-folder viewing passwords are set on the management page and stored on the box as
  `.fileshare-password` inside each top-level folder. They are not in `.env`.
- Gokapi admin reset: stop the container, run it once with `--deployment-password` (on the
  upstream image the command is `/app/run.sh --deployment-password`). Both were reset on
  2026-10-10. The non-admin `alan` user on the Shenzhen Gokapi has an unknown password.

## fileshare

One file, `fileshare/server.py`, standard library only, plus the vendored
`fileshare/qrcode.min.js` (qrcode-generator 1.4.4, MIT).

- `ThreadingHTTPServer` with `ShareHandler`, a `SimpleHTTPRequestHandler` subclass.
- Pages are `str.format` templates. JavaScript lives in separate plain-string constants
  (`LIGHTBOX_SCRIPT`, `QR_SCRIPT`, `COPY_SCRIPT`, `MANAGE_SCRIPT`, `UPLOAD_SCRIPT`) so its
  braces need no doubling.
- Admin (`/admin` redirects to `/upload`) uses Basic auth from `UPLOAD_USER`/`UPLOAD_PASS`.
- Visitors: the top level is not listed. Each top-level folder can have its own viewing
  password (cookie, 30 days) and an expiry date after which a background sweep deletes it.
  `VIEW_PASS` is an optional site-wide password, currently unset.
- Five wrong passwords from one address lock it out for 10 minutes, admin login included.
- Dot-files return 404. Uploads never overwrite: a clash becomes `name (1).ext`.
- Listing rows: thumbnail, copy link, QR code, download. Images open in an in-page viewer
  with arrows, keys and swipe. The management page has the same viewer and QR button.

### Deploy

```bash
scp fileshare/server.py fileshare/qrcode.min.js fileshare/Dockerfile sz:/root/fileshare/
ssh sz 'cd /root/fileshare && docker compose up -d --build'
```

### Test locally before deploying

```bash
cd fileshare && SHARE_DIR=/path/to/scratch PORT=18765 UPLOAD_PASS=test exec python3 server.py
```

- Stop it afterwards with `lsof -ti tcp:18765 | xargs kill`; a leftover server gives false
  results on the next run.
- Check page scripts by extracting the `<script>` blocks and running `node --check`.
- Screenshots: headless Chrome (`--headless=new --screenshot`). It cannot render narrower
  than about 500px, so phone-width layout has not been checked that way.

## gokapi

- The bare address redirects to GitHub (Gokapi's default `RedirectUrl`); the admin page is
  `/admin`.
- `bash gokapi/clear-all.sh <sg|sz> [-y]` deletes every stored file through the API, using
  the URL and API key from `.env`.
- Shenzhen pulls from Docker Hub unreliably; see the README's "Docker Hub wrinkle".

## Docs

- `README.md` (English) and `README_CN.md` (Chinese) are separate files with a switcher
  line under the title. Always update both.
- The four pages in `docs/` are also published as artifacts. After editing one, republish it
  to the same link by passing `url`:
  - `file-share-cheat-sheet.html`: https://claude.ai/artifact/UnToVdrGLAKDVPxEXXx2GD
  - `ip-change-checklist.html`: https://claude.ai/artifact/9aPyPhJSa6WvhcMdoQnoR5
  - `where-files-live.html`: https://claude.ai/artifact/ScQ1oZJnygbWF7bEinoQkp
  - `new-box-same-stack.html`: https://claude.ai/artifact/1RnMsUccKRwRdvmU7yzTeL

## How Alan works

- A change means: implement, deploy to the Shenzhen box, update both READMEs and the cheat
  sheet, and leave it uncommitted. Commit and push only when asked.
- Commit straight to `main`; no side branches.
- Prefer the simplest option and explain it in plain terms.

## Work log

Details are in `git log`. Summary of the 2026-10-10 session:

- Collected all credentials into the local `.env`; reset both Gokapi admin passwords;
  removed stale passwords and backups from the boxes.
- Added `gokapi/clear-all.sh`.
- Split the README into English and Chinese files; added "Where to start" and "Which one to
  use"; brought the four `docs/` pages up to date.
- fileshare: download, copy-link and QR buttons; responsive layout up to 1120px; management
  link hidden from visitors; top level unlisted; per-folder passwords; login lockout; folder
  expiry; no silent overwrite; thumbnails; drag-and-drop upload with a progress bar;
  redesigned management page; `/admin` shortcut; image viewer on both pages.
- The site-wide viewing password was switched off once per-folder passwords existed.
- In the Shenzhen-Reality repo: unused firewall ports were closed on both boxes. Ports 8080
  and 9001 stay open for these services.

## Open items

- Not yet tried on a real phone: swipe in the viewer, scanning a QR code, drag and drop,
  phone-width layout. WeChat's browser may warn on a bare-IP HTTP link.
- A new top-level folder has no password until one is set; the management page flags it.
- Plain HTTP on both services.
- The server IP and login addresses are in the public README by choice.
