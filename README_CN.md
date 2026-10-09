# Gokapi-FileShare

[English](README.md) | [中文](README_CN.md)


两个独立的小型文件共享服务，用于从深圳 ECS 向国内朋友分享文件——可浏览目录，以及带管理界面的到期链接。每个都是独立的 Docker Compose 服务，没有共享数据库或云端依赖。

刻意通过裸 IP 访问，而非域名——中国大陆要求任何通过域名对外提供服务的站点完成 ICP 备案，裸 IP 完全绕开了这项要求。

## 两个应用

| 应用 | 端口 | 用途 | 源码 |
|---|---|---|---|
| [`fileshare/`](fileshare/) | 8080 | 可浏览目录列表——每一行都有「复制直达链接」按钮，文件还有「下载」按钮；点文件名则直接在浏览器里打开——外加密码保护的管理页面（上传 / 改名 / 删除 / 复制链接）。页面宽度自适应，从手机到最宽 1120px | 自定义 Python（仅标准库） |
| [`gokapi/`](gokapi/) | 9001 | 带真正管理界面、静态加密的到期链接 | [Gokapi](https://github.com/Forceu/Gokapi) |

`fileshare` 先后替代了 [Filebrowser](https://github.com/filebrowser/filebrowser) 和 [Alist](https://github.com/AlistGo/alist)——Filebrowser 将于 2026-09-01 归档、不再有后续发布，而 Alist 的功能则超出了实际需求。`gokapi` 是之后加入的，用来覆盖一次性私密链接、带真正到期机制的场景——这个角色以前由已下线的伴生应用 `quickshare-sz` 承担。

**Gokapi 的裸地址是故意跳走的。** 打开 `http://<主机>:9001/` 会被带到 Gokapi 的 GitHub 页面——它没有公开首页，而 `RedirectUrl` 这个设置（在服务器上的 `gokapi/config/config.json` 里）还是默认值。这不是故障。管理员登录入口是 `http://<主机>:9001/admin`；分享出去的文件各有自己的下载链接。

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
- `fileshare` 未加密存储文件，直接以明文文件系统路径存放——访问控制完全依赖链接和密码。
