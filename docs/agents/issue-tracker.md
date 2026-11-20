# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues in **`2JumpSinA/moyu-reader`**
(a fork of `gzg66/moyu-reader`; the fork is where our work lives).

## 本机工具现状

- **没有 `gh` CLI**（`gh` 未安装，且 GitHub release 资产域名在本机不可达）。
- 已配置 SSH 身份：`git@github.com:2JumpSinA/moyu-reader.git`（remote 名为 `fork`）。
- 因此：**读**用 `https://api.github.com/repos/2JumpSinA/moyu-reader/...`（匿名可读公开仓库），
  **写**（建 issue / 评论 / 打标签）走浏览器预填链接，由本人点确认。

## Conventions

- **Create an issue（无 gh 时的推荐路径）**：生成预填链接并请用户确认：
  `https://github.com/2JumpSinA/moyu-reader/issues/new?title=<URL编码标题>&body=<URL编码正文>`
  正文里的 `#` `&` 等必须 URL 编码（`%23`、`%26`）。
- **Read an issue**：`curl -s https://api.github.com/repos/2JumpSinA/moyu-reader/issues/<n>`
- **List issues**：`curl -s 'https://api.github.com/repos/2JumpSinA/moyu-reader/issues?state=open'`
- **Comment / label / close**：同样给预填/直链让用户点，或安装 `gh` 后改走 CLI。
- **Push code**：`git push fork main`（SSH）。上游 `origin` 只读，不要向上游推。

File issues only into `2JumpSinA/moyu-reader`. Never file into the upstream `gzg66/moyu-reader`.

## Pull requests as a triage surface

**PRs as a request surface: no.**

## When a skill says "publish to the issue tracker"

Create a GitHub issue in `2JumpSinA/moyu-reader`（按上面的预填链接流程）。

## When a skill says "fetch the relevant ticket"

Read it via the GitHub REST API above.
