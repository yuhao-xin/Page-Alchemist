# 常见问题（FAQ）

## 安装与运行

**Q：一定要装 `requests` 吗？**
只有走网络的两个阶段需要：`extract`（api 引擎）和 `publish`。
`demo`、`transform`、`export-md`、`doctor`、`--help` 纯标准库就能跑。
安装：`pip install requests`（或 `pip install -e .` 装完整包）。

**Q：Windows 能用吗？**
能。全部代码跨平台，CLI 无 shell 依赖。用 PowerShell 跑：
`python -m notion_alchemist.cli demo -o output`。

**Q：Python 版本要求？**
>= 3.9。开发测试在 3.13 上通过。

## 凭证与权限

**Q：提取需要什么权限？**
两种路子：① 页面「分享」给你的集成（`···` → Connections），这是推荐路径；
② 只有查看权限的页面（付费库访客链接）走实验性导出引擎，需要
`NOTION_TOKEN_V2`。详见 [notion-token-setup.md](notion-token-setup.md)。

**Q：为什么 API 返回 404，页面明明存在？**
99% 是没把页面共享给集成。Notion 故意对未授权集成返回 404 而不是 403
（不暴露页面是否存在）。打开页面 → `···` → Connections → 选你的集成。
子页面会继承，所以共享根页面即可。

**Q：`my-integrations` 页面打不开？**
只有 Workspace Owner 能建集成。让 Owner 代建，或提升你的账号权限。

**Q：token 会过期吗？**
集成 token 不过期（直到你手动 Refresh 作废）。`token_v2` cookie 会在
退出登录/改密后失效。

**Q：免费版 Notion 能用吗？**
能。API 能力与付费计划无关，页面块数上限是源库自己的限制，与本工具无关。

## 提取

**Q：能提取多大？**
受 Notion API 速率限制（~3 req/s），经验值：100 页含子块的库约
10–20 分钟。工具自动限流+重试，挂着就行。

**Q：图片为什么是死链？**
Notion 文件 URL 带签名、约 1 小时过期。默认提取时就会把图片下载到
`output/assets/`（按 sha1 命名去重）。别加 `--no-assets`——除非你
确定不需要图片。

**Q：数据库会丢吗？**
不会。数据库的 schema + 行数据进 IR（`PageNode.database`），
export-md 时导成 CSV，publish 时在你的空间重建真数据库并插行。

**Q：嵌套多深的页面能提取？**
理论无上限，实际有 12 层安全阀（防病态树）。正常库远到不了。

**Q：导出引擎（export）和 API 引擎输出有区别吗？**
IR 结构完全一致，下游无感。差异只在保真度：导出引擎拿的是 Notion
自己的 Markdown 导出，个别复杂块（如列布局 column_list）会扁平化。

## 发布

**Q：publish 中断了怎么办？**
直接**重跑同一条命令**。`.na_state.json` 记录了每个已建页面的 ID、
已追加块数、数据库已插行数，会精确续传。切勿从头再来——那会创建
重复页面。

**Q：503 错误是什么意思？**
带 `retry_guidance: do_not_retry` 的 503 表示**写入其实已成功**，
Notion 只是响应超时。工具不会盲目重放（那会造成重复内容），而是
记入状态等续传对账。

**Q：发布会在我的空间留下「来源痕迹」吗？**
默认不会：来源信息只在本地 `transform-report.json` 和每页顶部的溯源
callout（可用 `--no-archive-card` 关掉）。页面创建者是你的集成，
Notion 不会显示「复制自 X」。

**Q：发布目标可以是一整个数据库吗？**
`--parent` 传普通页面即可。数据库会在页面下作为子数据库重建。

**Q：速率能调快吗？**
`NA_MAX_RPS` 默认 2.5（安全值）。调到 3 是 Notion 的硬顶附近，
429 会变多；不建议更高。

## 内容与版权

**Q：这工具是「破解」付费内容吗？**
不是。它不绕过任何权限——提取的是**你的账号本来就能看到**的内容，
等价于手动复制粘贴，只是自动化。请只提取你被授权访问的内容，
并遵守源材料的授权协议与 Notion 服务条款。

**Q：会上传我的数据到第三方吗？**
不会。无遥测、无服务端，凭证和内容都只在本机。源码可见，欢迎审计。

**Q：支持飞书/钉钉文档吗？**
不支持，且**故意**不支持——飞书提取是独立项目（用户明确要求分开）。

## 输出与集成

**Q：Markdown 包怎么用？**
`export-md` 产出的 bundle 里每页一个 `.md`，数据库是 `.csv`，图片在
`assets/`。Notion 支持导入 Markdown（设置 → Import），或用
`na publish` 直接写回。

**Q：`structure.json` 是什么格式？**
规范 IR（Intermediate Representation），`models.py` 里四个 dataclass 的
JSON 序列化。字段含义见 [architecture.md](architecture.md#irintermediate-representation)。
可以拿它做 diff、喂给别的工具、或进 git 做版本管理。

**Q：能定时自动同步吗？**
可以。宿主 cron / GitHub Actions / docker compose 定时跑
`na run <url> --parent <id>`，中断自动续传，幂等。
（增量 diff 是 v0.3 roadmap，目前是全量重建。）

## 报错排查

**Q：`error: exit code 2`？**
配置类问题（缺 token、缺 parent、路径不可写）。`na doctor` 会逐项
列出原因和修法。

**Q：`error: exit code 1`？**
运行时报错。加 `-v` 重跑看完整 traceback；还不行就把
`transform-report.json` / `publish-report.json` 里的 errors 数组贴到
issue 里。

**Q：transform 把我要的内容删了？**
先看 `transform-report.json` 的 `dropped` 统计，再用对应的
`--keep-*` 开关恢复。所有删除规则都有开关，没有静默丢弃。
