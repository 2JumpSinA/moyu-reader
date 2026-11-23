# 🐟 摸鱼阅读器 (Moyu Reader) · 透明悬浮版

> 背景完全透明、只有文字浮在桌面上的小说阅读器 —— 鼠标移开自动隐身。

本项目 fork 自 [gzg66/moyu-reader](https://github.com/gzg66/moyu-reader)，在原版基础上**重写了阅读模式与交互层**，
核心差异见下方[与原版的差异](#-与原版的差异)。

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 🪟 **透明悬浮阅读** | 阅读模式下背景**完全透明**（Windows 色键抠底），桌面上只剩文字 |
| 👻 **悬停显隐** | 鼠标在窗口内显示、移出后 ~0.1s 自动隐身，移回立即出现 |
| 🖱️ **滚轮全窗接管** | Win32 低级鼠标钩子接管：指针在窗口内滚动只作用于阅读器，**绝不漏到背后的浏览器/IDE** |
| 📜 **平滑滚动 + 自动续章** | 滚到章底自动无缝追加下一章，无需手动翻页；可调滚轮速度（30%~200%） |
| 📖 **章节目录** | 右键或 `Ctrl+L` 打开目录，913 章也能秒跳；当前章高亮 |
| 🔠 **章节标题加粗** | 正文内章节标题加粗居中，滚动时一眼看出章界 |
| 🎨 **外观可调** | 字体、字号、行距、文字颜色（9 种预设 + 自定义取色）、透明度、置顶 |
| 📐 **窗口尺寸** | 最小可压到 160×60；预设 320×80 / 420×140 / 600×200 / 800×280；阅读模式右下角拖拽缩放 |
| 💾 **阅读记忆** | 记住书目、章节、滚动位置、字体/颜色/尺寸，下次启动自动恢复到原处 |
| 🚨 **老板键** | `Esc` 瞬间隐身；再次双击启动器唤回（无全局热键） |
| 🔒 **单实例** | 重复启动只会把已有窗口唤到前台，不会多开抢热键 |
| 🕵️ **无痕** | 不写日志、不弹错误框；窗口标题伪装为「会议记录」；不进任务栏/Alt+Tab |

---

## ⌨️ 快捷键

| 快捷键 | 作用 |
|--------|------|
| `Shift+Ctrl+Z` | 切换 普通模式 ⇄ 阅读模式 |
| `Shift+Ctrl+X` | 立即退出（自动保存进度） |
| `Esc` | 老板键：瞬间隐身 |
| `Ctrl+L` | 打开章节目录 |
| `Ctrl+O` | 打开本地 TXT |
| `F2` / 右键 | 设置菜单 |
| 滚轮 | 平滑滚动，阅读模式滚到章底自动续章 |
| `←` / `→` | 上一页 / 下一页 |
| 阅读模式下拖拽 | 移动窗口；拖右下角 = 缩放 |

> 所有快捷键都是**窗口内**生效，系统里没有任何全局热键/键盘钩子。
>
> **隐身唤回**：按 `Esc` 隐身后，再次双击 `启动摸鱼阅读器.bat` 即可把窗口唤回（单实例激活机制）。

---

## 🚀 快速开始

### 方式一：直接运行（推荐）

```bash
git clone git@github.com:2JumpSinA/moyu-reader.git
cd moyu-reader

python -m venv .venv
.venv\Scripts\python -m pip install beautifulsoup4 chardet lxml requests ttkbootstrap

# 启动（无控制台黑窗）
start "" ".venv\Scripts\pythonw.exe" main.py
```

Windows 下也可直接双击仓库内的 `启动摸鱼阅读器.bat`。

### 方式二：排障模式

```bash
cd /d D:\moyu-reader
set MOYU_DEBUG=1
.venv\Scripts\python.exe main.py
```

正常退出完全静默；只有设置 `MOYU_DEBUG=1` 时才会把异常打印到 stderr。

### 依赖

- Python ≥ 3.11（Windows 10/11）
- `ttkbootstrap`、`beautifulsoup4`、`lxml`、`requests`、`chardet`

---

## 💾 记忆与配置

配置保存在 `%APPDATA%\moyu-reader\settings.json`（不在仓库目录，重装可保留）：

```json
{
  "version": 1,
  "book": { "type": "txt", "path": "D:\\books\\xxx.txt", "chapter": 12 },
  "scroll": { "yview": 0.34, "line": "128.5" },
  "window": { "geometry": "600x200+1200+80" },
  "appearance": {
    "text_color": "#FFD866", "font_family": "Microsoft YaHei",
    "font_size": 10, "line_spacing": 2,
    "opacity": 100, "topmost": true, "scroll_speed": 75
  }
}
```

- 保存时机：翻章 / 续章 / 切模式 / 外观变更 / 滚动停止 1.5s / 退出（X、Alt+F4、`Shift+Ctrl+X`）/ 20s 周期兜底
- 坏文件、缺字段、文件被删都会**静默降级**，不影响启动

---

## 🏗️ 实现要点

| 能力 | 实现方式 |
|------|----------|
| 背景完全透明 | `root.attributes("-transparentcolor", key)`；`key = 文字色任一通道 XOR 0x01`，让抗锯齿边缘与文字色不可分，消除彩边 |
| 透明区域可拖拽/右键 | 色键像素会穿透鼠标命中测试 → 叠加一个 `alpha 0.01` 的**输入层窗口**（视觉不可见但可命中），与主窗几何同步 |
| 悬停显隐 | 30ms 轮询 `GetCursorPos + GetWindowRect`（物理像素，避免高 DPI 错位）+ 迟滞边距；<Enter>/<Leave> 在色键窗口上不可靠，故不用 |
| 滚轮不漏背景 | `WH_MOUSE_LL` 低级鼠标钩子（仅鼠标事件）：指针在窗口矩形内则接管并吞掉事件 |
| 菜单外部点击关闭 | `Menu.post()` 不设 grab，点击窗口外收不到 → 钩子监听左右键，落在菜单矩形外则 `unpost` |
| 单实例+唤回 | 命名互斥量 + 命名事件；重复启动把已有窗口唤到前台。注意必须用 `ctypes.WinDLL(..., use_last_error=True)` 才能读到 `ERROR_ALREADY_EXISTS` |
| 自动续章 | 章底检测后**追加**而非重绘，滚动位置不跳 |

---

## ⚠️ 已知限制

1. **网页抓取依赖目标站结构**，站点改版会导致正文提取失败；抓取会在公司网络审计中留下域名记录，建议优先用 TXT。
2. **滚动位置恢复有 ±几行误差**（Tk 首次布局会重置视图，已用多点确认补偿）。
3. **滚轮接管与菜单外部关闭依赖全局鼠标钩子**；若被安全软件拦截，会退化为仅窗口内生效（功能不崩，体验下降）。
4. 阅读模式的透明区域由于叠加输入层，**窗口显示时会吃掉覆盖区域的点击**；隐身（鼠标移开）后立即恢复穿透。

---

## 📁 目录结构

```
moyu-reader/
├── main.py                 # 全部逻辑（约 2100 行，单文件）
├── AGENTS.md               # 工程约定 / 架构速查（给 AI 协作用）
├── docs/agents/            # issue tracker 与领域文档约定
├── 启动摸鱼阅读器.bat        # 双击启动（pythonw，无黑窗）
├── pyproject.toml
└── LICENSE                 # MIT
```

---

## 🔄 与原版的差异

| 维度 | 原版 gzg66/moyu-reader | 本 fork |
|------|------------------------|---------|
| 阅读模式 | 半透明暗底（alpha 0.35） | **背景完全透明**，仅文字悬浮 |
| 显隐 | 手动快捷键 | **悬停自动显示 / 移出自动隐身** |
| 滚轮 | `yview_scroll` 直接滚动，会漏到背景 | 钩子接管，**绝不漏**；可调速度 |
| 续章 | 手动翻页 | 滚到章底**自动无缝续章** |
| 目录 | 无 | **完整章节目录 + 跳转** |
| 记忆 | 无 | **书目/章节/位置/外观全记忆** |
| 单实例 | 无（可多开抢热键） | **命名互斥量单实例** |
| 窗口 | 最小 400×300 | 最小 **160×60** + 尺寸预设 + 边角缩放 |
| 退出 | 无保护 | `Shift+Ctrl+X` 保存后退出，X/Alt+F4 同样保存 |

---

## 📄 License

[MIT](LICENSE) · 原始版权归 [gzg66](https://github.com/gzg66/moyu-reader) 所有，本 fork 同样以 MIT 发布。

## 🙏 致谢

- 原项目：[gzg66/moyu-reader](https://github.com/gzg66/moyu-reader)
- UI 主题：[ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap)
