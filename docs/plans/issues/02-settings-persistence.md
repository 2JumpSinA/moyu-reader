# settings.json 持久化：书目 / 章节 / 滚动位置 / 外观

> 类型：feature　｜　依赖：无（与 #1 无代码依赖）　｜　阻塞：#3 启动恢复

## 背景

当前工程**没有任何持久化**：`main.py` 全文件无 `json` 导入、无配置读写，所有状态只存在内存里。

退出即全丢：

- 书目：`self.current_url`（`main.py:248`）、`self.txt_book`（`main.py:251`）——重开就空白。
- 章节：`TxtBook.current_index`（`main.py:142`）——重开回到第 1 章。
- 滚动位置：纯 Tk 视图状态，`_display()` 里被硬编码 `self.text.yview_moveto(0)`（`main.py:1036`）——重开回到顶部。
- 外观：字体/字号/行距/文字颜色/透明度/置顶/工具栏可见性全是 `tk.Variable`（`main.py:283-290`）与实例字段（`main.py:255`），进程结束即蒸发。

用户每次启动都要重新：打开文件 → 翻回第 N 章 → 滚到原来那一屏 → 重新调字号字体颜色。本项目定位是"随时切回来的摸鱼窗口"，这个成本直接劝退。

目标：把上述状态落到 `%APPDATA%\moyu-reader\settings.json`，**坏文件绝不崩溃、绝不弹窗、绝不留半截文件**（与 `main.py:1180-1187` 的"静默退出、不留日志"约定一致）。

## 改动点

### 1. 存储位置与原子写

```python
APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "moyu-reader")
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
```

- `os.makedirs(APP_DIR, exist_ok=True)`；目录创建失败仅静默降级为"本次不持久化"。
- 写入：`settings.json.tmp` → `os.replace()` 原子替换。**禁止** `open(path, "w")` 直写（断电/强杀会留半截 JSON）。
- 编码 `utf-8`，`ensure_ascii=False`，`indent=2`（便于用户手工排障）。

### 2. 新增 `SettingsStore` 类（模块级，建议放在 `TxtBook` 之后，`main.py:196` 附近）

| 方法 | 职责 |
|---|---|
| `defaults() -> dict` | 返回完整 v1 默认结构 |
| `load() -> dict` | 读 + 校验 + 归一；任何异常返回 defaults |
| `save(data: dict) -> bool` | 原子写；失败返回 False，不抛 |
| `_validate(raw) -> dict` | 逐字段类型/范围校验，越界钳制 |

异常处理要求（`OSError` / `json.JSONDecodeError` / `TypeError` / `ValueError` / `UnicodeDecodeError`）：

- 坏文件改名为 `settings.json.bad`（覆盖上一份 bad，不做时间戳轮转，避免目录堆垃圾）；
- 返回 defaults，进程继续；
- **不得**调用 `messagebox`；
- `os.environ.get("MOYU_DEBUG")` 为真时 `traceback.print_exc()` 到 stderr，与入口约定一致。

### 3. schema v1

```json
{
  "version": 1,
  "window": {
    "geometry": "860x680+120+80",
    "topmost": false,
    "opacity": 100,
    "toolbar_visible": true
  },
  "appearance": {
    "font_family": "Microsoft YaHei",
    "font_size": 10,
    "line_spacing": 2,
    "text_color": "#777777"
  },
  "session": {
    "mode": "txt",
    "txt": { "path": "D:\\novels\\a.txt", "chapter_index": 12 },
    "web": { "url": "", "next_url": null, "history": [] },
    "scroll_fraction": 0.35
  }
}
```

字段口径说明：

- `geometry`：`root.geometry()` 原始串；读回时用 try/except 包 `root.geometry(...)`，畸形串会抛 `TclError`。
- `opacity`：对应 `self._opacity`（`main.py:255`），10–100 整数。
- `scroll_fraction`：`self.text.yview()[0]` 的浮点比例，**不要**存像素或行号——窗口尺寸变了就错位，比例才跨分辨率稳定。
- `session.mode`：`"txt"` / `"web"` / `"none"`，决定 #3 的恢复分支。
- `history`：网页回退栈（`self.history`，`main.py:250`），封顶 50 条防止无限增长。
- 不持久化 `_reading_mode` / `_boss_hidden`：启动一律普通模式，避免"启动即隐身、用户找不到窗口"。

### 4. 写入时机

新增 `_schedule_save()`：`root.after(1500, ...)` 防抖，单 job 复用（旧 job 先 `after_cancel`）。

**立即写**：

- `_safe_exit` 第二击命中（`main.py:999-1001`，`root.destroy()` 之前）；
- `_force_exit`（`main.py:1167-1170`，窗口 X / Alt+F4 走 `WM_DELETE_WINDOW`）；
- `_on_open_txt` 成功加载后（`main.py:1121`）；
- `_on_fetch_done` 成功后（`main.py:1068`）；
- 翻章 `_on_next` / `_on_prev` 之后（`main.py:1140-1156`）；
- 外观变更：`_apply_font`、`_set_opacity`、`_on_topmost_changed`、`_on_text_color_changed`、`_toggle_toolbar`。

**防抖写**：滚动位置、窗口拖动结束（`_on_drag_end`，`main.py:877`）。

> 只靠"退出时写"不够：#3 的测试矩阵含强杀进程，必须靠防抖快照兜底（最坏丢 1.5 秒进度）。

### 5. 读取时机

- `ReaderApp.__init__` 最前面 `self._settings_data = SettingsStore().load()`；
- 在 `_build_ui()` **之前**把 `var_font_family / var_font_size / var_line_spacing / var_topmost / var_text_color` 设为持久化值（`main.py:283-290`），避免先建 UI 再回刷导致闪烁；
- `geometry` / `opacity` 在 `run()` 里 `mainloop()` 之前应用（`main.py:1161`）；
- `_toolbar_visible` 直接赋初值，`_build_ui` 的 pack 逻辑据此决定是否 `pack`。

### 6. 校验与钳制表

| 字段 | 规则 | 越界处理 |
|---|---|---|
| `version` | 缺失/非 1 | 用 defaults 覆盖（本期无迁移） |
| `font_family` | 必须 ∈ `FONT_CHOICES`（`main.py:206-209`） | 回落默认 |
| `font_size` | int 4–28 | 钳制 |
| `line_spacing` | int 0–18 | 钳制 |
| `text_color` | `^#[0-9a-fA-F]{6}$` | 回落 `#777777` |
| `opacity` | int 10–100 | 钳制 |
| `chapter_index` | int ≥ 0 | 负数归 0；越界由 #3 按 `book.total` 钳制 |
| `scroll_fraction` | float 0.0–1.0 | 钳制 |
| `geometry` | 匹配 `\d+x\d+([+-]\d+){2}` 且 Tk 不抛错 | 回落默认 860x680 居中 |

### 7. 隐私与无痕

- 文件名/路径/URL 可能含书名等个人信息，仅写用户 `%APPDATA%`，不外发、不上传。
- 不新增任何日志文件；`.tmp` 残留由下次 `save` 覆盖。
- 无痕性约定不变：默认静默（`main.py:1181`）。

## 验收标准

- [ ] **AC1** 全新机器首次启动（`%APPDATA%\moyu-reader\` 不存在）→ 不报错、正常使用；正常退出后目录被创建，`settings.json` 存在且 `python -m json.tool settings.json` 通过，含 `"version": 1`。
- [ ] **AC2** 外观全量往返：改字体（如 KaiTi）/ 字号（16）/ 行距（4）/ 文字颜色（#FFD866）/ 透明度（60%）/ 勾选置顶 / 隐藏工具栏 → 退出 → 重启 → 六项全部保持。
- [ ] **AC3** 窗口尺寸/位置往返：调整窗口到 1200x800 并拖到屏幕右下 → 退出 → 重启 → 尺寸位置一致。
- [ ] **AC4** 进度写入：TXT 翻到第 12 章、滚到中段 → 强杀进程（任务管理器结束）→ 重启 → `settings.json` 中 `chapter_index == 12`、`scroll_fraction` 非 0（允许最多丢失 1.5 秒内的滚动）。
- [ ] **AC5** 原子性：写盘过程中强杀（可用循环 `save` + 强杀压测 20 次）→ `settings.json` 每次都可解析，无半截文件、无 `.tmp` 残留（或残留不影响下次写入）。
- [ ] **AC6** 坏文件容错五种，均**不崩溃、不弹窗**、以默认值启动，且坏文件被改名为 `settings.json.bad`：
  - [ ] 空文件（0 字节）
  - [ ] 截断 JSON：`{"version":1,"wind`
  - [ ] 类型错误：`{"appearance":{"font_size":"big"},"opacity":"透明"}`
  - [ ] 顶层是数组：`[]`
  - [ ] 非 UTF-8 编码（用 GBK 写入的中文 JSON）
- [ ] **AC7** 范围钳制：手工写入 `font_size: 999`、`opacity: -5`、`scroll_fraction: 3.5`、`text_color: "red"` → 启动不崩，全部按钳制表回落/钳位。
- [ ] **AC8** 目录不可写（把 `moyu-reader` 目录设为只读）→ 应用正常运行，无弹窗；仅 `MOYU_DEBUG=1` 时 stderr 有记录。
- [ ] **AC9** 滚动位置用比例：同一章在 860x680 与 1200x800 下恢复的位置视觉接近（±1 行），不会因窗口变大而跳到文末。
- [ ] **AC10** 多实例：同时开两个进程各自改外观并退出 → 文件仍可解析（后写者胜即可），不出现损坏。
- [ ] **AC11** 无痕：全程观察 `%APPDATA%\moyu-reader\` 仅 `settings.json`（+ 可能的 `.bad`），无日志文件。

## 非目标

- 不做多本书书架（"书目"= 上次打开的那一本，不是书库）。
- 不做设置面板 UI（沿用现有右键菜单）。
- 不做跨平台路径（本项目仅 Windows，`%APPDATA%` 即可）。
