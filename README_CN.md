# Gokapi-FileShare

[English](README.md) | [中文](README_CN.md)


两个独立的小型文件共享服务，用于从深圳 ECS 向国内朋友分享文件——可浏览目录，以及带管理界面的到期链接。每个都是独立的 Docker Compose 服务，没有共享数据库或云端依赖。

刻意通过裸 IP 访问，而非域名——中国大陆要求任何通过域名对外提供服务的站点完成 ICP 备案，裸 IP 完全绕开了这项要求。

## 从哪里开始

需要登录的几个页面。下面是当前的地址——**服务器的公网 IP 变了，这些地址也会跟着变**，所以哪个打不开了，先确认 IP（见[文档](#文档)里的 IP Change Checklist）。

| 服务器 | 应用 | 从这里进入 |
|---|---|---|
| 深圳 | `fileshare` 管理页面（上传、文件夹、密码、到期） | http://47.107.139.170:8080/admin |
| 深圳 | `gokapi` 管理后台 | http://47.107.139.170:9001/admin |
| 新加坡 | `gokapi` 管理后台 | http://singapore.1000600.xyz:9001/admin |

- 用户名和密码**不在**本仓库里。它们在本地仓库根目录下被 gitignore 排除的 `.env` 里，和这几个地址放在一起（`SZ_FILESHARE_UPLOAD_URL`、`SZ_GOKAPI_URL`、`SG_GOKAPI_URL`）——IP 变了，两处都要更新。
- `fileshare` 的 `/admin` 是个方便记忆的入口，会跳转到它真正的管理地址 `/upload`。
- 深圳的地址故意使用裸 IP（免 ICP 备案）。新加坡的地址用的是域名，该服务器 IP 变化时会自动重新指向。
- 不带 `/admin` 的裸地址不是入口：`:8080/` 对访客什么都不显示，`:9001/` 会跳转到 Gokapi 的 GitHub 页面。

## 两个应用

| 应用 | 端口 | 用途 | 源码 |
|---|---|---|---|
| [`fileshare/`](fileshare/) | 8080 | 可浏览的文件夹——访客看不到顶层列表，只能打开自己拿到确切链接的文件夹或文件（以及该文件夹里的全部内容），还可以设置一个共用的访问密码（`VIEW_PASS`，可选），输对了才能打开任何内容；每一行都有「复制直达链接」按钮，文件还有「下载」按钮；点文件名则直接在浏览器里打开——外加密码保护的管理页面（上传 / 改名 / 删除 / 复制链接）。图片文件会显示缩略图，点开后在页面内的查看器里浏览，可以用屏幕上的箭头、键盘方向键或手指滑动翻看同一文件夹里的图片（管理页面上也一样）。页面宽度自适应，从手机到最宽 1120px | 自定义 Python（仅标准库） |
| [`gokapi/`](gokapi/) | 9001 | 带真正管理界面、静态加密的到期链接 | [Gokapi](https://github.com/Forceu/Gokapi) |

`fileshare` 先后替代了 [Filebrowser](https://github.com/filebrowser/filebrowser) 和 [Alist](https://github.com/AlistGo/alist)——Filebrowser 将于 2026-09-01 归档、不再有后续发布，而 Alist 的功能则超出了实际需求。`gokapi` 是之后加入的，用来覆盖一次性私密链接、带真正到期机制的场景——这个角色以前由已下线的伴生应用 `quickshare-sz` 承担。

**Gokapi 的裸地址是故意跳走的。** 打开 `http://<主机>:9001/` 会被带到 Gokapi 的 GitHub 页面——它没有公开首页，而 `RedirectUrl` 这个设置（在服务器上的 `gokapi/config/config.json` 里）还是默认值。这不是故障。管理员登录入口是 `http://<主机>:9001/admin`；分享出去的文件各有自己的下载链接。

## 该用哪一个

要把一批东西分享给信得过的人，用 `fileshare`；要把某一个文件发给某一个人，用 Gokapi。

| | `fileshare` | `gokapi` |
|---|---|---|
| 最适合 | 一个可以翻看的文件夹：截图、出行资料，朋友自己从里面挑 | 一个文件发给一个人 |
| 链接 | 每个文件夹一个链接，之后往里加文件，链接不变 | 每个文件一个猜不到的链接 |
| 查看方式 | 图片和 PDF 直接在浏览器里打开，带缩略图 | 每个文件一个下载页 |
| 访问控制 | 通用密码或文件夹单独的密码；拿到某个文件夹的链接和密码，就能看到里面的全部内容 | 每个文件可以单独设密码 |
| 到期 | 可选，按顶层文件夹设置天数 | 按文件设置，按天数或下载次数 |
| 服务器上的存储 | 明文文件 | 静态加密 |
| 下载记录 | 没有 | 每个文件有下载次数 |
| 大小限制 | 单次上传 500MB | 大得多（设为 100GB） |

**简单的判断标准：** 如果被陌生人看到会让你不舒服，就用 Gokapi；如果只是图个方便、想放在一处，就用 `fileshare`。护照扫描件、签证材料、合同，应该放在 Gokapi 里并设置到期。

**两者共同的注意事项：** 都没有使用 HTTPS，所以文件和密码在服务器与访客之间是明文传输的。Gokapi 的加密只保护存放在服务器上的文件。真正机密的东西，先打成带密码的压缩包，再通过另一个渠道把密码发过去。

## 运行某个应用

每个应用目录都是自包含的：

```bash
cd fileshare        # 或 gokapi
cp .env.example .env    # 仅 fileshare 需要——填入真实值
docker compose up -d --build
```

**gokapi** 不使用 `.env`——它的管理员账号是首次启动时通过浏览器里的 `/setup` 向导创建的，而不是环境变量。它默认的 `docker-compose.yml` 直接拉取上游 `f0rc3/gokapi` 镜像；如果你的网络屏蔽了该镜像仓库（见下文），改用 `docker-compose.china.yml`。

### 中国大陆 Docker Hub 的坑

官方镜像（`python:3.12-alpine`、`alpine:latest`）通过国内 Docker 镜像源都能正常拉取。但第三方命名空间的镜像——比如 `f0rc3/gokapi`——会被 `docker.m.daocloud.io` 镜像源返回 `403`，而曾经常用的 `hub-mirror.c.163.com` 镜像源已经失效（连域名都解析不出来）。GitHub 的发布资源 CDN（`release-assets.githubusercontent.com`）在中国大陆也无法直接访问。

对应的解决方案，已经写成了 `gokapi/docker-compose.china.yml`：

1. 在一台能正常访问互联网的机器上——**不是**目标服务器——运行 `gokapi/fetch-binary.sh` 下载 Gokapi 的发布二进制文件。
2. 把生成的 `gokapi/bin/` 目录通过 `scp` 传到服务器上。
3. 执行 `docker compose -f docker-compose.china.yml up -d --build`——这会基于该二进制文件在本地构建一个精简镜像，而不是拉取预先构建好的镜像。

### 公开页面翻译（仅限深圳服务器）

深圳部署面向中国大陆用户，因此其公开下载页 / 密码验证页通过 [`gokapi/custom/public.js`](gokapi/custom/public.js) 翻译成简体中文——这是 Gokapi 官方支持的免重新构建自定义方式（只要在 `/app/custom` 下挂载一个 `custom/public.js`，Gokapi 会自动加载它，`docker-compose.china.yml` 里已经配好了这个挂载）。同时把 `PublicName` 配置项改成了「深圳文件快传」而不是英文名称。这个改动只作用于这一台服务器——用本仓库部署的其他服务器默认仍是英文界面，除非你把 `custom/public.js` 复制过去并按同样方式挂载。

Gokapi 会把 `custom/public.js` 缓存 2 天，所以在服务器上改完这个文件后，需要把 `custom/version.txt`（一个纯数字，比如执行 `echo 2 > version.txt`）加一并重启容器——这会让脚本的 URL 发生变化，逼所有客户端重新拉取新版本，而不是继续用缓存里的旧版本。

### 一次删除 Gokapi 的全部文件

Gokapi 的管理页面只有逐个文件的删除按钮。[`gokapi/clear-all.sh`](gokapi/clear-all.sh) 通过 Gokapi 的 API 一次清空整台机器——在 Mac 上、从仓库根目录运行：

```bash
bash gokapi/clear-all.sh sg      # 新加坡服务器
bash gokapi/clear-all.sh sz      # 深圳服务器
bash gokapi/clear-all.sh sg -y   # 跳过确认提问
```

它会先列出所有已存文件，要求你输入 `yes`，然后全部删除（所有分享链接随之失效——无法撤销），最后报告还剩多少个文件。它从仓库根目录下被 gitignore 排除的 `.env` 里读取 `SG_GOKAPI_URL` + `SG_GOKAPI_API_KEY`（或 `SZ_` 那一对）；API key 在管理页面的 API Keys 菜单里创建，需要有查看和删除文件的权限。依赖 `curl` 和 `jq`。

## 文档

四份参考文档，已发布为独立 HTML 页面（同时也镜像在本仓库的 [`docs/`](docs/) 目录下——文档内容均为英文，无论你读的是哪一份 README）：

- **[File Share Cheat Sheet](https://claude.ai/code/artifact/e0ffbb05-7912-46d4-9e32-88af1983508e)** —— fileshare 最初的速查文档
- **[IP Change Checklist](https://claude.ai/code/artifact/4572cf93-e3fb-4301-9ac8-b621ca557c24)** —— 服务器 IP 变更后一分钟内该做的事
- **[Where Your Files Live](https://claude.ai/code/artifact/cf65ae65-3f4d-4419-9363-641fc6804a09)** —— 每个应用的存储路径、增删命令与保留策略
- **[New Box, Same Stack](https://claude.ai/code/artifact/0375cdf1-bd99-4319-a3db-c5ff5ffdd205)** —— 如何把两个应用迁移到一台全新的 Ubuntu 主机上

## 安全说明

- 本仓库 compose 文件中的所有凭据都只是占位符，真实值从被 gitignore 排除在外的 `.env` 文件中读取——真实值从未进入 git 历史记录。所有密码（fileshare 的上传登录，以及两台机器上 Gokapi 的管理员登录）的主副本，是 Alan 的 Mac 上本地仓库根目录下那个被 gitignore 排除的 `.env`。Gokapi 管理员密码忘了的话无法从服务器上读回（服务器只存哈希）——在容器停止的状态下用 `gokapi --deployment-password <新密码>` 重置，再把新值存进这个 `.env`。目前实际部署中有一个例外：深圳服务器上 `fileshare` 的 compose 文件是把用户名和密码直接写在里面的，而不是从 `.env` 读取——这份改过的副本只存在于服务器上，不在本仓库里。
- `gokapi` 的数据目录是静态加密的（Level 1——密钥保存在本地，因此容器在崩溃或重启后仍能无人值守自动恢复）。
- `fileshare` 的访问密码：`VIEW_PASS`（可选）是整个站点共用的一个密码；每个顶层文件夹还可以在管理页面上单独设置自己的密码，设了之后该文件夹就只认这个密码。输入正确后会为对应范围写入一个 30 天有效的 cookie；改了密码，用过它的人都需要重新输入。同一个地址连续输错 5 次（无论是访问密码还是管理员密码），该地址会被拒绝 10 分钟。密码仍然走明文 HTTP，文件夹密码在服务器上也是明文保存，所以它能挡住随手点进来的访客和扫描器，挡不住有心的攻击者。
- `fileshare` 不会对外提供以点开头的隐藏文件；上传时绝不覆盖已有文件（第二个 `a.pdf` 会存成 `a (1).pdf`）；改名或新建文件夹如果和已有名称冲突，会被拒绝。
- `fileshare` 的文件夹到期：可以在管理页面上给顶层文件夹设置天数，时间一到，该文件夹连同里面所有内容会被自动删除，无法恢复。
- `fileshare` 未加密存储文件，直接以明文文件系统路径存放——访问控制完全依赖链接和密码。
