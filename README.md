# Gokapi-FileShare

**[English](#english)** · **[简体中文](#简体中文)**

---

<a id="english"></a>
## English

Two small, independent file-sharing services for handing files to friends in mainland China from a Shenzhen ECS box — a browsable folder, and expiring links with an admin UI. Each is its own Docker Compose service with no shared database or cloud dependency.

Deliberately reachable by bare IP, not a domain — mainland China requires ICP filing for anything served at a domain name, and a bare IP sidesteps that entirely.

### The two apps

| App | Port | What it's for | Source |
|---|---|---|---|
| [`fileshare/`](fileshare/) | 8080 | Browsable directory listing + password-gated management page (upload / rename / delete / copy-link) | Custom Python (stdlib only) |
| [`gokapi/`](gokapi/) | 9001 | Expiring links with a real admin UI, encrypted at rest | [Gokapi](https://github.com/Forceu/Gokapi) |

`fileshare` replaced [Filebrowser](https://github.com/filebrowser/filebrowser), then [Alist](https://github.com/AlistGo/alist) — Filebrowser archives 2026-09-01 with no further releases, and Alist ended up being more than this needed. `gokapi` was added afterward to cover one-off private links with real expiry, a role a since-removed companion app (`quickshare-sz`) used to fill.

### Running one

Each app directory is self-contained:

```bash
cd fileshare        # or gokapi
cp .env.example .env    # fileshare only — edit in real values
docker compose up -d --build
```

**gokapi** doesn't use `.env` — its admin account is created on first boot via its own `/setup` wizard in the browser, not environment variables. Its default `docker-compose.yml` pulls the upstream `f0rc3/gokapi` image directly; if that registry is blocked on your network (see below), use `docker-compose.china.yml` instead.

#### The mainland China Docker Hub wrinkle

Official images (`python:3.12-alpine`, `alpine:latest`) pull fine through China-side Docker registry mirrors. Third-party namespaced images — like `f0rc3/gokapi` — get a `403` from the `docker.m.daocloud.io` mirror, and the once-common `hub-mirror.c.163.com` mirror is dead (its hostname doesn't even resolve anymore). GitHub's release-asset CDN (`release-assets.githubusercontent.com`) is also unreachable directly from mainland China.

The workaround, wired up as `gokapi/docker-compose.china.yml`:

1. On a machine with normal internet access — **not** the target server — run `gokapi/fetch-binary.sh` to download the Gokapi release binary.
2. `scp` the resulting `gokapi/bin/` directory to the server.
3. `docker compose -f docker-compose.china.yml up -d --build` — this builds a thin local image wrapping the binary instead of pulling a prebuilt one.

#### Translating the public pages (Shenzhen box only)

The Shenzhen deployment serves a mainland Chinese audience, so its public download/password pages are translated to Simplified Chinese via [`gokapi/custom/public.js`](gokapi/custom/public.js) — Gokapi's supported no-rebuild customization hook (it auto-loads any `custom/public.js` it finds, mounted at `/app/custom` in `docker-compose.china.yml`). Its `PublicName` config value is also set to `深圳文件快传` instead of an English name. This is scoped to that one deployment on purpose — other boxes running this repo keep the English UI unless you copy `custom/public.js` over and mount it the same way.

### Docs

Four reference pages, published as standalone HTML (also mirrored in [`docs/`](docs/) here — English only, regardless of which repo language section you're reading):

- **[File Share Cheat Sheet](https://claude.ai/code/artifact/e0ffbb05-7912-46d4-9e32-88af1983508e)** — the original quick-reference for fileshare
- **[IP Change Checklist](https://claude.ai/code/artifact/4572cf93-e3fb-4301-9ac8-b621ca557c24)** — what to do within a minute of the server's IP changing
- **[Where Your Files Live](https://claude.ai/code/artifact/cf65ae65-3f4d-4419-9363-641fc6804a09)** — storage paths, add/remove commands, and retention per app
- **[New Box, Same Stack](https://claude.ai/code/artifact/0375cdf1-bd99-4319-a3db-c5ff5ffdd205)** — replicating both apps onto a fresh Ubuntu box

### Security notes

- Every credential in this repo's compose files is a placeholder read from a **gitignored** `.env` — real values live only on the deployed server, never in git history.
- `gokapi`'s data directory is encrypted at rest (Level 1 — local key, so the container still restarts unattended after a crash or reboot without manual intervention).
- `fileshare` stores files unencrypted, as plain filesystem paths — access control is entirely "does the link/password, whichever the app uses."

[↑ Back to top](#gokapi-fileshare)

---

<a id="简体中文"></a>
## 简体中文

两个独立的小型文件共享服务，用于从深圳 ECS 向国内朋友分享文件——可浏览目录，以及带管理界面的到期链接。每个都是独立的 Docker Compose 服务，没有共享数据库或云端依赖。

刻意通过裸 IP 访问，而非域名——中国大陆要求任何通过域名对外提供服务的站点完成 ICP 备案，裸 IP 完全绕开了这项要求。

### 两个应用

| 应用 | 端口 | 用途 | 源码 |
|---|---|---|---|
| [`fileshare/`](fileshare/) | 8080 | 可浏览目录列表 + 密码保护的管理页面（上传 / 改名 / 删除 / 复制链接） | 自定义 Python（仅标准库） |
| [`gokapi/`](gokapi/) | 9001 | 带真正管理界面、静态加密的到期链接 | [Gokapi](https://github.com/Forceu/Gokapi) |

`fileshare` 先后替代了 [Filebrowser](https://github.com/filebrowser/filebrowser) 和 [Alist](https://github.com/AlistGo/alist)——Filebrowser 将于 2026-09-01 归档、不再有后续发布，而 Alist 的功能则超出了实际需求。`gokapi` 是之后加入的，用来覆盖一次性私密链接、带真正到期机制的场景——这个角色以前由已下线的伴生应用 `quickshare-sz` 承担。

### 运行某个应用

每个应用目录都是自包含的：

```bash
cd fileshare        # 或 gokapi
cp .env.example .env    # 仅 fileshare 需要——填入真实值
docker compose up -d --build
```

**gokapi** 不使用 `.env`——它的管理员账号是首次启动时通过浏览器里的 `/setup` 向导创建的，而不是环境变量。它默认的 `docker-compose.yml` 直接拉取上游 `f0rc3/gokapi` 镜像；如果你的网络屏蔽了该镜像仓库（见下文），改用 `docker-compose.china.yml`。

#### 中国大陆 Docker Hub 的坑

官方镜像（`python:3.12-alpine`、`alpine:latest`）通过国内 Docker 镜像源都能正常拉取。但第三方命名空间的镜像——比如 `f0rc3/gokapi`——会被 `docker.m.daocloud.io` 镜像源返回 `403`，而曾经常用的 `hub-mirror.c.163.com` 镜像源已经失效（连域名都解析不出来）。GitHub 的发布资源 CDN（`release-assets.githubusercontent.com`）在中国大陆也无法直接访问。

对应的解决方案，已经写成了 `gokapi/docker-compose.china.yml`：

1. 在一台能正常访问互联网的机器上——**不是**目标服务器——运行 `gokapi/fetch-binary.sh` 下载 Gokapi 的发布二进制文件。
2. 把生成的 `gokapi/bin/` 目录通过 `scp` 传到服务器上。
3. 执行 `docker compose -f docker-compose.china.yml up -d --build`——这会基于该二进制文件在本地构建一个精简镜像，而不是拉取预先构建好的镜像。

#### 公开页面翻译（仅限深圳服务器）

深圳部署面向中国大陆用户，因此其公开下载页 / 密码验证页通过 [`gokapi/custom/public.js`](gokapi/custom/public.js) 翻译成简体中文——这是 Gokapi 官方支持的免重新构建自定义方式（只要在 `/app/custom` 下挂载一个 `custom/public.js`，Gokapi 会自动加载它，`docker-compose.china.yml` 里已经配好了这个挂载）。同时把 `PublicName` 配置项改成了「深圳文件快传」而不是英文名称。这个改动只作用于这一台服务器——用本仓库部署的其他服务器默认仍是英文界面，除非你把 `custom/public.js` 复制过去并按同样方式挂载。

### 文档

四份参考文档，已发布为独立 HTML 页面（同时也镜像在本仓库的 [`docs/`](docs/) 目录下——文档内容均为英文，与你正在阅读的语言区块无关）：

- **[File Share Cheat Sheet](https://claude.ai/code/artifact/e0ffbb05-7912-46d4-9e32-88af1983508e)** —— fileshare 最初的速查文档
- **[IP Change Checklist](https://claude.ai/code/artifact/4572cf93-e3fb-4301-9ac8-b621ca557c24)** —— 服务器 IP 变更后一分钟内该做的事
- **[Where Your Files Live](https://claude.ai/code/artifact/cf65ae65-3f4d-4419-9363-641fc6804a09)** —— 每个应用的存储路径、增删命令与保留策略
- **[New Box, Same Stack](https://claude.ai/code/artifact/0375cdf1-bd99-4319-a3db-c5ff5ffdd205)** —— 如何把两个应用迁移到一台全新的 Ubuntu 主机上

### 安全说明

- 本仓库 compose 文件中的所有凭据都只是占位符，真实值从被 gitignore 排除在外的 `.env` 文件中读取——真实值只存在于已部署的服务器上，从未进入 git 历史记录。
- `gokapi` 的数据目录是静态加密的（Level 1——密钥保存在本地，因此容器在崩溃或重启后仍能无人值守自动恢复）。
- `fileshare` 未加密存储文件，直接以明文文件系统路径存放——访问控制完全依赖链接和密码。

[↑ 返回顶部](#gokapi-fileshare)
