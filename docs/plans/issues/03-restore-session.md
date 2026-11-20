# 启动自动恢复上次阅读（书/章/滚动位置）

> 类型：feature　｜　**依赖：#2 settings.json 持久化（必须先合入）**　｜　阻塞：无

## 背景

`run()`（`main.py:1161-1165`）当前只做三件事：绑定 `WM_DELETE_WINDOW`、注册全局热键、进 `mainloop`。启动后正文区永远空白，`_display()` 还会把视图硬重置到顶部（`main.py:1036`）。

#2 落地后，状态已经躺在 `%APPDATA%\moyu-reader\settings.json` 里，但没人读回来用。本 issue 负责"把它变成一张可继续阅读的界面"：启动 → 自动打开上次那本书 → 定位到上次那一章 → 滚到上次那一屏。

范围边界：恢复的是**上次这一本书**，不是书架；启动后的交互状态（阅读模式/老板键隐身）**一律不恢复**。

## 改动点

### 1. 恢复入口

在 `run()` 中 `mainloop()` 之前挂 `self.root.after(0, self._restore_last_session)`：

- 必须在 mainloop 内执行——窗口尚未完成布局时 `yview_moveto` 的比例计算不可靠。
- 恢复流程整体置于 `self._restoring = True` 保护下，结束（成功或失败）后置 False。

### 2. 三分支逻辑

```python
def _restore_last_session(self):
    sess = (self._settings_data.get("session") or {})
    mode = sess.get("mode")
    if mode == "txt":   self._restore_txt(sess)
    elif mode == "web": self._restore_web(sess)
    # mode 缺失/为 "none" → 保持现状（空白普通模式）
```

**TXT 分支**

- `path` 为空或文件不存在 → 状态栏 `未找到上次的书：<basename>（已跳过恢复）`，不弹窗、不重试、界面正常可用。
- 存在 → 后台线程 `TxtBook(path)` 加载（`TxtBook._load` 是同步全量读 + 全文正则，`main.py:145-168`；10MB+ 文件会卡主线程）→ 完成回调 `root.after(0, ...)` 回主线程。
- 加载期间状态栏显示 `正在恢复上次阅读…`；期间 `btn_fetch` / 翻页按钮 disable，加载完成再 enable。
- 加载成功：`go_to(clamp(chapter_index, 0, total-1))` → `_show_txt_page()` → `after_idle` 应用 `scroll_fraction`。
- 加载失败（编码/权限/空文件）→ 状态栏提示，保持普通模式空白，不弹 `messagebox`。

**WEB 分支**

- `url` 为空 → 跳过。否则 `var_url.set(url)` 后复用 `_on_fetch()`（异步，不阻塞启动）。
- 抓取失败：走 `_on_fetch_error`，但**恢复路径不弹窗**——新增 `silent` 参数或 `self._restoring` 判定，只写状态栏（启动即弹错误框非常骚扰；用户手动抓取时保留原弹窗行为）。
- 抓取成功：`_on_fetch_done` 之后 `after_idle` 应用 `scroll_fraction`。
- `next_url` / `history` 一并还原（`main.py:249-250`），保证左右方向键翻章/回退可用。

### 3. 必须遵守的三条硬约束

1. **启动一律普通模式**：不恢复 `_reading_mode`、不 `overrideredirect(True)`、不设透明色键、不 `-topmost`。上次停在阅读模式时，重启后回到带标题栏的普通模式，内容与位置保留。理由：避免"启动即隐身且进不了任务栏，用户找不到窗口"。
2. **恢复期间禁止回写**：`_schedule_save()` 在 `self._restoring` 为真时直接 return。否则恢复失败的那一瞬间会用默认值覆盖掉磁盘上的真实进度，造成"越修越丢"。
3. **恢复幂等**：连续重启 3 次，`chapter_index` 与 `scroll_fraction` 不得单向漂移（典型漂移源：恢复后立刻保存了"还没滚到位"的临时位置）。

### 4. 收尾提示

恢复成功后状态栏 `已恢复：<书名/域名> · 第 N/N 章`，3 秒后由既有 `var_status` 默认文案覆盖（不新增 toast，避免与阅读模式教学 toast 抢屏）。

### 5. 不碰的东西

- 不动 `_bind_keys` / 右键菜单 / 老板键 / 两段式退出的既有逻辑（#1 的成果）。
- 不改入口的静默异常约定（`main.py:1180-1187`）。

## 验收标准

- [ ] **AC1** 上次 TXT 停在第 12 章中段 → 重启 → 自动打开同一文件、定位第 12 章、滚动位置视觉一致（±1 行），无需任何点击。
- [ ] **AC2** 上次网页停在某 URL → 重启（联网）→ 自动抓取并显示同一 URL 正文，滚动位置一致。
- [ ] **AC3** 上次网页 URL → 重启（断网）→ 不崩溃、**不弹窗**，状态栏提示抓取失败；界面可正常手动输入网址抓取。
- [ ] **AC4** 上次 TXT 文件被删除/改名/移到别的盘 → 重启 → 不崩溃、不弹窗，状态栏提示"未找到上次的书"，界面可用（可直接打开新文件）。
- [ ] **AC5** 上次停在阅读模式 → 重启 → 回到**普通模式**（有标题栏、有工具栏、非透明、可点 X），内容与位置正常。
- [ ] **AC6** 恢复后功能完好：`Shift+Q` / `Shift+W` / 右键菜单 / 方向键翻章 / `Ctrl+Alt+M` 全部按 #1 与既有行为工作。
- [ ] **AC7** 越界钳制：手工把 `chapter_index` 改成 `9999` / `-3` → 重启 → 分别定位到最后一章 / 第一章，不崩。
- [ ] **AC8** 大文件不冻结：≥10MB TXT 恢复时窗口可拖动、可响应点击，白屏/冻结 < 1 秒，且有"正在恢复"提示。
- [ ] **AC9** 幂等：同一状态连续重启 3 次，`chapter_index` 与 `scroll_fraction` 保持一致（不漂移）。
- [ ] **AC10** 恢复失败不毁数据：故意让 TXT 恢复失败（如临时锁文件），关闭应用后 `settings.json` 中 `session.txt.path` 仍为原值（未被默认值覆盖）。
- [ ] **AC11** 首次启动（无 `session` 键 / `mode: "none"`）→ 行为与改动前完全一致（空白普通模式）。
- [ ] **AC12** 无痕：恢复流程不新增任何日志文件、不弹错误窗（`%APPDATA%\moyu-reader\` 仍只有 `settings.json`）。

## 已知限制

- 网页内容依赖站点存活与反爬策略；恢复可能抓到"页面不存在"或登录墙，此时按 AC3 静默降级，不视为缺陷。
- 滚动位置为比例还原，字体/字号变化后视觉位置会有少量偏移（预期行为）。
