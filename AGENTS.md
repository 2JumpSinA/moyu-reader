# moyu-reader — 工程约定

摸鱼阅读器：Windows 桌面小说阅读器（Python 3.13 + tkinter/ttkbootstrap）。
核心特性：普通模式 / 阅读模式（色键透明、仅文字悬浮、悬停显隐）、全局热键、本地记忆。

## 快速开始

```bash
# 依赖安装（venv 在仓库内）
python -m venv .venv
.venv/Scripts/python -m pip install -r pyproject.toml   # 或按 pyproject 依赖手动装
# 运行
.venv/Scripts/python main.py
# 或双击 启动摸鱼阅读器.bat
```

## 快捷键

| 键 | 作用 |
|---|---|
| `Shift+Q` | 窗口内切换阅读模式（输入框聚焦时不拦截） |
| `Shift+W` | 立即退出（保存进度后退出） |
| `Esc` | 老板键（普通模式隐藏窗口 / 阅读模式全透明） |
| `Ctrl+Alt+M` | 全局热键：隐身 / 唤回（窗口隐藏时也生效） |
| 右键 / `F2` | 设置菜单（字体、字号、行距、文字颜色、透明度、模式） |
| 滚轮 | 平滑滚动，阅读模式滚到章底自动续章 |

## 记忆

- 设置与进度写到 `%APPDATA%\moyu-reader\settings.json`
- 保存时机：翻章/续章、切模式、外观变更、滚动停稳 1.5s、退出（X / Alt+F4 / Shift+W）、20s 周期兜底
- 启动自动恢复上次书目、章节与滚动位置；坏文件静默降级

## 约定

- 单文件应用（`main.py`），不引入额外运行时依赖
- 无痕优先：不写日志、不弹错误框、异常静默；排障用 `MOYU_DEBUG=1` 看 stderr
- 全局热键必须"注册与消息泵同线程"，否则 `WM_HOTKEY` 收不到
- 透明窗口的背景点击会穿透，悬停显隐用光标位置轮询而非 `<Enter>/<Leave>`

## Agent skills

### Issue tracker

GitHub issues live in `2JumpSinA/moyu-reader`（上游 fork）。See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context layout: `GLOSSARY.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
