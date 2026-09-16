# DreamDash · 梦幻跑跑

浏览器 3D 跑酷小游戏，单文件 `index.html` + 本地素材，无 npm、无构建。

- 在线游玩：https://daiyuqi-arch.github.io/DreamDash/
- 单人模式：收集星星 / 金币 / 发光蘑菇，冲过终点结算
- 双人竞速：先到终点者获胜，两人距离拉开时自动左右分屏

## 操作

| | 移动 | 跳跃 | 角色技能 | 问号道具 |
|---|---|---|---|---|
| P1 | `A` / `D` | `W` 或 `Space` | `Q` | `S` |
| P2 | `←` / `→` | `↑` | 小键盘 `0` | `↓` |

- `ESC` 暂停
- 选角界面：P1 用 `A`/`D`，P2 用 `←`/`→`，`Space` 确认

## 本地运行

因为要加载本地 GLTF 角色模型，建议用本地服务打开：

```bash
python3 -m http.server 8000
# 打开 http://localhost:8000/index.html
```

直接双击 `index.html` 也能玩，但浏览器会拦截本地模型文件，角色会回退成程序化模型。

## 更新线上版本

```bash
git add -A
git commit -m "更新说明"
git push
```

推送后 GitHub Pages 会自动重新构建，约 1 分钟后生效。
