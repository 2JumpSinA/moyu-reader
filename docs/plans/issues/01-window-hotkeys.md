# 热键改为窗口内 Shift+Q / Shift+W，移除全局 Ctrl+Alt+Q/W

> 类型：feature / refactor　｜　依赖：无　｜　阻塞：#2 的退出路径测试口径

## 背景

当前 `_setup_global_hotkey()`（`main.py:942-975`）用 Win32 `RegisterHotKey(None, ...)` 一次注册三个**系统级**热键：

| 热键 | ID | 动作 |
|---|---|---|
| `Ctrl+Alt+M` | `0xA111` | 老板键（`_on_boss_key`） |
| `Ctrl+Alt+Q` | `0xA112` | 切换阅读模式（`_toggle_reading_mode`） |
| `Ctrl+Alt+W` | `0xA113` | 两段式退出（`_safe_exit`） |

全局注册有两个实际问题：

1. **占坑**：只要阅读器在跑，这三个组合就被系统优先分给本进程，其他软件（IDE、Office、输入法）设置相同组合会直接失效，且用户无感知。
2. **注册失败**：组合被别的进程先占用时 `RegisterHotKey` 返回 0，代码走 `failed` 分支只在状态栏写一句"全局热键注册失败"（`main.py:964-966`），Q/W 功能即静默丢失。

由于 Q/W 只服务于本应用自身，没有"窗口不在前台也要响应"的必要（真正需要全局的是老板键），应下沉为**窗口内按键绑定**：窗口有焦点才响应。`Ctrl+Alt+M` 保持全局不变。

## 改动点

### 1. 收缩全局热键注册（`main.py:942-975`）

- `regs` 列表只保留 M 一条：`(0xA111, 0x4D, self._on_boss_key)`。
- `listen` 线程与 `GetMessageW` 消息泵**必须保留**——M 仍然依赖它（文件内已有注释说明"注册与消息泵必须同线程"，勿破坏）。
- `_poll_hotkey` 保持不变；`_hotkey_actions` 中不再出现 Q/W。

### 2. 新增窗口内绑定（`_bind_keys`，`main.py:501-515`）

```python
# 阅读模式切换 / 两段式退出：窗口内热键（仅本窗口持有焦点时生效）
for seq in ("<Shift-q>", "<Shift-Q>"):
    self.root.bind_all(seq, self._on_toggle_reading_hotkey)
for seq in ("<Shift-w>", "<Shift-W>"):
    self.root.bind_all(seq, self._on_exit_hotkey)
```

- 同时绑定小写/大写两个 keysym：CapsLock 开启时 keysym 会变成 `Q`/`W`，只绑小写会漏。
- 用 `bind_all` 而非仅 `bind` 到 `root`：阅读模式下窗口去掉了标题栏（`overrideredirect(True)`），焦点常落在正文 `Text` 上，`bind_all` 覆盖更稳。
- 处理器返回 `"break"` 仅在真正消费热键时（见下条），不无脑返回，避免影响输入框正常键入。

### 3. 焦点守卫（新增 `_hotkey_blocked() -> bool`）

必须区分"可编辑输入控件"与"正文只读控件"：

- `focus = self.root.focus_get()`；`focus is None` → 不拦截（阅读模式下可能瞬时无焦点，仍需能退出）。
- `isinstance(focus, (tk.Entry, ttk.Entry))` → 拦截（URL 输入框，`main.py:309`）。
- `isinstance(focus, tk.Text)` 且 `str(focus.cget("state")) != "disabled"` → 拦截；正文 `self.text` 在 `_display` 中被设为 `DISABLED`（`main.py:1035`），**必须放行**，否则阅读模式下 Shift+Q 永远失效。
- `self._dialog_open` 为真（原生对话框占用中，`main.py:259`）→ 拦截。

> 这一条是本 issue 的核心陷阱：守卫写宽了 = 阅读模式里退不出来；写窄了 = 打字吐不出大写 Q。

### 4. 语义与文案同步

- `_toggle_reading_mode` / `_safe_exit` 的逻辑**不动**（两段式仍是 3 秒内两次），只换触发入口。保持 `_exit_req_at`、`_exiting` 状态机原样。
- toast 文案：`main.py:672`、`main.py:1004` → `"Shift+Q 退出阅读模式 · Shift+W 退出应用"`、`"再按一次 Shift+W 确认退出应用"`。
- 右键菜单 accelerator：`main.py:450`（→ `Shift+Q`）、`main.py:476`（→ `Shift+W`）。
- 模块 docstring `main.py:5`、`_setup_global_hotkey` docstring `main.py:943-944`、`_safe_exit` docstring `main.py:995`。
- `README.md` 快捷键表同步。

## 验收标准

- [ ] **AC1** 窗口有焦点，按 `Shift+Q` 进入阅读模式；再按返回普通模式（含标题栏/工具栏复原）。
- [ ] **AC2** 窗口有焦点，按一次 `Shift+W` → 出现"再按一次 Shift+W 确认退出应用"；3 秒内再按 → 进程退出。
- [ ] **AC3** 距首次按 `Shift+W` 超过 3 秒再按 → 不退出，重新开始确认计时（沿用现有边界，2.9s 退出 / 3.1s 不退出）。
- [ ] **AC4** 窗口无焦点（切到记事本/浏览器）时按 `Shift+Q` / `Shift+W` → 阅读器无任何反应（不切换、不退出、不弹 toast）。
- [ ] **AC5** 旧全局热键失效：`Ctrl+Alt+Q` / `Ctrl+Alt+W` 在窗口有焦点、无焦点两种状态下均无反应。
- [ ] **AC6** 退出应用后，`Ctrl+Alt+Q` / `Ctrl+Alt+W` 在系统其他软件中可正常使用（本进程未再注册）。
- [ ] **AC7** `Ctrl+Alt+M` 仍为全局老板键：窗口无焦点时按 M → 普通模式窗口隐藏；再按 → 唤回。阅读模式按 M → alpha 归 0；再按 → 恢复。
- [ ] **AC8** URL 输入框聚焦时键入 `Shift+Q` / `Shift+W` → 输入框正常出现大写 `Q` / `W`，不切换模式、不触发退出确认。
- [ ] **AC9** CapsLock 开启时 `Shift+Q` / `Shift+W` 仍生效。
- [ ] **AC10** 阅读模式（无边框）下窗口有焦点时 `Shift+Q` / `Shift+W` 生效。
- [ ] **AC11** 代码中不再残留 Q/W 的 `RegisterHotKey` 注册；`Ctrl+Alt+Q`、`Ctrl+Alt+W` 字样在 `main.py` 与 `README.md` 中已无描述性残留（历史注释除外）。
- [ ] **AC12** 无新增全局热键；应用启动后系统级热键占用数量仍为 1（可用 [AutoHotkey/Process Hacker 查] 或对比改动前后 `RegisterHotKey` 调用次数）。
- [ ] **AC13** 中文输入法激活状态下按 `Shift+Q` 的行为已实测记录：若 IME 吞掉按键导致不触发，作为已知限制写入 issue 备注（不作为验收失败项）。

## 已知风险

- 阅读模式 `overrideredirect(True)` + `-toolwindow`：窗口不可从任务栏点回，失去焦点后只能点正文找回。`bind_all` 保证"点回来就能用"，但不会解决"找不到窗口"——这是既有行为，不在本 issue 范围。
- `bind_all` 会覆盖同 keysym 的其他绑定；若未来加 `Shift+W` 的输入相关功能需重新评估。
