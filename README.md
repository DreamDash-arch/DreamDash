# DreamDash · 梦幻跑跑

浏览器 3D 跑酷小游戏，单文件 `index.html` + 本地素材，无 npm、无构建。

- 在线游玩：https://dreamdash-arch.github.io/DreamDash/
- 单人模式：收集星星 / 金币 / 发光蘑菇，冲过终点结算
- 双人竞速：先到终点者获胜，两人距离拉开时自动左右分屏

## 操作

| | 移动 | 跳跃 | 角色技能 | 问号道具 |
|---|---|---|---|---|
| P1 | `A` / `D` | `W` 或 `Space` | `Q` | `S` |
| P2 | `←` / `→` | `↑` | 小键盘 `0` | `↓` |

- `ESC` 暂停
- 选角界面：P1 用 `A`/`D`，P2 用 `←`/`→`，`Space` 确认

## 联机对战（1v1）

### 在线房间（推荐，双方都不用安装任何东西）

1. 打开 https://dreamdash-arch.github.io/DreamDash/
2. 点 **局域网联机** → **创建房间（我是主机）**
3. 页面会显示一个带房间码的链接，把它发给朋友
4. 朋友用浏览器打开这个链接 → **自动加入**
5. 你这边点 **开始选角**，双方各自用 `A` / `D` 选角色，房主按空格开始

> 中继服务部署在 Cloudflare Workers + Durable Objects 上（一个房间 = 一个独立对象），
> 双方不在同一个 Wi-Fi 也能玩。免费额度：一局 3 分钟约 9000 次请求，免费额度约每月 100 局。

### 局域网直连（离线备选，无需外网）

在**其中一台电脑**上运行主机程序（零依赖，只用 Python 标准库）：

```bash
python3 server.py            # 默认端口 8000
python3 server.py --port 9000
```

macOS 可以直接双击仓库里的 `启动服务器.command`。启动后终端会打印局域网地址，
主机打开该地址创建房间，把链接发给朋友即可（页面会自动识别并走局域网直连）。

### 联机操作（两台电脑都用同一套键位）

| 操作 | 按键 |
|---|---|
| 左右移动 | `A` / `D` |
| 跳跃 | `W`（或空格） |
| 角色技能 | `Q` |
| 问号道具 | `S` |

> 同步模型为主机权威：主机跑物理并广播状态，客机只上传按键并渲染结果，
> 客机自己的操作约有 30–60ms 延迟。

## 本地运行

因为要加载本地 GLTF 角色模型，建议用本地服务打开：

```bash
python3 -m http.server 8000
# 打开 http://localhost:8000/index.html
```

直接双击 `index.html` 也能玩，但浏览器会拦截本地模型文件，角色会回退成程序化模型。

联机时，页面会先探测本机是否运行了 `server.py`：有就走局域网直连，没有就走 Cloudflare 在线中继。

## 更新线上版本

```bash
git add -A
git commit -m "更新说明"
git push
```

推送后 GitHub Pages 会自动重新构建，约 1 分钟后生效。

## 开发者：部署 / 维护在线中继

中继代码在 `cloudflare/`（Worker + Room Durable Object，免费版 SQLite 存储）。

```bash
npx wrangler login          # 首次：浏览器点一次「允许」
cd cloudflare
npx wrangler deploy         # 部署，输出 https://<名字>.<子域>.workers.dev
```

部署后把地址（加 `/ws`）填进 `index.html` 的 `ONLINE_RELAY_WS`，再 `git push` 即可。
客户端也支持临时覆盖：`?relay=wss://xxx.workers.dev/ws`。
