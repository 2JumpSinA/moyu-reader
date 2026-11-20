#!/usr/bin/env python3
"""把 docs/plans/issues/*.md 转成 GitHub 网页预填建 issue 链接。

用法:
    python docs/plans/gen_prefill_links.py

输入约定: 每个 md 的第一行是 "# 标题"，其余全部作为 body。
输出: docs/plans/prefill-links.md（stdout 只打印结论行，符合成本纪律）。
"""

from __future__ import annotations

import pathlib
import sys
from urllib.parse import quote

REPO = "2JumpSinA/moyu-reader"
NEW_ISSUE = f"https://github.com/{REPO}/issues/new"
SAFE_URL_BUDGET = 7500  # 浏览器/服务端实际可用约 8k，留余量

HERE = pathlib.Path(__file__).resolve().parent
ISSUE_DIR = HERE / "issues"
OUT = HERE / "prefill-links.md"


def split_issue(text: str) -> tuple[str, str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return line[2:].strip(), "\n".join(lines[i + 1 :]).strip()
    raise SystemExit("找不到 '# 标题' 行")


def section(body: str, heading: str) -> str:
    """取出某个 '## heading' 到下一个 '## ' 之间的内容。"""
    start = body.find(f"\n## {heading}")
    if start < 0:
        return ""
    rest = body[start + 1 :]
    nxt = rest.find("\n## ", 3)
    return rest if nxt < 0 else rest[:nxt]


def mini_body(body: str) -> str:
    """精简版：背景 + 验收标准，够开会话、细节再编辑补充。"""
    parts = [section(body, "背景").strip(), section(body, "验收标准").strip()]
    return "\n\n".join(p for p in parts if p)


def build_url(title: str, body: str, labels: str = "") -> str:
    url = f"{NEW_ISSUE}?title={quote(title, safe='')}"
    if body:
        url += f"&body={quote(body, safe='')}"
    if labels:
        url += f"&labels={quote(labels, safe='')}"
    return url


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    files = sorted(ISSUE_DIR.glob("*.md"))
    if not files:
        print("没有找到 docs/plans/issues/*.md", file=sys.stderr)
        return 1

    rows = []
    for path in files:
        title, body = split_issue(path.read_text(encoding="utf-8"))
        full = build_url(title, body)
        mini = build_url(title, mini_body(body))
        bare = build_url(title, "")
        rows.append(
            {
                "file": path.name,
                "title": title,
                "full": full,
                "full_len": len(full),
                "mini": mini,
                "mini_len": len(mini),
                "bare": bare,
                "bare_len": len(bare),
                "body_len": len(body),
            }
        )

    out = [
        "# 网页预填建 issue 链接（自动生成）",
        "",
        f"> 由 `gen_prefill_links.py` 生成，仓库 `{REPO}`。中文经 URL 编码后长度约 ×9，",
        f"> 单链接按 {SAFE_URL_BUDGET} 字符预算控制（GitHub 侧实际可用约 8k）。",
        "> 推荐路径：先用「仅标题」链接开页，再从 `docs/plans/issues/*.md` 复制正文粘进去。",
        "",
        "| Issue | 正文原长 | 仅标题 | 完整链接 | 精简链接 | 可用性 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r["mini_len"] <= SAFE_URL_BUDGET:
            verdict = "精简版可直接用"
        else:
            verdict = "均超预算 → 用「仅标题」+ 粘贴正文"
        out.append(
            f"| {r['title']} | {r['body_len']} | {r['bare_len']} | {r['full_len']} | {r['mini_len']} | {verdict} |"
        )

    for r in rows:
        out += ["", f"## {r['title']}", "", f"源文件：`docs/plans/issues/{r['file']}`", ""]
        out += ["### 仅标题（推荐）", "", f"[新建 issue]({r['bare']})", ""]
        out += [
            "### 精简正文（背景 + 验收标准）",
            "",
            f"[新建 issue（精简）]({r['mini']})　—　编码后 {r['mini_len']} 字符"
            + ("" if r["mini_len"] <= SAFE_URL_BUDGET else "　⚠️ 超预算，需先删减验收项"),
            "",
        ]
        out += [
            "### 完整正文（留档，长度仅供参考）",
            "",
            f"编码后 {r['full_len']} 字符（正文原长 {r['body_len']}）。",
            "",
            "<details><summary>展开原始 URL</summary>",
            "",
            "```text",
            r["full"],
            "```",
            "",
            "</details>",
            "",
        ]

    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"已生成 {OUT.relative_to(HERE.parent.parent)}")
    for r in rows:
        print(f"  {r['file']}: full={r['full_len']} mini={r['mini_len']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
