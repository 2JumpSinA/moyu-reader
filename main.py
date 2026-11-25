"""
小说阅读器 - 摸鱼神器（改造版）
双模式：普通模式（带标题栏/工具栏，启动默认）/ 阅读模式（背景完全透明、
仅文字悬浮、悬停显示移出隐形、置顶、不进任务栏）
窗口内快捷键：Shift+Ctrl+Z 切换阅读模式 | Shift+Ctrl+X 退出应用 | Esc 老板键隐身
唤回：Ctrl+Shift+V（全局热键）或再次双击启动器，任何隐身状态均可唤回
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
    # 候选字体（family, 别名集, 菜单标签）：中文优先，运行时只显示已安装的。
    # 别名集兼容中文 Windows 的本地化字体名（families() 返回「微软雅黑」等中文名）
    FONT_CHOICES = [
        ("Microsoft YaHei", ("微软雅黑",), "微软雅黑 · 清晰耐看"),
        ("DengXian", ("等线",), "等线 · 现代轻盈"),
        ("SimHei", ("黑体",), "黑体 · 醒目粗犷"),
        ("SimSun", ("宋体", "NSimSun", "新宋体"), "宋体 · 传统印刷"),
        ("KaiTi", ("楷体", "KaiTi_GB2312", "楷体_GB2312"), "楷体 · 书卷气"),
        ("FangSong", ("仿宋", "FangSong_GB2312", "仿宋_GB2312"), "仿宋 · 轻盈纤细"),
        ("Microsoft JhengHei", ("微軟正黑體", "微软正黑"), "微软正黑 · 繁体"),
        ("Yu Gothic", ("游ゴシック", "YuGothic"), "Yu Gothic · 日文小说"),
        ("Malgun Gothic", ("맑은 고딕",), "Malgun · 韩文小说"),
        ("Segoe UI", (), "Segoe UI"),
        ("Calibri", (), "Calibri"),
        ("Cambria", (), "Cambria · 衬线"),
        ("Georgia", (), "Georgia · 衬线"),
        ("Times New Roman", (), "Times New Roman"),
        ("Bahnschrift", (), "Bahnschrift"),
        ("Consolas", (), "Consolas · 等宽"),
        ("Courier New", (), "Courier New · 等宽"),
        ("Arial", (), "Arial"),
    ]
    FONT_FALLBACK = ["Microsoft YaHei", "SimSun", "SimHei"]

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

    # 悬停显隐参数（响应优先：轮询高频、隐藏延迟短）
    HOVER_ALPHA_SHOWN = 1.0     # 悬停时
    HOVER_ALPHA_HIDDEN = 0.02   # 移出时（留 0.02 便于找回）
    HIDE_DELAY_MS = 80          # 移出后延迟隐藏
    MIN_SHOWN_SEC = 0.1         # 最短显形时间，防扫过闪隐
    HOVER_MARGIN = 4            # 迟滞边距（像素，物理）
    HOVER_POLL_MS = 30          # 光标轮询周期（33Hz）
    INPUT_LAYER_ALPHA = 0.01    # 输入层不透明度（再低会失去命中测试）
    MIN_READING_WIDTH = 160     # 阅读模式最小宽
    MIN_READING_HEIGHT = 60     # 阅读模式最小高

    def __init__(self):
        self.root = ttk.Window(
            title="会议记录",
            themename="litera",
            size=(860, 680),
            minsize=(300, 180),
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
        self._resizing = False
        self._resize_w0 = 0
        self._resize_h0 = 0
        self._resize_x0 = 0
        self._resize_y0 = 0
        self._dialog_open = False       # 原生模态对话框打开中
        self._toolbar_was_visible = True

        # ── 阅读模式状态 ──
        self._reading_mode = False        # 是否处于阅读模式（透明悬浮）
        self._boss_hidden = False         # 老板键隐身中（阅读模式下 alpha 0）
        self._layer_shown = False          # 输入层当前是否已显示
        self._force_shown_until = 0.0      # 唤回后的强制显形截止时刻
        self._layer_allowed = True         # 菜单/对话框期间禁止显示输入层
        self._menu_rect = None             # 右键菜单屏幕矩形（防误隐）
        self._reading_toast_shown = False # 首次进入阅读模式的教学提示
        self._reading_key = ""            # 当前色键（透明色）
        self._hover_visible = True        # 悬停显隐当前状态
        self._shown_at = 0.0              # 最近一次显形时刻
        self._hover_job = None            # 悬停轮询 after 任务
        self._hide_job = None             # 延迟隐藏 after 任务

        # ── 平滑滚动状态 ──
        self._smooth_job = None           # 滚动动画 after 任务
        self._scroll_pending = 0.0        # 待滚动行数（相对位移，不用绝对坐标）
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
        self._normal_geometry = None     # 普通模式窗口几何（阅读模式期间保留）

        # ── tkinter 变量 ──
        self.var_font_family = tk.StringVar(value=self.DEFAULT_FONT_FAMILY)
        self.var_font_size = tk.IntVar(value=self.DEFAULT_FONT_SIZE)
        self.var_font_bold = tk.BooleanVar(value=False)   # 正文字体加粗

        # 只把系统实际安装的字体放进菜单（主名或任一别名命中即算安装）
        try:
            from tkinter import font as tkfont
            installed = set(tkfont.families(self.root))
            self.font_menu_items = [
                (fam, label)
                for fam, aliases, label in self.FONT_CHOICES
                if fam in installed or any(a in installed for a in aliases)
            ]
            # 一个都没有时兜底（极端环境）
            if not self.font_menu_items:
                self.font_menu_items = [(f, f) for f in self.FONT_FALLBACK]
            fams = {f for f, _ in self.font_menu_items}
            if self.var_font_family.get() not in fams:
                self.var_font_family.set(self.font_menu_items[0][0])
        except Exception:
            self.font_menu_items = [(f, f) for f in self.FONT_FALLBACK]
        self.var_line_spacing = tk.IntVar(value=self.DEFAULT_LINE_SPACING)
        self.var_topmost = tk.BooleanVar(value=False)
        self.var_text_color = tk.StringVar(value="#777777")
        self.var_scroll_speed = tk.IntVar(value=75)   # 滚轮速度百分比（默认稍慢）
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

        # 按钮先靠右 pack：窗口变窄时由输入框收缩，按钮始终可见可选文件
        self.btn_open = ttk.Button(
            self.toolbar, text="打开TXT", bootstyle=INFO, width=8, command=self._on_open_txt,
        )
        self.btn_open.pack(side=RIGHT, padx=(4, 0))

        self.btn_fetch = ttk.Button(
            self.toolbar, text="抓取", bootstyle=PRIMARY, width=6, command=self._on_fetch,
        )
        self.btn_fetch.pack(side=RIGHT, padx=4)

        tk.Label(self.toolbar, text="网址:", bg=self._default_bg,
                 font=("Microsoft YaHei", 10)).pack(side=LEFT, padx=(0, 4))
        self.entry_url = ttk.Entry(self.toolbar, textvariable=self.var_url, width=10)
        self.entry_url.pack(side=LEFT, fill=X, expand=True, padx=(0, 4))
        self.entry_url.bind("<Return>", lambda e: self._on_fetch())

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
            spacing3=self.DEFAULT_LINE_SPACING,
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
        self._configure_tags()

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

        # ── 字体子菜单（仅列出已安装字体）──
        font_menu = tk.Menu(self.ctx_menu, tearoff=0, font=("Microsoft YaHei", 10))
        for fam, label in self.font_menu_items:
            font_menu.add_radiobutton(
                label=label, variable=self.var_font_family, value=fam,
                command=self._apply_font,
            )
        font_menu.add_separator()
        font_menu.add_checkbutton(
            label="加粗（大字号更耐读）", variable=self.var_font_bold,
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
            accelerator="Shift+Ctrl+Z",
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

        # ── 打开本地文件（工具栏隐藏/窗口过窄时的保底入口） ──
        self.ctx_menu.add_command(
            label="📂 打开TXT…",
            accelerator="Ctrl+O",
            command=self._on_open_txt,
        )

        # ── 窗口尺寸预设 ──
        size_preset = tk.Menu(self.ctx_menu, tearoff=0, font=("Microsoft YaHei", 10))
        for label, (ww, hh) in (
            ("极简条 320×80", (320, 80)),
            ("紧凑 420×140", (420, 140)),
            ("标准 600×200", (600, 200)),
            ("宽松 800×280", (800, 280)),
        ):
            size_preset.add_command(
                label=label,
                command=lambda w=ww, h=hh: self._set_window_size(w, h),
            )
        self.ctx_menu.add_cascade(label="窗口尺寸", menu=size_preset)

        # ── 滚轮速度 ──
        speed_menu = tk.Menu(self.ctx_menu, tearoff=0, font=("Microsoft YaHei", 10))
        for pct, label in (
            (10, "极慢 10%"),
            (20, "很慢 20%"),
            (30, "慢速 30%"),
            (50, "偏慢 50%"),
            (75, "稍慢 75%"),
            (100, "标准 100%"),
            (150, "偏快 150%"),
            (200, "很快 200%"),
        ):
            speed_menu.add_radiobutton(
                label=label, variable=self.var_scroll_speed, value=pct,
                command=self._on_scroll_speed_changed,
            )
        self.ctx_menu.add_cascade(label="滚轮速度", menu=speed_menu)

        # ── 显示/隐藏工具栏 ──
        self.ctx_menu.add_command(label="显示/隐藏工具栏", command=self._toggle_toolbar)

        # ── 老板键 ──
        self.ctx_menu.add_command(
            label="老板键·立即隐身 (Esc) · 唤回 Ctrl+Shift+V",
            command=self._on_boss_key,
        )

        # ── 退出（两段式确认） ──
        self.ctx_menu.add_command(
            label="退出应用",
            accelerator="Shift+Ctrl+X",
            command=self._safe_exit,
        )

    def _show_context_menu(self, event):
        """弹出右键菜单前，更新阅读模式的标签"""
        self.ctx_menu.entryconfig(
            self._idx_mode,
            label="✅ 返回普通模式" if self._reading_mode else "⬜ 进入阅读模式",
        )
        # 菜单是独立窗口：显示期间撤掉输入层，否则菜单项落在窗口范围内点不到
        self._layer_allowed = False
        self._sync_input_layer(False)
        self.ctx_menu.post(event.x_root, event.y_root)
        # 必须在 post 之后测量：菜单未实现时 reqwidth() 只有 1px，
        # 算出的矩形是错的，会被悬停逻辑立刻清掉，导致菜单外点击关不掉
        self.root.update_idletasks()
        self._remember_menu_rect(event.x_root, event.y_root)
        return "break"     # 阻断向 toplevel 冒泡，避免菜单被 post 两次

    def _show_context_menu_center(self, _event=None):
        """键盘 F2 在窗口中央弹出菜单"""
        self.ctx_menu.entryconfig(
            self._idx_mode,
            label="✅ 返回普通模式" if self._reading_mode else "⬜ 进入阅读模式",
        )
        self._layer_allowed = False
        self._sync_input_layer(False)
        x = self.root.winfo_rootx() + self.root.winfo_width() // 2
        y = self.root.winfo_rooty() + self.root.winfo_height() // 2
        self.ctx_menu.post(x, y)
        self.root.update_idletasks()
        self._remember_menu_rect(x, y)

    # ────────────────────────────────────
    #              快捷键
    # ────────────────────────────────────
    def _bind_keys(self):
        self.root.bind("<Escape>", lambda e: self._on_boss_key())
        self.root.bind("<Control-o>", lambda e: self._on_open_txt())
        self.root.bind("<Control-l>", lambda e: self._show_toc())
        # Shift+Ctrl+Z / Shift+Ctrl+X：必须同时绑到 toplevel 和 Entry 本身。
        # ttk.Entry 的类绑定会 return "break" 吃掉按键，只绑 toplevel 时
        # 焦点在网址框内（启动默认焦点）按组合键完全无响应。
        self.root.bind("<KeyPress>", self._on_key_press)
        self.entry_url.bind("<KeyPress>", self._on_key_press, add="+")
        # 滚轮：text 上平滑滚动；toplevel 绑定兜住标题/工具栏/状态栏等区域，
        # 保证鼠标在本窗口任何位置滚轮都作用于阅读器而非背景窗口
        self.text.bind("<MouseWheel>", self._on_mousewheel)
        self.root.bind("<MouseWheel>", self._on_mousewheel)
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
        """窗口内 Shift+Ctrl+Z 切换阅读模式 / Shift+Ctrl+X 退出应用"""
        if not (event.state & 0x0001):          # 未按 Shift
            return
        if not (event.state & 0x0004):          # 未按 Ctrl
            return
        keysym = event.keysym.lower()
        if keysym == "z":
            self._toggle_reading_mode()
            return "break"
        if keysym == "x":
            self._safe_exit()
            return "break"

    # ────────────────────────────────────
    #         平滑滚动 & 自动续章
    # ────────────────────────────────────
    def _on_mousewheel(self, event):
        # Tk 绑定兜底（钩子未安装或被安全软件拦截时仍可用）
        self._apply_wheel(event.delta)
        return "break"

    def _smooth_scroll_tick(self):
        """16ms ease-out 相对步进（不依赖绝对坐标，布局变化也不会跳）"""
        try:
            first, last = self.text.yview()
        except tk.TclError:
            self._smooth_job = None
            return
        span = max(last - first, 1e-6)
        max_first = max(1.0 - span, 0.0)
        pending = self._scroll_pending

        if abs(pending) < 0.3:
            self._smooth_job = None
            self._scroll_pending = 0.0
            if pending > 0 and first >= max_first - 1e-4:
                self._check_bottom()
            return

        total = max(int(self.text.index("end-1c").split(".")[0]), 1)
        step = pending * 0.25
        if abs(step) < 0.3:
            step = 0.3 if pending > 0 else -0.3

        new_first = min(max(first + step / total, 0.0), max_first)
        moved = new_first - first
        self.text.yview_moveto(new_first)
        self._scroll_pending = pending - moved * total

        # 已顶到边界但仍有剩余位移：结束动画；向下则触发续章
        if abs(moved) < 1e-9 and abs(self._scroll_pending) > 0.3:
            self._smooth_job = None
            self._scroll_pending = 0.0
            if pending > 0:
                self._check_bottom()
            return
        self._smooth_job = self.root.after(16, self._smooth_scroll_tick)

    def _check_bottom(self):
        """滚动停稳在章底且仍要向下 → 自动续章"""
        if self._bottom_consumed or not self._reading_mode:
            return
        if self.text.yview()[1] >= 0.9995:
            self._maybe_continue_reading()

    def _stop_smooth_scroll(self):
        if self._smooth_job:
            self.root.after_cancel(self._smooth_job)
        self._smooth_job = None
        self._scroll_pending = 0.0
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
        self.text.insert(tk.END, "\n\n")
        self._insert_chapter_title(title)
        for line in content.split("\n"):
            line = line.strip()
            if line:
                self.text.insert(tk.END, "　　" + line + "\n")
        self.text.config(state=tk.DISABLED)
        self._bottom_consumed = False
        # 追加改变总行数：清空待滚动量（相对位移模型不受影响）
        self._scroll_pending = 0.0
        self._schedule_save(600)

    def _insert_chapter_title(self, title: str):
        """章节标题：加粗 + 居中 + 上下留白，滚动时一眼看出已进入下一章"""
        if not title:
            return
        self.text.insert(tk.END, f"{title}\n", "chapter")

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
        # 先记录普通模式窗口几何，供记忆与退出时恢复
        try:
            self._normal_geometry = self.root.winfo_geometry()
        except tk.TclError:
            pass
        self._reading_mode = True
        self._boss_hidden = False
        self._dragging = False
        self._toolbar_was_visible = self._toolbar_visible
        self._hover_visible = True
        self._shown_at = time.time()

        self.root.attributes("-toolwindow", True)   # 不进任务栏/Alt+Tab
        self._set_overrideredirect(True)            # 去标题栏
        self.root.minsize(self.MIN_READING_WIDTH, self.MIN_READING_HEIGHT)
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

        # 阅读字体：与普通模式完全一致（字号/字重不做额外处理）
        self._apply_font()

        # 拖动窗口（按住正文拖）
        self.text.bind("<ButtonPress-1>", self._on_drag_start)
        self.text.bind("<B1-Motion>", self._on_drag_motion)
        self.text.bind("<ButtonRelease-1>", self._on_drag_end)

        self.text.see(anchor)
        # 布局变化（隐藏控件/换字体）后总行数会变，重定位滚动目标，防首滚方向反
        self._reset_scroll_target()
        # 输入层：透明区域也能拖拽/右键
        self._ensure_input_layer()
        self._sync_input_layer(True)
        self._poll_hover()

        if not self._reading_toast_shown:
            if self._show_toast(
                "已进入阅读模式：悬停显示 / 移开隐身 · Shift+Ctrl+Z 返回普通模式 · Shift+Ctrl+X 退出",
                ms=5000,
            ):
                self._reading_toast_shown = True

    def _exit_reading_mode(self):
        anchor = self.text.index("@0,0")
        self._reading_mode = False
        self._boss_hidden = False
        self._sync_input_layer(False)

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

        self._set_overrideredirect(False)
        self.root.attributes("-toolwindow", False)
        self.root.minsize(300, 180)
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
        self._reset_scroll_target()

    def _apply_reading_appearance(self):
        """按当前模式恢复窗口外观（老板键唤回后调用）"""
        if self._reading_mode:
            self.root.attributes("-toolwindow", True)
            self._set_overrideredirect(True)
            self.root.attributes("-topmost", True)
            self.root.attributes("-alpha", self.HOVER_ALPHA_SHOWN)
            self._hover_visible = True
            self._shown_at = time.time()
        else:
            self.root.attributes("-toolwindow", False)
            self._set_overrideredirect(False)
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
    def _close_menu(self):
        """关闭右键菜单并恢复输入层"""
        try:
            self.ctx_menu.unpost()
        except tk.TclError:
            pass
        self._menu_rect = None
        self._layer_allowed = True

    def _remember_menu_rect(self, x: int, y: int):
        """记录菜单的屏幕矩形（菜单是原生窗口，取不到实时几何，
        用 post 坐标 + 请求尺寸估算），供悬停判定避免误隐窗口"""
        try:
            ww = max(self.ctx_menu.winfo_reqwidth(), 120)
            hh = max(self.ctx_menu.winfo_reqheight(), 80)
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x0 = x - ww if x + ww > sw else x
            y0 = y - hh if y + hh > sh else y
            self._menu_rect = (x0, y0, x0 + ww, y0 + hh)
        except tk.TclError:
            self._menu_rect = None

    def _cursor_in_menu(self) -> bool:
        """光标是否落在已弹出的右键菜单矩形内。
        菜单是原生窗口，winfo_ismapped/WindowFromPoint 都不可靠，
        用 post 时的坐标 + 菜单请求尺寸构造的矩形来判断"""
        rect = getattr(self, "_menu_rect", None)
        if not rect:
            return False
        try:
            pt = wt.POINT()
            if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return False
            x0, y0, x1, y1 = rect
            return x0 <= pt.x <= x1 and y0 <= pt.y <= y1
        except Exception:
            return False

    def _poll_hover(self):
        if not self._reading_mode:
            return
        self._hover_job = self.root.after(self.HOVER_POLL_MS, self._poll_hover)
        if self.root.state() == "withdrawn" or self._boss_hidden:
            return
        if self.root.grab_current() or self._dragging or self._dialog_open:
            return  # 菜单开着 / 拖动中 / 原生对话框：保持显形

        in_reader = self._cursor_inside_window()
        in_menu = self._cursor_in_menu()
        inside = in_reader or in_menu
        if self._menu_rect and not inside:
            # 光标已离开菜单和窗口：菜单矩形立即失效，
            # 否则菜单关闭后那片区域仍被当作"在菜单上"，导致离开窗口不隐身
            self._menu_rect = None
        if inside:
            if not self._hover_visible:
                if self._hide_job:
                    self.root.after_cancel(self._hide_job)
                    self._hide_job = None
                self._hover_visible = True
                self._shown_at = time.time()
                self.root.attributes("-alpha", self.HOVER_ALPHA_SHOWN)
                self._sync_input_layer(True)
            else:
                # 菜单关闭后把输入层恢复回来（拖动/右键要用）
                self._sync_input_layer(True)
        elif self._hover_visible and time.time() - self._shown_at >= self.MIN_SHOWN_SEC:
            self._layer_allowed = True      # 光标离开所有我方窗口：菜单已关，允许恢复输入层
            # 唤回后 3 秒强制显形期：让用户看到窗口回来了
            if time.time() < self._force_shown_until:
                return
            if not self._hide_job:
                self._hide_job = self.root.after(self.HIDE_DELAY_MS, self._hide_hover)

    def _hide_hover(self):
        self._hide_job = None
        if time.time() < self._force_shown_until:
            return
        if self._reading_mode and not self._cursor_inside_window() \
                and not self._cursor_in_menu() \
                and not self.root.grab_current() and not self._dragging \
                and not self._dialog_open:
            self._hover_visible = False
            self.root.attributes("-alpha", self.HOVER_ALPHA_HIDDEN)
            self._sync_input_layer(False)

    # ────────────────────────────────────
    #   输入层：色键透明窗口的透明区域不接收鼠标，用一层几乎不可见
    #   （alpha 0.01）的窗口覆盖其上，负责拖拽与右键
    # ────────────────────────────────────
    def _ensure_input_layer(self):
        w = getattr(self, "_input_layer", None)
        if w is not None:
            try:
                if w.winfo_exists():
                    return w
            except tk.TclError:
                pass
        w = tk.Toplevel(self.root)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", self.INPUT_LAYER_ALPHA)   # 视觉不可见，但命中测试有效
        try:
            w.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        w.configure(bg="#000000", cursor="arrow")
        w.bind("<ButtonPress-1>", self._layer_drag_start)
        w.bind("<B1-Motion>", self._layer_drag_motion)
        w.bind("<ButtonRelease-1>", self._layer_drag_end)
        w.bind("<Button-3>", self._layer_right_click)
        # 点击/拖拽后键盘焦点会落到输入层（独立 Toplevel，bindtags 不经过主窗），
        # 必须把它用到的按键也绑全，否则 Esc/目录/打开文件在阅读模式下失效
        w.bind("<KeyPress>", self._on_key_press)
        w.bind("<Escape>", lambda e: self._on_boss_key())
        w.bind("<Control-l>", lambda e: self._show_toc())
        w.bind("<Control-o>", lambda e: self._on_open_txt())
        w.bind("<F2>", self._show_context_menu_center)
        self._input_layer = w
        return w

    def _sync_input_layer(self, show: bool):
        w = getattr(self, "_input_layer", None)
        if w is None:
            return
        if show and (self._dialog_open or not self._layer_allowed):
            return   # 目录/菜单打开时不显示输入层，避免盖住它们
        try:
            if show:
                x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
                ww, hh = self.root.winfo_width(), self.root.winfo_height()
                if ww < 10 or hh < 10:
                    return
                w.geometry(f"{ww}x{hh}+{x}+{y}")
                if not self._layer_shown:
                    w.deiconify()
                    self._layer_shown = True
                # deiconify 后分层属性可能被重置：每次显示都复断言，防止变成不透明色块
                w.configure(bg="#000000")
                w.attributes("-alpha", self.INPUT_LAYER_ALPHA)
                w.attributes("-topmost", True)
                w.lift()
            else:
                w.withdraw()
                self._layer_shown = False
        except tk.TclError:
            pass

    def _layer_drag_start(self, event):
        # 右下角 18px 内按下 = 缩放窗口，其余区域 = 移动窗口
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        ww, hh = self.root.winfo_width(), self.root.winfo_height()
        if (rx + ww - event.x_root) <= 18 and (ry + hh - event.y_root) <= 18:
            self._resizing = True
            self._resize_w0, self._resize_h0 = ww, hh
            self._resize_x0, self._resize_y0 = event.x_root, event.y_root
            return
        self._dragging = True
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _layer_drag_motion(self, event):
        if self._resizing:
            new_w = max(self.MIN_READING_WIDTH, self._resize_w0 + (event.x_root - self._resize_x0))
            new_h = max(self.MIN_READING_HEIGHT, self._resize_h0 + (event.y_root - self._resize_y0))
            try:
                self.root.geometry(f"{new_w}x{new_h}")
                self._sync_input_layer(True)
            except tk.TclError:
                pass
            return
        if not self._dragging:
            return
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        try:
            self.root.geometry(f"+{x}+{y}")
            self._sync_input_layer(True)
        except tk.TclError:
            pass

    def _layer_drag_end(self, _event=None):
        self._dragging = False
        if self._resizing:
            self._resizing = False
            self._schedule_save(400)   # 记住新尺寸

    def _layer_right_click(self, event):
        self._show_context_menu(event)

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
        self._sync_input_layer(True)

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
    #          老板键（窗口内 Esc）
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
            self._sync_input_layer(False)
        else:
            self.root.withdraw()

    # ────────────────────────────────────
    #       滚轮接管（Win32 低级鼠标钩子）
    # ────────────────────────────────────
    def _setup_wheel_hook(self):
        """用 WH_MOUSE_LL 钩子接管滚轮：指针落在本窗口矩形内时由阅读器处理并
        吞掉事件，背景窗口（浏览器/IDE）永远收不到——彻底解决"滚两下就滚到
        背景网页"的问题。Tk 自身的 <MouseWheel> 绑定保留作兜底。"""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        WH_MOUSE_LL = 14
        WM_MOUSEWHEEL = 0x020A
        self._wheel_queue: queue.Queue = queue.Queue()
        self._wheel_rect = None
        self._wheel_hook = None
        self._wheel_active = True    # 主线程维护：钩子线程只读

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("pt", wt.POINT),
                ("mouseData", wt.DWORD),
                ("flags", wt.DWORD),
                ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_void_p),
            ]

        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
        # 必须声明签名：64 位下 lParam 超出 c_int 会抛 OverflowError，
        # 导致钩子回调中途异常、滚轮事件丢失
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t

        def _pass_through(n_code, w_param, l_param):
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        def _hook(n_code, w_param, l_param):
            try:
                if n_code >= 0 and w_param == WM_MOUSEWHEEL:
                    info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    rect = self._wheel_rect
                    # 目录/对话框打开时让行：否则事件会被吞掉作用到背后正文，
                    # 目录自己的 Listbox 反而滚不动
                    if rect and self._wheel_active and not self._dialog_open:
                        x, y = info.pt.x, info.pt.y
                        if rect[0] <= x <= rect[1] and rect[2] <= y <= rect[3]:
                            delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
                            self._wheel_queue.put(delta)
                            return 1        # 吞掉：背景窗口收不到
                elif n_code >= 0 and w_param in (0x0201, 0x0204, 0x020A, 0x020B):
                    # 左键/右键按下：菜单开着且点在菜单外 → 关闭菜单
                    # （Tk 的 Menu.post() 不设 grab，点窗口外的事件到不了 Tk）
                    if self._menu_rect:
                        info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                        x, y = info.pt.x, info.pt.y
                        mx0, my0, mx1, my1 = self._menu_rect
                        if not (mx0 <= x <= mx1 and my0 <= y <= my1):
                            self._wheel_queue.put("UNPOST_MENU")
            except Exception:
                pass
            return _pass_through(n_code, w_param, l_param)

        self._wheel_proc = HOOKPROC(_hook)   # 必须保持引用，否则回调被回收

        def listen():
            # 低级钩子的 hMod 必须是 NULL（传 exe 句柄会失败：ERROR_MOD_NOT_FOUND 126）
            user32.SetWindowsHookExW.argtypes = [
                ctypes.c_int, HOOKPROC, ctypes.c_void_p, wt.DWORD
            ]
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            self._wheel_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._wheel_proc, None, 0)
            if not self._wheel_hook:
                return   # 安装失败：Tk 绑定兜底继续可用
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        threading.Thread(target=listen, daemon=True).start()
        self._poll_wheel()

    def _target_visible(self) -> bool:
        """钩子线程用：窗口是否应接管滚轮"""
        try:
            if self._exiting or self.root.state() == "withdrawn":
                return False
            if self._reading_mode and self._boss_hidden:
                return False
            return True
        except Exception:
            return False

    def _refresh_wheel_rect(self):
        """主线程刷新窗口屏幕矩形（物理像素），供钩子线程快速判断"""
        try:
            hwnd = ctypes.windll.user32.GetAncestor(self.root.winfo_id(), 2)
            if not hwnd:
                self._wheel_rect = None
                return
            r = wt.RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
                self._wheel_rect = (r.left, r.right, r.top, r.bottom)
            else:
                self._wheel_rect = None
        except Exception:
            self._wheel_rect = None

    def _poll_wheel(self):
        """主线程消费滚轮队列（Tk 操作必须在主线程）"""
        self._refresh_wheel_rect()
        # 在主线程计算"是否应接管滚轮"：钩子线程里严禁调用 Tk API
        try:
            self._wheel_active = (
                not self._exiting
                and self.root.state() != "withdrawn"
                and not (self._reading_mode and self._boss_hidden)
            )
        except tk.TclError:
            self._wheel_active = False
        try:
            while True:
                item = self._wheel_queue.get_nowait()
                if item == "UNPOST_MENU":
                    self._close_menu()
                else:
                    self._apply_wheel(item)
        except queue.Empty:
            pass
        except Exception:
            pass
        if not self._exiting:
            try:
                self.root.after(60, self._poll_wheel)
            except tk.TclError:
                pass

    def _cancel_restore_jobs(self):
        """取消启动恢复的滚动确认任务（用户一旦自己滚动/换书就不能再拽回去）"""
        for job in getattr(self, "_restore_jobs", None) or []:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._restore_jobs = []
        self._pending_scroll = None

    def _on_scroll_speed_changed(self):
        self.var_status.set(f"滚轮速度: {self.var_scroll_speed.get()}%")
        self._show_toast(f"滚轮速度已设为 {self.var_scroll_speed.get()}%")
        self._schedule_save(400)

    def _apply_wheel(self, delta: int):
        """把滚轮增量落到正文（平滑滚动 + 章底续章）"""
        if not delta:
            return
        self._cancel_restore_jobs()
        speed = max(10, min(300, int(self.var_scroll_speed.get()))) / 100.0
        steps = (-delta / 40.0) * speed
        self._scroll_pending += steps
        if self._smooth_job is None:
            self._smooth_job = self.root.after(16, self._smooth_scroll_tick)
        self._schedule_save(1500)

    # ────────────────────────────────────
    #        窗口样式安全封装
    # ────────────────────────────────────
    def _set_overrideredirect(self, on: bool):
        """安全设置无边框：直接走 Tk 原生命令。
        ttkbootstrap 的包装在设置时仍解析返回值，Tk 某些状态下返回空会抛
        TclError: expected boolean value but got "None" """
        try:
            self.root.tk.call("wm", "overrideredirect", self.root._w, 1 if on else 0)
        except tk.TclError:
            pass

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
        """Shift+Ctrl+X：保存进度后立刻退出（一段式，不弹确认）"""
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
        # 两种模式使用完全相同的字号/字重，避免切换时视觉跳变
        # spacing3 与 spacing2 保持一致：段落边界间距(spacing3+spacing1)与段内折行间距相同，
        # 否则段落交界处会比段内行距更紧，看起来行距不均匀
        weight = "bold" if self.var_font_bold.get() else "normal"
        self.text.config(font=(family, size, weight), spacing2=spacing, spacing3=spacing)
        self._configure_tags()
        self._reset_scroll_target()
        self._schedule_save(800)

    def _configure_tags(self):
        """章节标题样式：比正文大 2px 且加粗居中，滚动时章节边界一眼可辨"""
        family = self.var_font_family.get()
        size = self.var_font_size.get()
        try:
            self.text.tag_configure(
                "chapter",
                font=(family, max(size + 2, 10), "bold"),
                justify="center",
                spacing1=16,
                spacing2=0,
                spacing3=12,
            )
        except tk.TclError:
            pass

    def _set_window_size(self, ww: int, hh: int):
        """设置窗口尺寸（阅读模式下的条状阅读）"""
        try:
            self.root.geometry(f"{ww}x{hh}")
            self._sync_input_layer(True)
            self._schedule_save(400)
        except tk.TclError:
            pass

    def _reset_scroll_target(self):
        """布局/内容变化后清空待滚动量，避免用旧坐标步进"""
        self._scroll_pending = 0.0

    # ────────────────────────────────────
    #             内容展示
    # ────────────────────────────────────
    def _display(self, title: str, content: str):
        self._cancel_restore_jobs()
        self._stop_smooth_scroll()
        # 标题已作为加粗首行写入正文，标签不再重复显示（否则同屏两份标题）
        self.lbl_title.config(text="")

        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)

        self._insert_chapter_title(title)
        self.text.insert(tk.END, "\n")

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
        self._sync_input_layer(False)
        win = tk.Toplevel(self.root)
        self._toc_win = win
        win.title(f"目录 · {self.txt_book.total} 章")
        win.configure(bg="#FFFFFF")
        win.attributes("-topmost", True)
        # 关键：Toplevel 可能继承主窗的 alpha / 色键（阅读模式下主窗 alpha 很低），
        # 那样目录会变成几乎看不见或整窗被抠空——这里强制复位
        try:
            win.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        try:
            win.attributes("-transparentcolor", "")
        except tk.TclError:
            try:
                win.attributes("-transparentcolor", "#010203")
            except tk.TclError:
                pass
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
            exportselection=False, fg="#1F1F1F", bg="#FFFFFF",
            selectborderwidth=0,
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

        def _lb_wheel(event):
            step = -1 if event.delta > 0 else 1
            lb.yview_scroll(step * 3, "units")
            return "break"

        lb.bind("<MouseWheel>", _lb_wheel)
        win.bind("<MouseWheel>", _lb_wheel)
        win.bind("<Escape>", _close)
        win.protocol("WM_DELETE_WINDOW", _close)
        tk.Label(
            win, text=f"共 {self.txt_book.total} 章 · 当前第 {cur + 1} 章",
            bg="#F5F5F5", fg="#666666", anchor=W, padx=10, pady=4,
            font=("Microsoft YaHei", 9),
        ).pack(fill=X, side=BOTTOM)
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
                "font_bold": bool(self.var_font_bold.get()),
                "line_spacing": int(self.var_line_spacing.get()),
                "opacity": int(self._opacity),
                "topmost": bool(self.var_topmost.get()),
                "scroll_speed": int(self.var_scroll_speed.get()),
            },
            "scroll": {"yview": 0.0, "line": "1.0"},
            "window": {"geometry": ""},
            "book": {},
        }
        try:
            geo = self.root.winfo_geometry()
            if geo:
                data["window"] = {"geometry": geo}
        except tk.TclError:
            pass
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
                if isinstance(app.get("font_bold"), bool):
                    self.var_font_bold.set(app["font_bold"])
                if isinstance(app.get("line_spacing"), int):
                    self.var_line_spacing.set(app["line_spacing"])
                if isinstance(app.get("scroll_speed"), int):
                    self.var_scroll_speed.set(max(10, min(300, app["scroll_speed"])))
                if isinstance(app.get("opacity"), int):
                    self._opacity = max(20, min(100, app["opacity"]))
                    self.root.attributes("-alpha", self._opacity / 100.0)
                if isinstance(app.get("topmost"), bool):
                    self.var_topmost.set(app["topmost"])
                    self.root.attributes("-topmost", app["topmost"])
                self._apply_font()
            except Exception:
                pass

            # ── 窗口尺寸与位置 ──
            win = data.get("window") or {}
            geo = win.get("geometry")
            if isinstance(geo, str) and "x" in geo and "+" in geo:
                try:
                    self.root.geometry(geo)
                    self._normal_geometry = geo
                except tk.TclError:
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
            self._scroll_pending = 0.0
        except Exception:
            pass

    # ────────────────────────────────────
    #               启动
    # ────────────────────────────────────
    def set_activate_event(self, event_handle):
        """接收单实例激活事件句柄（第二个实例启动时触发）"""
        self._activate_event = event_handle

    def _poll_activation(self):
        """轮询激活事件：第二次启动时把已有窗口唤到前台"""
        ev = getattr(self, "_activate_event", None)
        if ev:
            try:
                if ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(ev), 0) == 0:
                    self._activate_window()
            except Exception:
                pass
        if not self._exiting:
            try:
                self.root.after(300, self._poll_activation)
            except tk.TclError:
                pass

    # ────────────────────────────────────
    #   全局唤回热键（Ctrl+Shift+V）
    # ────────────────────────────────────
    def _setup_recall_hotkey(self):
        """注册全局热键 Ctrl+Shift+V：任何状态下把窗口唤回前台。
        隐身（Esc/老板键）后窗口收不到键盘事件，必须有全局热键兜底；
        双击启动器（单实例激活）是等效的备用唤回方式"""
        MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x2, 0x4, 0x4000
        user32 = ctypes.windll.user32
        self._recall_queue: queue.Queue = queue.Queue()
        # 注册必须在钩子线程内进行（WM_HOTKEY 投递到注册线程的消息队列）
        VK_V = 0x56

        def listen():
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetModuleHandleW.restype = wt.HMODULE
            user32.SetWindowsHookExW  # noqa: 仅注释占位，保持属性已加载
            if not user32.RegisterHotKey(None, 0xA114, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_V):
                return   # 被占用：双击启动器仍可唤回
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    self._recall_queue.put(msg.wParam)

        threading.Thread(target=listen, daemon=True).start()
        self._poll_recall()

    def _poll_recall(self):
        """主线程轮询唤回热键队列"""
        try:
            while True:
                self._recall_queue.get_nowait()
                try:
                    self._activate_window()
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        finally:
            if not self._exiting:
                try:
                    self.root.after(150, self._poll_recall)
                except tk.TclError:
                    pass

    def _activate_window(self):
        """把窗口从隐藏/最小化/隐身状态恢复到可见并置前。
        唤回后强制显形 3 秒（鼠标不在窗口上也先亮出来），之后交还悬停机制"""
        try:
            if self.root.state() == "withdrawn":
                self.root.deiconify()
            self._boss_hidden = False
            if self._reading_mode:
                self.root.attributes("-alpha", self.HOVER_ALPHA_SHOWN)
                self.root.attributes("-topmost", True)
                self._hover_visible = True
                self._shown_at = time.time()
                self._force_shown_until = time.time() + 3.0
                self._sync_input_layer(True)
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def run(self):
        # 普通模式启动（带标题栏/工具栏），Shift+Ctrl+Z 随时切入阅读模式
        # 隐身（老板键）后 Ctrl+Shift+V 或再次双击启动器即可唤回
        self.root.protocol("WM_DELETE_WINDOW", self._force_exit)
        self._setup_recall_hotkey()
        self._setup_wheel_hook()
        self._poll_activation()
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
#                   单实例守护
# ═══════════════════════════════════════════════════════
MUTEX_NAME = "Local\\MoyuReader_SingleInstance"
ACTIVATE_EVENT = "Local\\MoyuReader_Activate"
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002


def acquire_single_instance():
    """返回 (是否首个实例, 激活事件句柄)。
    非首个实例：向已运行实例发激活信号后应立即退出，避免多开抢热键/重复窗口。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # 关键：必须用 use_last_error=True 的 WinDLL。
    # ctypes.windll 的 GetLastError() 会被 Python 内部调用冲掉、恒返回 0，
    # "互斥量已存在"永远检测不到 → 可以无限多开。
    # 必须声明 argtypes：否则 Python str 按 ANSI 传给宽字符 API，名称编码错误。
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateEventW.restype = ctypes.c_void_p
    kernel32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.SetEvent.argtypes = [ctypes.c_void_p]

    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    if already:
        ev = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, ACTIVATE_EVENT)
        if ev:
            kernel32.SetEvent(ctypes.c_void_p(ev))
            kernel32.CloseHandle(ctypes.c_void_p(ev))
        else:
            # 兜底：按窗口标题找到已有实例并唤到前台
            try:
                u = ctypes.windll.user32
                hwnd = u.FindWindowW(None, "会议记录")
                if hwnd:
                    u.ShowWindow(hwnd, 9)      # SW_RESTORE
                    u.SetForegroundWindow(hwnd)
            except Exception:
                pass
        return False, None

    ev = kernel32.CreateEventW(None, False, False, ACTIVATE_EVENT)
    return True, ev


# ═══════════════════════════════════════════════════════
#                        入口
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        _first, _activate_event = acquire_single_instance()
        if not _first:
            import sys
            sys.exit(0)          # 已有实例：已发出激活信号，直接退出
        _app = ReaderApp()
        _app.set_activate_event(_activate_event)
        _app.run()
    except SystemExit:
        raise
    except BaseException:
        # 静默退出：不弹错误窗、不留日志文件（无痕性要求）
        # 设 MOYU_DEBUG=1 可在 stderr 查看 traceback（排障用）
        if os.environ.get("MOYU_DEBUG"):
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)
