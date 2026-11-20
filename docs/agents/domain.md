# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root（若不存在则静默继续）
- **`docs/adr/`**：读与本次改动相关的 ADR

这些文件不存在时**静默继续**，不要提示缺失、不要主动建议创建。
`/domain-modeling`（经 `/grill-with-docs`、`/improve-codebase-architecture`）会在术语与决策真正确定时惰性创建。

## File structure

单上下文仓库（本仓库）：

```
/
├── GLOSSARY.md
├── docs/adr/
│   └── 0001-*.md
└── main.py
```

## 关键领域术语（待 GLOSSARY.md 建立后迁入）

- **普通模式**：带标题栏/工具栏的常规窗口，启动默认。
- **阅读模式**：无边框、置顶、`-transparentcolor` 色键抠底，仅文字悬浮于桌面。
- **色键（transparent key）**：`root.attributes("-transparentcolor", key)`；取文字色某通道 XOR 0x01，消抗锯齿色晕。
- **悬停显隐**：阅读模式下光标在窗口矩形内 → `alpha 1.0`；移出 → `alpha 0.02`。用 Win32 光标轮询实现（色键窗口背景会穿透鼠标事件）。
- **续章**：滚到章底自动追加下一章文本，不重置视图（`_append_chapter`）。
- **老板键**：Esc / Ctrl+Alt+M，普通模式 `withdraw()`，阅读模式 `alpha 0`。
