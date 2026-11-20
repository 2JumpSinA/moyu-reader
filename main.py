"""
小说阅读器 - 摸鱼神器（改造版）
双模式：普通模式（带标题栏/工具栏，启动默认）/ 阅读模式（背景完全透明、
仅文字悬浮、悬停显示移出隐形、置顶、不进任务栏）
窗口内快捷键：Shift+Q 切换阅读模式 | Shift+W 退出应用 | Esc 老板键
全局热键：Ctrl+Alt+M 隐身/唤回（窗口隐藏时也生效）
记忆：自动记住书目/章节/滚动位置/外观，下次启动自动恢复
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

import chardet
import requests
import ttkbootstrap as ttk
from ttkbootstrap.constants import (
    PRIMARY, INFO,
    LEFT, RIGHT, BOTH, X, Y, W,
    CENTER, BOTTOM,
)
from bs4 import BeautifulSoup
from urllib.parse import urljoin



# ═══════════════════════════════════════════════════════
#                     网页抓取器
# ═══════════════════════════════════════════════════════
class WebFetcher:
    """抓取网页小说内容"""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    @staticmethod
    def fetch(url: str) -> dict:
        resp = requests.get(url, headers=WebFetcher.HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        title = WebFetcher._extract_title(soup)
        content = WebFetcher._extract_content(soup)
        next_url = WebFetcher._find_next_link(soup)
        if next_url:
            next_url = urljoin(url, next_url)

        return {"title": title, "content": content, "next_url": next_url}

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        for tag in ("h1", "h2", "h3"):
            el = soup.find(tag)
            if el:
                return el.get_text(strip=True)
        t = soup.find("title")
        return t.get_text(strip=True) if t else "未知标题"

    @staticmethod
    def _extract_content(soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        ids = [
            "content", "chaptercontent", "booktxt", "book_text",
            "htmlContent", "chapter-content", "articlecontent",
            "TextContent", "text_content", "nr_title", "nr1",
        ]
        classes = [
            "content", "chapter_content", "book_text", "readcontent",
            "read-content", "article-content", "novelcontent",
            "txtnav", "contentbox", "RBGBookDetailcontent",
        ]

        best, best_len = None, 0

        for cid in ids:
            el = soup.find(id=cid)
            if el:
                txt = el.get_text("\n", strip=True)
                if len(txt) > best_len:
                    best, best_len = txt, len(txt)

        for cls in classes:
            for el in soup.find_all(class_=cls):
                txt = el.get_text("\n", strip=True)
                if len(txt) > best_len:
                    best, best_len = txt, len(txt)

        if best_len < 200:
            p_text = "\n".join(
                p.get_text(strip=True)
                for p in soup.find_all("p")
                if len(p.get_text(strip=True)) > 10
            )
            if len(p_text) > best_len:
                best, best_len = p_text, len(p_text)

        if best_len < 100:
            body = soup.find("body")
            if body:
                best = body.get_text("\n", strip=True)

        return best or "未能提取到正文内容，请检查 URL 是否正确。"

    @staticmethod
    def _find_next_link(soup: BeautifulSoup) -> str | None:
        patterns = [
            re.compile(r"下一[页章节篇]"),
            re.compile(r"next\s*(page|chapter)", re.IGNORECASE),
        ]
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            for pat in patterns:
                if pat.search(text):
                    return a["href"]
        for a in soup.find_all("a", href=True, id=re.compile(r"next", re.IGNORECASE)):
            return a["href"]
        return None


# ═══════════════════════════════════════════════════════
#                    TXT 分章管理
# ═══════════════════════════════════════════════════════
class TxtBook:
    """管理 TXT 文件的加载和分章/分页"""

    def __init__(self, filepath: str, chars_per_page: int = 3000):
        self.filepath = filepath
        self.chars_per_page = chars_per_page
        self.chapters: list[tuple[str, str]] = []
        self.current_index = 0
        self._load()

    def _load(self):
        with open(self.filepath, "rb") as f:
            raw = f.read()
        enc = chardet.detect(raw).get("encoding", "utf-8") or "utf-8"
        text = raw.decode(enc, errors="replace")

        pattern = re.compile(
            r"^[ \t]*(第[零一二三四五六七八九十百千万\d]+[章节回卷集部篇].*)",
            re.MULTILINE,
        )
        splits = list(pattern.finditer(text))

        if len(splits) >= 2:
            for i, m in enumerate(splits):
                title = m.group(1).strip()
                start = m.end()
                end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
                content = text[start:end].strip()
                if content:
                    self.chapters.append((title, content))
        else:
            for i in range(0, len(text), self.chars_per_page):
                page = i // self.chars_per_page + 1
                self.chapters.append((f"第 {page} 页", text[i : i + self.chars_per_page]))

    @property
    def total(self) -> int:
        return len(self.chapters)

    def current(self) -> tuple[str, str]:
        if 0 <= self.current_index < self.total:
            return self.chapters[self.current_index]
        return ("", "")

    def has_next(self) -> bool:
        return self.current_index < self.total - 1

    def has_prev(self) -> bool:
        return self.current_index > 0

    def go_next(self):
        if self.has_next():
            self.current_index += 1

    def go_prev(self):
        if self.has_prev():
            self.current_index -= 1

    def go_to(self, idx: int):
        if 0 <= idx < self.total:
            self.current_index = idx


# ═══════════════════════════════════════════════════════
#                     阅读器主窗口
# ═══════════════════════════════════════════════════════
class ReaderApp:
    # 默认配置
    DEFAULT_FONT_FAMILY = "Microsoft YaHei"
    DEFAULT_FONT_SIZE = 10
    DEFAULT_LINE_SPACING = 2
    FONT_CHOICES = [
        "Microsoft YaHei", "SimSun", "KaiTi", "SimHei",
        "FangSong", "Consolas", "Courier New", "Arial",
    ]

    # 阅读模式文字颜色色板（分组：适用桌面明暗）
    READING_COLOR_GROUPS = [
        ("通用", [
            ("#777777", "中灰（默认）"),
            ("#6B7280", "蓝灰"),
        ]),
        ("深色桌面用", [
            ("#FFD866", "暖黄"),
            ("#F5F5F5", "近白"),
            ("#FFFFFF", "纯白"),
            ("#A5D6FF", "淡蓝"),
        ]),
        ("浅色桌面用", [
            ("#2B2B2B", "炭黑"),
            ("#1E3A8A", "深蓝"),
            ("#14532D", "深绿"),
        ]),
    ]

    # 悬停显隐参数
    HOVER_ALPHA_SHOWN = 1.0     # 悬停时
    HOVER_ALPHA_HIDDEN = 0.02   # 移出时（留 0.02 便于找回）
    HIDE_DELAY_MS = 400         # 移出后延迟隐藏
    MIN_SHOWN_SEC = 0.8         # 最短显形时间，防扫过闪隐
    HOVER_MARGIN = 8            # 迟滞边距（像素，物理）
    HOVER_POLL_MS = 100         # 光标轮询周期

    def __init__(self):
        self.root = ttk.Window(
            title="会议记录",
            themename="litera",
            size=(860, 680),
            minsize=(400, 300),
        )
        self.root.place_window_center()

        # ── 状态变量 ──
        self.current_url = ""
        self.next_url: str | None = None
        self.history: list[str] = []
        self.txt_book: TxtBook | None = None
        self.is_web_mode = True
        self._fetching = False
        self._toolbar_visible = True      # 顶栏是否可见
        self._opacity = 100
        self._drag_x = 0
        self._drag_y = 0
        self._dragging = False
        self._dialog_open = False       # 原生模态对话框打开中
        self._toolbar_was_visible = True

        # ── 阅读模式状态 ──
        self._reading_mode = False        # 是否处于阅读模式（透明悬浮）
        self._boss_hidden = False         # 老板键隐身中（阅读模式下 alpha 0）
        self._reading_toast_shown = False # 首次进入阅读模式的教学提示
        self._reading_key = ""            # 当前色键（透明色）
        self._hover_visible = True        # 悬停显隐当前状态
        self._shown_at = 0.0              # 最近一次显形时刻
        self._hover_job = None            # 悬停轮询 after 任务
        self._hide_job = None             # 延迟隐藏 after 任务

        # ── 平滑滚动状态 ──
        self._smooth_job = None           # 滚动动画 after 任务
        self._scroll_target = 0.0         # 目标滚动位置（行单位）
        self._bottom_consumed = False     # 章底续章防重
        self._auto_loading = False        # 网页自动续章抓取中

        # ── 全局热键/退出状态 ──
        self._exiting = False
        self._exit_req_at = 0.0

        # ── 记忆：进度与设置持久化 ──
        self._appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        self._settings_dir = os.path.join(self._appdata, "moyu-reader")
        self._settings_path = os.path.join(self._settings_dir, "settings.json")
        self._save_job = None            # 保存节流 after 任务
        self._restore_jobs = []          # 滚动恢复确认任务
        self._pending_scroll = None
        self._restoring = False          # 恢复会话中：抑制保存
        self._pending_restore_scroll = None  # 网页恢复待应用的滚动位置

        # ── tkinter 变量 ──
        self.var_font_family = tk.StringVar(value=self.DEFAULT_FONT_FAMILY)
        self.var_font_size = tk.IntVar(value=self.DEFAULT_FONT_SIZE)
        self.var_line_spacing = tk.IntVar(value=self.DEFAULT_LINE_SPACING)
        self.var_topmost = tk.BooleanVar(value=False)
        self.var_text_color = tk.StringVar(value="#777777")
        self.var_status = tk.StringVar(value="就绪 — 右键打开菜单 | 输入网址或打开TXT")
        self.var_url = tk.StringVar()
        self.var_page_info = tk.StringVar()

        self._build_ui()
        self._build_context_menu()
        self._bind_keys()

    # ────────────────────────────────────
    #              界面构建
    # ────────────────────────────────────
    def _build_ui(self):
        # 用原生 tk.Frame 作容器（ttk.Frame 不支持直接改 bg，透明会失效）
        self._default_bg = self.root.cget("bg")

        # ═══ 顶部工具栏（可隐藏） ═══
        self.toolbar = tk.Frame(self.root, bg=self._default_bg, padx=5, pady=3)
        self.toolbar.pack(fill=X)

        tk.Label(self.toolbar, text="网址:", bg=self._default_bg,
                 font=("Microsoft YaHei", 10)).pack(side=LEFT, padx=(0, 4))
        self.entry_url = ttk.Entry(self.toolbar, textvariable=self.var_url, width=55)
        self.entry_url.pack(side=LEFT, fill=X, expand=True, padx=(0, 4))
        self.entry_url.bind("<Return>", lambda e: self._on_fetch())

        self.btn_fetch = ttk.Button(
            self.toolbar, text="抓取", bootstyle=PRIMARY, width=6, command=self._on_fetch,
        )
        self.btn_fetch.pack(side=LEFT, padx=2)

        self.btn_open = ttk.Button(
            self.toolbar, text="打开TXT", bootstyle=INFO, width=8, command=self._on_open_txt,
        )
        self.btn_open.pack(side=LEFT, padx=2)

        # ═══ 标题 ═══
        self.lbl_title = tk.Label(
            self.root, text="", font=("Microsoft YaHei", 14, "bold"),
            anchor=CENTER, bg=self._default_bg, fg="#333333", pady=4,
        )
        self.lbl_title.pack(fill=X)

        # ═══ 正文阅读区 ═══
        self.text_frame = tk.Frame(self.root, bg=self._default_bg)
        self.text_frame.pack(fill=BOTH, expand=True, padx=4, pady=2)

        self.scrollbar = ttk.Scrollbar(self.text_frame, bootstyle="round")
        self.scrollbar.pack(side=RIGHT, fill=Y)

        self.text = tk.Text(
            self.text_frame,
            wrap=tk.WORD,
            font=(self.DEFAULT_FONT_FAMILY, self.DEFAULT_FONT_SIZE),
            spacing1=0,
            spacing2=self.DEFAULT_LINE_SPACING,
            spacing3=0,
            padx=16,
            pady=10,
            relief=tk.FLAT,
            bd=0,
            bg="#FFFFFF",
            fg="#333333",
            selectbackground="#B3D9FF",
            insertwidth=0,
            cursor="arrow",
            yscrollcommand=self.scrollbar.set,
        )
        self.text.pack(side=LEFT, fill=BOTH, expand=True)
        self.scrollbar.config(command=self.text.yview)
        self.text.config(state=tk.DISABLED)

        # ═══ 底部翻页栏 ═══
        self.nav_bar = tk.Frame(self.root, bg=self._default_bg, padx=5, pady=2)
        self.nav_bar.pack(fill=X)

        self.btn_prev = ttk.Button(
            self.nav_bar, text="← 上一页", width=10, command=self._on_prev,
        )
        self.btn_prev.pack(side=LEFT)
        self.btn_prev.config(state=tk.DISABLED)

        self.lbl_page_info = tk.Label(
            self.nav_bar, textvariable=self.var_page_info,
            anchor=CENTER, bg=self._default_bg, font=("Microsoft YaHei", 10),
        )
        self.lbl_page_info.pack(side=LEFT, fill=X, expand=True)

        self.btn_next = ttk.Button(
            self.nav_bar, text="下一页 →", width=10, command=self._on_next,
        )
        self.btn_next.pack(side=RIGHT)
        self.btn_next.config(state=tk.DISABLED)

        # ═══ 状态栏 ═══
        self.status_bar = tk.Label(
            self.root, textvariable=self.var_status,
            relief=tk.SUNKEN, anchor=W, padx=6, pady=2,
            font=("Microsoft YaHei", 9), bg=self._default_bg, fg="#777777",
        )
        self.status_bar.pack(fill=X, side=BOTTOM)

    # ────────────────────────────────────
    #           右键菜单（替代设置面板）
    # ────────────────────────────────────
    def _build_context_menu(self):
        self.ctx_menu = tk.Menu(self.root, tearoff=0, font=("Microsoft YaHei", 10))

        # ── 字体子菜单 ──
        font_menu = tk.Menu(self.ctx_menu, tearoff=0, font=("Microsoft YaHei", 10))
        for f in self.FONT_CHOICES:
            font_menu.add_radiobutton(
                label=f, variable=self.var_font_family, value=f,
                command=self._apply_font,
            )
        self.ctx_menu.add_cascade(label="字体", menu=font_menu)

        # ── 字号子菜单 ──
        size_menu = tk.Menu(self.ctx_menu, tearoff=0, font=("Microsoft YaHei", 10))
        for s in (4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 24, 28):
            size_menu.add_radiobutton(
                label=f"{s} px", variable=self.var_font_size, value=s,
                command=self._apply_font,
            )
        self.ctx_menu.add_cascade(label="字号", menu=size_menu)

        # ── 行距子菜单 ──
        spacing_menu = tk.Menu(self.ctx_menu, tearoff=0, font=("Microsoft YaHei", 10))
        for sp in (0, 1, 2, 3, 4, 6, 8, 10, 14, 18):
            spacing_menu.add_radiobutton(
                label=f"{sp} px", variable=self.var_line_spacing, value=sp,
                command=self._apply_font,
            )
        self.ctx_menu.add_cascade(label="行距", menu=spacing_menu)

        # ── 文字颜色子菜单（阅读模式用） ──
        color_menu = tk.Menu(self.ctx_menu, tearoff=0, font=("Microsoft YaHei", 10))
        for gi, (_group, items) in enumerate(self.READING_COLOR_GROUPS):
            if gi:
                color_menu.add_separator()
            for hexv, name in items:
                color_menu.add_radiobutton(
                    label=name, variable=self.var_text_color, value=hexv,
                    command=self._on_text_color_changed,
                )
        color_menu.add_separator()
        color_menu.add_command(label="自定义…", command=self._pick_text_color)
        self.ctx_menu.add_cascade(label="文字颜色", menu=color_menu)

        self.ctx_menu.add_separator()

        # ── 透明度子菜单（仅普通模式有效） ──
        opacity_menu = tk.Menu(self.ctx_menu, tearoff=0, font=("Microsoft YaHei", 10))
        for pct in (100, 90, 80, 70, 60, 50, 40, 30, 20, 10):
            opacity_menu.add_command(
                label=f"{pct}%",
                command=lambda p=pct: self._set_opacity(p),
            )
        self.ctx_menu.add_cascade(label="窗口透明度", menu=opacity_menu)

        # ── 阅读模式切换（动态文案） ──
        self.ctx_menu.add_command(
            label="⬜ 进入阅读模式",
            accelerator="Shift+Q",
            command=self._toggle_reading_mode,
        )
        self._idx_mode = self.ctx_menu.index("⬜ 进入阅读模式")

        # ── 窗口置顶 ──
        self.ctx_menu.add_checkbutton(
            label="窗口置顶", variable=self.var_topmost,
            command=self._on_topmost_changed,
        )

        self.ctx_menu.add_separator()

        # ── 目录（章节选择） ──
        self.ctx_menu.add_command(
            label="📖 目录（章节选择）",
            accelerator="Ctrl+L",
            command=self._show_toc,
        )

        # ── 显示/隐藏工具栏 ──
        self.ctx_menu.add_command(label="显示/隐藏工具栏", command=self._toggle_toolbar)

        # ── 老板键 ──
        self.ctx_menu.add_command(
            label="老板键·立即隐身 (Esc)",
            accelerator="Ctrl+Alt+M",
            command=self._on_boss_key,
        )

        # ── 退出（两段式确认） ──
        self.ctx_menu.add_command(
            label="退出应用",
            accelerator="Shift+W",
            command=self._safe_exit,
        )

    def _show_context_menu(self, event):
        """弹出右键菜单前，更新阅读模式的标签"""
        self.ctx_menu.entryconfig(
            self._idx_mode,
            label="✅ 返回普通模式" if self._reading_mode else "⬜ 进入阅读模式",
        )
        self.ctx_menu.post(event.x_root, event.y_root)

    def _show_context_menu_center(self, _event=None):
        """键盘 F2 在窗口中央弹出菜单"""
        self.ctx_menu.entryconfig(
            self._idx_mode,
            label="✅ 返回普通模式" if self._reading_mode else "⬜ 进入阅读模式",
        )
        x = self.root.winfo_rootx() + self.root.winfo_width() // 2
        y = self.root.winfo_rooty() + self.root.winfo_height() // 2
        self.ctx_menu.post(x, y)

    # ────────────────────────────────────
    #              快捷键
    # ────────────────────────────────────
    def _bind_keys(self):
        self.root.bind("<Escape>", lambda e: self._on_boss_key())
        self.root.bind("<Control-o>", lambda e: self._on_open_txt())
        self.root.bind("<Control-l>", lambda e: self._show_toc())
        # 窗口内快捷键：Shift+Q 切阅读模式 / Shift+W 退出应用（输入框聚焦时放行）
        self.root.bind("<KeyPress>", self._on_key_press)
        # 滚轮只在 text 上绑定，处理函数 return "break" 截断冒泡防双触发
        self.text.bind("<MouseWheel>", self._on_mousewheel)
        # 方向键绑在 text 上：URL 输入框内的方向键不会误触发翻页/滚动
        self.text.bind("<Left>", lambda e: self._on_prev())
        self.text.bind("<Right>", lambda e: self._on_next())
        self.text.bind("<Up>", lambda e: self.text.yview_scroll(-3, "units"))
        self.text.bind("<Down>", lambda e: self.text.yview_scroll(3, "units"))

        # 右键菜单（鼠标 + 键盘 F2）
        self.root.bind("<Button-3>", self._show_context_menu)
        self.text.bind("<Button-3>", self._show_context_menu)
        self.root.bind("<F2>", self._show_context_menu_center)

    def _on_key_press(self, event):
        """窗口内 Shift+Q 切换阅读模式 / Shift+W 退出应用。
        仅作用于本窗口（不做全局热键），输入框聚焦时直接放行——
        保证在网址栏里照常输入大写 Q/W"""
        if not (event.state & 0x0001):          # 未按 Shift
            return
        widget = self.root.focus_get()
        if widget is not None and widget.winfo_class() in ("Entry", "TEntry"):
            return                               # 放行给输入框
        keysym = event.keysym.lower()
        if keysym == "q":
            self._toggle_reading_mode()
            return "break"
        if keysym == "w":
            self._safe_exit()
            return "break"

    # ────────────────────────────────────
    #         平滑滚动 & 自动续章
    # ────────────────────────────────────
    def _on_mousewheel(self, event):
        # 统一平滑滚动（兼容触控板小 delta）；章底自动续章仅在阅读模式生效
        steps = -event.delta / 40.0
        self._scroll_target = max(0.0, self._scroll_target + steps)
        if self._smooth_job is None:
            self._smooth_job = self.root.after(16, self._smooth_scroll_tick)
        self._schedule_save(1500)   # 滚动停止 1.5s 后记一次位置
        return "break"

    def _smooth_scroll_tick(self):
        """16ms ease-out 步进到目标位置，停稳后检查章底"""
        total = max(int(self.text.index("end-1c").split(".")[0]), 1)
        first, last = self.text.yview()
        cur = first * total
        remaining = self._scroll_target - cur
        # 顶/底短路：已到边界即收敛，防 target 超限导致 16ms 空转、章底续章永不触发
        if last >= 0.9995 and remaining > 0:
            self.text.yview_moveto(1.0)
            self._smooth_job = None
            self._check_bottom()
            return
        if last <= 0.0001 and remaining < 0:
            self._scroll_target = cur
            self._smooth_job = None
            return
        if abs(remaining) < 0.6:
            self._smooth_job = None
            self._check_bottom()
            return
        step = remaining * 0.25
        if abs(step) < 0.6:
            step = 0.6 if remaining > 0 else -0.6
        new = min(max(cur + step, 0.0), float(total))
        self.text.yview_moveto(new / total)
        self._smooth_job = self.root.after(16, self._smooth_scroll_tick)

    def _check_bottom(self):
        """滚动停稳在章底且仍要向下 → 自动续章"""
        if self._bottom_consumed or not self._reading_mode:
            return
        if self.text.yview()[1] >= 0.9995 and self._scroll_target > 0:
            self._maybe_continue_reading()

    def _stop_smooth_scroll(self):
        if self._smooth_job:
            self.root.after_cancel(self._smooth_job)
        self._smooth_job = None
        self._scroll_target = 0.0
        self._bottom_consumed = False

    def _maybe_continue_reading(self):
        """章底触发：TXT 追加下一章；网页后台抓取下一章后追加"""
        if self._bottom_consumed:
            return

        if not self.is_web_mode and self.txt_book:
            if self.txt_book.has_next():
                self._bottom_consumed = True
                self.txt_book.go_next()
                title, content = self.txt_book.current()
                self.lbl_title.config(text=title)
                self.var_page_info.set(
                    f"{self.txt_book.current_index + 1} / {self.txt_book.total}"
                )
                self._append_chapter(title, content)
            else:
                self._show_toast("已是最后一页")
            return

        # ── 网页模式 ──
        if self._auto_loading:
            return
        if not self.next_url:
            self._show_toast("已是最后一章")
            return
        self._bottom_consumed = True
        self._auto_loading = True
        url = self.next_url

        def _do():
            try:
                result = WebFetcher.fetch(url)
                self.root.after(0, lambda: self._on_fetch_done(url, result, append=True))
            except Exception as err:
                msg = str(err)
                self.root.after(0, lambda: self._on_auto_fetch_error(msg))

        threading.Thread(target=_do, daemon=True).start()

    def _append_chapter(self, title: str, content: str):
        """章底无缝追加：保持当前滚动位置，新内容长在视野下方"""
        self.text.config(state=tk.NORMAL)
        self.text.insert(tk.END, "\n\n" + title + "\n\n")
        for line in content.split("\n"):
            line = line.strip()
            if line:
                self.text.insert(tk.END, "　　" + line + "\n")
        self.text.config(state=tk.DISABLED)
        self._bottom_consumed = False
        # 追加改变总行数，把滚动目标重定位到当前位置，避免下次动画反向回滚
        total = max(int(self.text.index("end-1c").split(".")[0]), 1)
        self._scroll_target = self.text.yview()[0] * total
        self._schedule_save(600)

    def _on_auto_fetch_error(self, msg: str):
        self._auto_loading = False
        self._bottom_consumed = False
        self._show_toast(f"自动续章失败: {msg[:40]}")

    # ────────────────────────────────────
    #      阅读模式（透明悬浮+悬停显隐）
    # ────────────────────────────────────
    def _toggle_reading_mode(self):
        if self._reading_mode:
            self._exit_reading_mode()
        else:
            self._enter_reading_mode()
        self._schedule_save(600)

    def _enter_reading_mode(self):
        anchor = self.text.index("@0,0")
        self._reading_mode = True
        self._boss_hidden = False
        self._dragging = False
        self._toolbar_was_visible = self._toolbar_visible
        self._hover_visible = True
        self._shown_at = time.time()

        self.root.attributes("-toolwindow", True)   # 不进任务栏/Alt+Tab
        self.root.overrideredirect(True)            # 去标题栏
        self.root.attributes("-topmost", True)      # 置顶
        self._apply_reading_colors()                # 色键抠底，仅文字悬浮
        self.root.attributes("-alpha", self.HOVER_ALPHA_SHOWN)

        # 隐藏多余控件，仅剩正文
        self.scrollbar.pack_forget()
        self.toolbar.pack_forget()
        self.lbl_title.pack_forget()
        self.nav_bar.pack_forget()
        self.status_bar.pack_forget()
        self._toolbar_visible = False

        # 阅读字体：加粗 + 最小 14px，无衬底时保证辨识度
        self._apply_font()

        # 拖动窗口（按住正文拖）
        self.text.bind("<ButtonPress-1>", self._on_drag_start)
        self.text.bind("<B1-Motion>", self._on_drag_motion)
        self.text.bind("<ButtonRelease-1>", self._on_drag_end)

        self.text.see(anchor)
        self._poll_hover()

        if not self._reading_toast_shown:
            if self._show_toast(
                "已进入阅读模式：悬停显示 / 移开隐身 · Shift+Q 返回普通模式 · Shift+W 退出",
                ms=5000,
            ):
                self._reading_toast_shown = True

    def _exit_reading_mode(self):
        anchor = self.text.index("@0,0")
        self._reading_mode = False
        self._boss_hidden = False

        for job in (self._hover_job, self._hide_job):
            if job:
                self.root.after_cancel(job)
        self._hover_job = None
        self._hide_job = None
        self._stop_smooth_scroll()
        self._dragging = False

        self.text.unbind("<ButtonPress-1>")
        self.text.unbind("<B1-Motion>")
        self.text.unbind("<ButtonRelease-1>")

        self.root.overrideredirect(False)
        self.root.attributes("-toolwindow", False)
        try:
            self.root.attributes("-transparentcolor", "")
        except tk.TclError:
            # Tk 8.6 不支持空串清除：用一个永不出现在界面的颜色兜底。
            # 绝不能设为窗口背景色（否则普通模式整窗被抠透明且点击穿透）
            try:
                self.root.attributes("-transparentcolor", "#010203")
            except tk.TclError:
                pass
        self.root.attributes("-alpha", self._opacity / 100.0)
        self.root.attributes("-topmost", self.var_topmost.get())

        # 恢复配色
        self.root.configure(bg=self._default_bg)
        self.text.config(bg="#FFFFFF", fg="#333333",
                         selectbackground="#B3D9FF")
        self.text_frame.config(bg=self._default_bg)
        self.lbl_title.config(fg="#333333")
        self.status_bar.config(fg="#777777")
        self._apply_font()
        self._rebuild_layout()
        self._toolbar_visible = self._toolbar_was_visible
        if self._toolbar_visible:
            self.toolbar.pack(fill=X, before=self.lbl_title)
        self.text.see(anchor)

    def _apply_reading_appearance(self):
        """按当前模式恢复窗口外观（老板键唤回后调用）"""
        if self._reading_mode:
            self.root.attributes("-toolwindow", True)
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.attributes("-alpha", self.HOVER_ALPHA_SHOWN)
            self._hover_visible = True
            self._shown_at = time.time()
        else:
            self.root.attributes("-toolwindow", False)
            self.root.overrideredirect(False)
            self.root.attributes("-alpha", self._opacity / 100.0)
            self.root.attributes("-topmost", self.var_topmost.get())

    @staticmethod
    def _calc_key_color(fg: str) -> str:
        """色键 = 文字色任一通道 XOR 0x01：与文字混合后视觉不可分（消抗锯齿色晕），
        又不等于文字色（保证字形实心不透明）"""
        r = int(fg[1:3], 16) ^ 0x01
        return f"#{r:02X}{fg[3:].upper()}"

    def _apply_reading_colors(self):
        fg = self.var_text_color.get()
        key = self._calc_key_color(fg)
        self._reading_key = key
        try:
            self.root.attributes("-transparentcolor", key)
        except tk.TclError:
            pass
        self.root.configure(bg=key)
        self.text.config(bg=key, fg=fg, selectbackground="#3A3A3A")
        self.text_frame.config(bg=key)

    def _on_text_color_changed(self):
        if self._reading_mode:
            anchor = self.text.index("@0,0")
            self._apply_reading_colors()
            self._apply_font()
            self.text.see(anchor)
        else:
            self.var_status.set("文字颜色已保存，进入阅读模式后生效")
        self._schedule_save(500)

    def _pick_text_color(self):
        self._dialog_open = True
        try:
            rgb = colorchooser.askcolor(
                color=self.var_text_color.get(), parent=self.root,
            )
        finally:
            self._dialog_open = False
        hexv = rgb[1] if rgb else None
        if hexv:
            self.var_text_color.set(hexv.upper())
            self._on_text_color_changed()

    # ── 悬停显隐：colorkey 窗口上 Enter/Leave 不可靠，改用光标位置轮询 ──
    def _poll_hover(self):
        if not self._reading_mode:
            return
        self._hover_job = self.root.after(self.HOVER_POLL_MS, self._poll_hover)
        if self.root.state() == "withdrawn" or self._boss_hidden:
            return
        if self.root.grab_current() or self._dragging or self._dialog_open:
            return  # 菜单开着 / 拖动中 / 原生对话框：保持显形

        inside = self._cursor_inside_window()
        if inside:
            if not self._hover_visible:
                if self._hide_job:
                    self.root.after_cancel(self._hide_job)
                    self._hide_job = None
                self._hover_visible = True
                self._shown_at = time.time()
                self.root.attributes("-alpha", self.HOVER_ALPHA_SHOWN)
        elif self._hover_visible and time.time() - self._shown_at >= self.MIN_SHOWN_SEC:
            if not self._hide_job:
                self._hide_job = self.root.after(self.HIDE_DELAY_MS, self._hide_hover)

    def _hide_hover(self):
        self._hide_job = None
        if self._reading_mode and not self._cursor_inside_window() \
                and not self.root.grab_current() and not self._dragging \
                and not self._dialog_open:
            self._hover_visible = False
            self.root.attributes("-alpha", self.HOVER_ALPHA_HIDDEN)

    def _cursor_inside_window(self) -> bool:
        """光标是否在窗口矩形内（全部用 Win32 物理像素，避免高 DPI 错位）。
        迟滞：进入判定用全矩形，离开判定用内缩矩形，杜绝边缘抖动"""
        try:
            pt = wt.POINT()
            if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return self._hover_visible
            hwnd = ctypes.windll.user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT
            if not hwnd:
                return self._hover_visible
            rect = wt.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return self._hover_visible
            m = self.HOVER_MARGIN
            if self._hover_visible:
                return (rect.left + m <= pt.x <= rect.right - m
                        and rect.top + m <= pt.y <= rect.bottom - m)
            return rect.left <= pt.x <= rect.right and rect.top <= pt.y <= rect.bottom
        except Exception:
            return self._hover_visible

    # ── Toast 提示（无边框置顶小浮窗，不抢焦点） ──
    def _show_toast(self, text, ms=4000) -> bool:
        try:
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            t.attributes("-alpha", 0.95)
            w = min(max(len(text) * 13 + 60, 280), 720)
            h = 46
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            t.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - 90}")
            tk.Label(t, text=text, bg="#222222", fg="#EEEEEE",
                     font=("Microsoft YaHei", 10), padx=14, pady=8).pack()
            # 仅当主窗可见时归还焦点；隐身/隐藏状态下绝不抢系统焦点
            if not self._boss_hidden and self.root.state() != "withdrawn":
                self.root.focus_set()

            def fade(step=0):
                try:
                    alphas = (0.95, 0.6, 0.3)
                    if step < 3:
                        t.attributes("-alpha", alphas[step])
                        t.after(180, lambda: fade(step + 1))
                    else:
                        t.destroy()
                except tk.TclError:
                    pass

            t.after(ms, fade)
            return True
        except tk.TclError:
            return False

    # ────────────────────────────────────
    #            拖动窗口（无标题栏时）
    # ────────────────────────────────────
    def _on_drag_start(self, event):
        self._dragging = True
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag_motion(self, event):
        x = self.root.winfo_x() + (event.x - self._drag_x)
        y = self.root.winfo_y() + (event.y - self._drag_y)
        self.root.geometry(f"+{x}+{y}")

    def _on_drag_end(self, _event=None):
        self._dragging = False

    def _rebuild_layout(self):
        """将所有控件按正确顺序重新 pack"""
        for w in (self.toolbar, self.lbl_title, self.text_frame,
                  self.nav_bar, self.status_bar):
            w.pack_forget()
        self.status_bar.pack(fill=X, side=BOTTOM)
        self.toolbar.pack(fill=X)
        self.lbl_title.pack(fill=X)
        self.text_frame.pack(fill=BOTH, expand=True, padx=4, pady=2)
        self.nav_bar.pack(fill=X)
        self.scrollbar.pack(side=RIGHT, fill=Y, before=self.text)

    def _set_opacity(self, pct: int):
        if self._reading_mode:
            self._show_toast("阅读模式下显隐由鼠标悬停自动控制")
            return
        self._opacity = pct
        self.root.attributes("-alpha", pct / 100.0)
        self.var_status.set(f"窗口透明度: {pct}%")
        self._schedule_save(500)

    def _on_topmost_changed(self):
        if not self._reading_mode:
            self.root.attributes("-topmost", self.var_topmost.get())
        self._schedule_save(500)

    def _toggle_toolbar(self):
        """显示/隐藏顶部工具栏"""
        if self._reading_mode:
            self._show_toast("阅读模式下工具栏不可用，退出阅读模式后再设置")
            return
        if self._toolbar_visible:
            self.toolbar.pack_forget()
            self._toolbar_visible = False
            self.var_status.set("工具栏已隐藏 — 右键菜单可恢复")
        else:
            # 重新 pack 到最顶部
            self.toolbar.pack(fill=X, before=self.lbl_title)
            self._toolbar_visible = True
            self.var_status.set("工具栏已显示")

    # ────────────────────────────────────
    #          老板键 & 全局热键
    # ────────────────────────────────────
    def _on_boss_key(self):
        """老板键：普通模式=整窗隐藏；阅读模式=完全透明（挂起悬停显隐）"""
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self._boss_hidden = False
            self._apply_reading_appearance()
        elif self._boss_hidden:
            self._boss_hidden = False
            self.root.attributes("-alpha", self.HOVER_ALPHA_SHOWN)
            self._hover_visible = True
            self._shown_at = time.time()
        elif self._reading_mode:
            self._boss_hidden = True
            self.root.attributes("-alpha", 0.0)
        else:
            self.root.withdraw()

    def _setup_global_hotkey(self):
        """注册全局热键（窗口隐藏时也生效）：Ctrl+Alt+M 老板键。
        阅读模式切换与退出已改为窗口内 Shift+Q / Shift+W，不做全局劫持"""
        MOD_CONTROL, MOD_ALT, MOD_NOREPEAT = 0x2, 0x1, 0x4000
        user32 = ctypes.windll.user32
        self._hotkey_queue: queue.Queue = queue.Queue()
        self._hotkey_actions = {}
        # 注册必须在 listen 线程内进行：hWnd=NULL 时 WM_HOTKEY 投递到
        # 注册线程的消息队列，与 GetMessageW 泵必须同线程，否则热键全部失效
        regs = [
            (0xA111, 0x4D, self._on_boss_key),          # M
        ]

        def listen():
            failed = []
            for hid, vk, action in regs:
                if user32.RegisterHotKey(None, hid, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, vk):
                    self._hotkey_actions[hid] = action
                else:
                    failed.append(chr(vk))
            if failed:
                msg_text = "全局热键注册失败: Ctrl+Alt+" + ",".join(failed)
                self.root.after(0, lambda: self.var_status.set(msg_text))
            if not self._hotkey_actions:
                return
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    self._hotkey_queue.put(msg.wParam)

        threading.Thread(target=listen, daemon=True).start()
        self._poll_hotkey()

    def _poll_hotkey(self):
        """主线程轮询热键队列（回调全部在 Tk 主线程执行，安全操作 UI）"""
        try:
            while True:
                hid = self._hotkey_queue.get_nowait()
                action = self._hotkey_actions.get(hid)
                if action:
                    try:
                        action()
                    except tk.TclError:
                        pass  # 单个回调失败不影响其他热键
        except queue.Empty:
            pass
        finally:
            if not self._exiting:
                self.root.after(150, self._poll_hotkey)

    def _cancel_pending(self):
        """退出前取消所有待执行的 after 任务，避免销毁后回调报 invalid command name"""
        for attr in ("_save_job", "_hover_job", "_hide_job", "_smooth_job"):
            job = getattr(self, attr, None)
            if job:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        for job in getattr(self, "_restore_jobs", None) or []:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._restore_jobs = []

    def _safe_exit(self):
        """Shift+W：保存进度后立刻退出（一段式，不弹确认）"""
        if self._exiting:
            return
        self._exiting = True
        self._save_settings_sync()
        self._cancel_pending()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ────────────────────────────────────
    #              字体应用
    # ────────────────────────────────────
    def _apply_font(self, *_args):
        family = self.var_font_family.get()
        size = self.var_font_size.get()
        spacing = self.var_line_spacing.get()
        if self._reading_mode:
            # 无衬底悬浮：加粗 + 最小 14px
            self.text.config(font=(family, max(size, 14), "bold"), spacing2=spacing)
        else:
            self.text.config(font=(family, size), spacing2=spacing)
        self._schedule_save(800)

    # ────────────────────────────────────
    #             内容展示
    # ────────────────────────────────────
    def _display(self, title: str, content: str):
        self._stop_smooth_scroll()
        self.lbl_title.config(text=title)

        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)

        for line in content.split("\n"):
            line = line.strip()
            if line:
                self.text.insert(tk.END, "　　" + line + "\n")

        self.text.config(state=tk.DISABLED)
        self.text.yview_moveto(0)
        self._schedule_save(600)

    # ────────────────────────────────────
    #             网页抓取
    # ────────────────────────────────────
    def _on_fetch(self):
        url = self.var_url.get().strip()
        if not url:
            self.var_status.set("请输入网址")
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.var_url.set(url)
        if self._fetching or self._auto_loading:
            return

        self.is_web_mode = True
        self.txt_book = None
        self._fetching = True
        self.btn_fetch.config(state=tk.DISABLED)
        self.var_status.set(f"正在抓取: {url} ...")

        def _do():
            try:
                result = WebFetcher.fetch(url)
                self.root.after(0, lambda: self._on_fetch_done(url, result))
            except Exception as err:
                msg = str(err)
                self.root.after(0, lambda: self._on_fetch_error(msg))

        threading.Thread(target=_do, daemon=True).start()

    def _on_fetch_done(self, url: str, result: dict, append: bool = False):
        self._fetching = False
        self._auto_loading = False
        self.btn_fetch.config(state=tk.NORMAL)

        if append:
            # 自动续章：追加而不重置视图（抓取期间切换了书源则丢弃过期回调）
            if not self.is_web_mode:
                return
            self.history.append(self.current_url)
            self.current_url = url
            self.next_url = result.get("next_url")
            self.var_url.set(url)
            self._append_chapter(result["title"], result["content"])
            self.var_status.set(f"已续章: {result['title']}")
            self._schedule_save(600)
            return

        self.current_url = url
        self.next_url = result.get("next_url")

        self._display(result["title"], result["content"])

        self.btn_prev.config(state=tk.NORMAL if self.history else tk.DISABLED)
        self.btn_next.config(state=tk.NORMAL if self.next_url else tk.DISABLED)
        self.var_page_info.set("")
        self.var_status.set(f"已加载: {result['title']}")

        # 网页恢复：抓取完成后应用上次的滚动位置
        if self._pending_restore_scroll is not None:
            scroll = self._pending_restore_scroll
            self._pending_restore_scroll = None
            self._restore_scroll(scroll)
            self.var_status.set(f"已恢复上次阅读：{result['title']}")
        self._schedule_save(600)

    def _on_fetch_error(self, msg: str):
        self._fetching = False
        self._auto_loading = False
        self.btn_fetch.config(state=tk.NORMAL)
        self.var_status.set(f"抓取失败: {msg}")
        messagebox.showerror("抓取失败", f"无法获取页面内容：\n{msg}")

    # ────────────────────────────────────
    #             TXT 文件
    # ────────────────────────────────────
    def _on_open_txt(self):
        self._dialog_open = True
        try:
            filepath = filedialog.askopenfilename(
                title="打开文档",
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            )
        finally:
            self._dialog_open = False
        if not filepath:
            return
        try:
            self.txt_book = TxtBook(filepath)
            self.is_web_mode = False
            self.next_url = None
            self.history.clear()
            self._show_txt_page()
            self.var_status.set(
                f"已加载: {os.path.basename(filepath)} ({self.txt_book.total} 章/页)"
            )
        except Exception as e:
            messagebox.showerror("打开失败", f"无法读取文件：\n{e}")

    def _show_txt_page(self):
        if not self.txt_book:
            return
        title, content = self.txt_book.current()
        self._display(title, content)
        self.btn_prev.config(state=tk.NORMAL if self.txt_book.has_prev() else tk.DISABLED)
        self.btn_next.config(state=tk.NORMAL if self.txt_book.has_next() else tk.DISABLED)
        self.var_page_info.set(f"{self.txt_book.current_index + 1} / {self.txt_book.total}")

    # ────────────────────────────────────
    #              目录 / 章节选择
    # ────────────────────────────────────
    def _show_toc(self):
        """弹出章节目录，双击（或回车）跳转"""
        if self.is_web_mode or not self.txt_book:
            self._show_toast("目录仅对 TXT 文件有效（网页模式无固定章节结构）")
            return

        win = getattr(self, "_toc_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_force()
                    return
            except tk.TclError:
                pass

        self._dialog_open = True
        win = tk.Toplevel(self.root)
        self._toc_win = win
        win.title(f"目录 · {self.txt_book.total} 章")
        win.configure(bg="#FFFFFF")
        win.attributes("-topmost", True)
        w, h = 440, 580
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2
        win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")

        # 顶部提示条
        head = tk.Label(
            win, text="双击跳转 · Esc 关闭 · 当前章节已高亮",
            bg="#F5F5F5", fg="#666666", anchor=W, padx=10, pady=6,
            font=("Microsoft YaHei", 9),
        )
        head.pack(fill=X)

        body = tk.Frame(win, bg="#FFFFFF")
        body.pack(fill=BOTH, expand=True, padx=6, pady=(4, 8))
        sb = ttk.Scrollbar(body, bootstyle="round")
        sb.pack(side=RIGHT, fill=Y)
        lb = tk.Listbox(
            body, yscrollcommand=sb.set, font=("Microsoft YaHei", 10),
            activestyle="none", selectbackground="#B3D9FF",
            selectforeground="#000000", bd=0, highlightthickness=0,
            exportselection=False,
        )
        lb.pack(side=LEFT, fill=BOTH, expand=True)
        sb.config(command=lb.yview)

        for i, (title, _content) in enumerate(self.txt_book.chapters):
            lb.insert(tk.END, f"{i + 1:>4}. {title}")

        cur = self.txt_book.current_index
        if 0 <= cur < lb.size():
            lb.selection_clear(0, tk.END)
            lb.selection_set(cur)
            lb.activate(cur)
            lb.see(cur)

        def _close(_event=None):
            self._dialog_open = False
            self._toc_win = None
            try:
                win.destroy()
            except tk.TclError:
                pass

        def _jump(_event=None):
            sel = lb.curselection()
            if not sel:
                return
            idx = int(sel[0])
            _close()
            self._goto_chapter(idx)

        lb.bind("<Double-Button-1>", _jump)
        lb.bind("<Return>", _jump)
        win.bind("<Escape>", _close)
        win.protocol("WM_DELETE_WINDOW", _close)
        lb.focus_set()
        win.after(50, lambda: lb.see(cur) if 0 <= cur < lb.size() else None)

    def _goto_chapter(self, idx: int):
        """跳转到指定章节（目录选择 / 快捷键共用）"""
        if not self.txt_book:
            return
        self.txt_book.go_to(idx)
        self._show_txt_page()
        self._schedule_save(400)
        if self._reading_mode:
            self.text.see("1.0")
        self.var_status.set(
            f"已跳转：{self.txt_book.current()[0]}"
            f"（{idx + 1}/{self.txt_book.total}）"
        )

    # ────────────────────────────────────
    #               翻页
    # ────────────────────────────────────
    def _on_prev(self):
        if not self.is_web_mode and self.txt_book:
            self.txt_book.go_prev()
            self._show_txt_page()
        elif self.is_web_mode and self.history:
            url = self.history.pop()
            self.var_url.set(url)
            self._on_fetch()

    def _on_next(self):
        if not self.is_web_mode and self.txt_book:
            self.txt_book.go_next()
            self._show_txt_page()
        elif self.is_web_mode and self.next_url:
            self.history.append(self.current_url)
            self.var_url.set(self.next_url)
            self._on_fetch()

    # ────────────────────────────────────
    #        记忆：进度与设置持久化
    # ────────────────────────────────────
    def _collect_settings(self) -> dict:
        """收集当前应持久化的状态"""
        data = {
            "version": 1,
            "appearance": {
                "text_color": self.var_text_color.get(),
                "font_family": self.var_font_family.get(),
                "font_size": int(self.var_font_size.get()),
                "line_spacing": int(self.var_line_spacing.get()),
                "opacity": int(self._opacity),
                "topmost": bool(self.var_topmost.get()),
            },
            "scroll": {"yview": 0.0, "line": "1.0"},
            "book": {},
        }
        try:
            first, _last = self.text.yview()
            data["scroll"] = {
                "yview": round(float(first), 6),
                "line": self.text.index("@0,0"),
            }
        except tk.TclError:
            pass

        if not self.is_web_mode and self.txt_book:
            data["book"] = {
                "type": "txt",
                "path": self.txt_book.filepath,
                "chapter": int(self.txt_book.current_index),
            }
        elif self.is_web_mode and self.current_url:
            data["book"] = {"type": "web", "url": self.current_url, "chapter": 0}
        return data

    def _save_settings_sync(self):
        """同步落盘（原子写）；任何异常都吞掉，绝不影响阅读与退出"""
        try:
            data = self._collect_settings()
            os.makedirs(self._settings_dir, exist_ok=True)
            tmp = self._settings_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._settings_path)
        except Exception:
            pass

    def _schedule_save(self, delay_ms: int = 1500):
        """节流保存：滚动等高频事件合并成一次写盘"""
        if self._restoring:
            return
        try:
            if self._save_job:
                self.root.after_cancel(self._save_job)
            self._save_job = self.root.after(delay_ms, self._save_now)
        except tk.TclError:
            pass

    def _save_now(self):
        self._save_job = None
        self._save_settings_sync()

    def _autosave_tick(self):
        """周期兜底（20s）：进程被强杀也能留住最近进度"""
        try:
            if not self._exiting and (self.txt_book or self.current_url):
                self._save_settings_sync()
            if not self._exiting:
                self.root.after(20000, self._autosave_tick)
        except tk.TclError:
            pass

    def _load_settings(self) -> dict:
        try:
            with open(self._settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}   # 坏文件/缺文件一律静默降级为空

    def _restore_last_session(self):
        """启动时恢复上次的书目、章节与滚动位置"""
        data = self._load_settings()
        if not data:
            return
        self._restoring = True
        try:
            # ── 外观 ──
            app = data.get("appearance") or {}
            try:
                if isinstance(app.get("text_color"), str):
                    self.var_text_color.set(app["text_color"])
                if isinstance(app.get("font_family"), str):
                    self.var_font_family.set(app["font_family"])
                if isinstance(app.get("font_size"), int):
                    self.var_font_size.set(app["font_size"])
                if isinstance(app.get("line_spacing"), int):
                    self.var_line_spacing.set(app["line_spacing"])
                if isinstance(app.get("opacity"), int):
                    self._opacity = max(20, min(100, app["opacity"]))
                    self.root.attributes("-alpha", self._opacity / 100.0)
                if isinstance(app.get("topmost"), bool):
                    self.var_topmost.set(app["topmost"])
                    self.root.attributes("-topmost", app["topmost"])
                self._apply_font()
            except Exception:
                pass

            # ── 书目与位置 ──
            book = data.get("book") or {}
            scroll = data.get("scroll") or {}
            btype = book.get("type")

            if btype == "txt" and book.get("path"):
                path = str(book["path"])
                if os.path.isfile(path):
                    try:
                        self.txt_book = TxtBook(path)
                        self.is_web_mode = False
                        self.next_url = None
                        self.history.clear()
                        idx = book.get("chapter")
                        if isinstance(idx, int):
                            self.txt_book.go_to(idx)
                        self._show_txt_page()
                        self._restore_scroll(scroll)
                        self.var_status.set(
                            f"已恢复上次阅读：{os.path.basename(path)}"
                            f"（第 {self.txt_book.current_index + 1}/{self.txt_book.total} 章）"
                        )
                        return
                    except Exception:
                        pass
            elif btype == "web" and book.get("url"):
                url = str(book["url"])
                self.var_url.set(url)
                self._pending_restore_scroll = scroll
                self.var_status.set("正在恢复上次阅读的网页章节…")
                self._on_fetch()
        finally:
            self._restoring = False

    def _restore_scroll(self, scroll: dict):
        """恢复滚动位置：优先 yview 比例，其次首行索引（字号变化时更稳）。
        Tk 在窗口首次布局时会重置视图，故在布局稳定过程中多次确认"""
        self._pending_scroll = scroll
        self._restore_jobs = []
        for delay in (50, 250, 600, 1200, 1800):
            try:
                self._restore_jobs.append(
                    self.root.after(delay, self._apply_pending_scroll)
                )
            except tk.TclError:
                break

    def _apply_pending_scroll(self):
        scroll = getattr(self, "_pending_scroll", None)
        if not scroll:
            return
        try:
            y = scroll.get("yview")
            if isinstance(y, (int, float)) and float(y) > 0:
                self.text.yview_moveto(float(y))
            else:
                line = scroll.get("line")
                if isinstance(line, str):
                    self.text.see(line)
            total = max(int(self.text.index("end-1c").split(".")[0]), 1)
            self._scroll_target = self.text.yview()[0] * total
        except Exception:
            pass

    # ────────────────────────────────────
    #               启动
    # ────────────────────────────────────
    def run(self):
        # 普通模式启动（带标题栏/工具栏），Shift+Q 随时切入阅读模式
        self.root.protocol("WM_DELETE_WINDOW", self._force_exit)
        self._setup_global_hotkey()
        self.root.after(200, self._restore_last_session)
        self.root.after(20000, self._autosave_tick)
        self.root.mainloop()

    def _force_exit(self):
        """窗口 X / Alt+F4：保存进度后退出"""
        if self._exiting:
            return
        self._exiting = True
        self._save_settings_sync()
        self._cancel_pending()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


# ═══════════════════════════════════════════════════════
#                        入口
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        _app = ReaderApp()
        _app.run()
    except Exception:
        # 静默退出：不弹错误窗、不留日志文件（无痕性要求）
        # 设 MOYU_DEBUG=1 可在 stderr 查看 traceback（排障用）
        if os.environ.get("MOYU_DEBUG"):
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)
