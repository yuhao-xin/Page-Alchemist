# 架构（Architecture）

## 一句话

**Notion Alchemist = 三阶段流水线 + 磁盘上的规范中间表示（IR）。**
Extract（提取）→ Transform（改造）→ Publish（发布），阶段之间只传
`structure.json` / `transformed.json` 两种纯 JSON 文件。

```
 Notion URL ──► ┌──────────┐   structure.json   ┌───────────┐  transformed.json
                │ Extract  │ ─────────────────► │ Transform │ ───────────────┐
                │ api/export│                    │ cleanse…  │               │
                └──────────┘                    └───────────┘               │
                     │ assets/                        │                     ▼
                     │                          ┌─────┴──────┐      ┌───────────┐
                     │                          │            │      │  Publish  │──► 你的 Notion
                     │                          ▼            ▼      │ (chunked │
                     │                    publish-report  export-md │ resumable│
                     │                                       │      └───────────┘
                     └──► output/assets/ ◄───────────────────┘            │
                                                                    Markdown bundle
```

## 为什么阶段之间用文件而不是内存对象

1. **可中断、可重跑**：提取 500 个页面要几十分钟，任何一步挂了，从磁盘
   上的 JSON 继续，不用重新提取（Notion 文件 URL 一小时过期，但 assets
   已在提取时落盘）。
2. **可审计**：`structure.json` 就是「这个库到底有什么」的完整快照，
   diff 两个版本能看到源库的变化。
3. **可脚本化**：transform 不改，单独重跑 publish；或者拿 `transformed.json`
   喂给你自己的渲染器。

## IR（Intermediate Representation）

定义在 `src/notion_alchemist/models.py`，四个 dataclass：

| 类型 | 关键字段 | 说明 |
|---|---|---|
| `Document` | `source_url, engine, extracted_at, pages[], stats` | 归档根 |
| `PageNode` | `source_id, title, icon, cover, blocks[], children[], database` | 页面；`children` 是子页面，`database` 存在时该页是数据库视图 |
| `Block` | `type, text[], children[], cells[], asset, raw, checked, language, url` | 块；`text`/`cells` 是 `RichText[]`；`raw` 保留原始 API 载荷 |
| `RichText` | `text, kind, bold, italic, …, color, link` | 最小文字单元 |

设计取舍：

- **保留 `raw`**：解析失败或未来新增块类型时，信息不丢，升级不毁数据。
- **表格用 `cells`**：`table_row` 的内容在单元格里而不是 `text` 里，
  漏了这层就会静默丢数据（踩过，见 `tests`）。
- **`asset.local_path`**：Notion 的文件 URL 带签名、约一小时过期，
  所以提取时就下载，IR 里只记本地路径。

## Extract：两个引擎

### 引擎 A — 官方 API（默认，稳定）

`notion_api.py`。`GET /v1/blocks/{id}/children` 递归拉取，要点：

- **版本钉死 `Notion-Version: 2022-06-28`**：兼容面最宽，本工具用到的
  pages / blocks / databases 都在该版本齐备。（2025-09-03 起 Notion 把
  database 改称 data source，字段有变化，所以不追新。）
- **限流**：令牌桶 ~3 req/s，429 时尊重 `Retry-After`。
- **资产随提取下载**到 `output/assets/`，按 sha1 命名去重。
- **深度上限 12 层**：防病态树把递归打爆。

### 引擎 B — 导出兜底（experimental）

`notion_unofficial.py`。对**只有查看权限**的页面（付费模板库访客链接等），
官方 API 拿不到数据——因为没法把页面「分享」给集成。

做法是调用网页端内部任务接口：`POST /api/v3/enqueueTask`
（`eventName: "exportBlock"`，`exportType: "markdown"`）→ 轮询
`getTasks` → 下载签名 ZIP → 解析。等价于在网页上手点
Export → Markdown & CSV，只是自动化了。然后 `parse_export_zip` 把
Markdown/CSV/图片树还原成与引擎 A **完全相同**的 IR——下游无感。

- 需要 `NOTION_TOKEN_V2`（已登录会话的 cookie），见
  [notion-token-setup.md](notion-token-setup.md)。
- 依赖网页端内部接口，Notion 随时可能改 → 标 experimental，不保证长期可用。
- 也支持 `--zip` 直接解析你手动下载的导出包，完全不联网。

## Transform：把内容变成「你的」

`transform.py`，默认全部开启，每个都有开关：

| 规则 | 默认 | 开关 | 说明 |
|---|---|---|---|
| 去噪 | ✅ 丢 `table_of_contents` / `breadcrumb` / `template` / `ai_block` / `unsupported` | `--keep-noise` | 别人库的导航痕迹 |
| 去色 | ✅ | `--keep-colors` | 文字/背景高亮色全部还原为 default |
| 图标重调 | ✅ sha1 确定性换emoji | `--icon-mode keep\|retune\|none` | 同一标题永远得到同一图标，可复现 |
| 标题规范化 | ✅ | `--keep-titles` | 剥掉 emoji/品牌前缀/括号装饰 |
| H1 降级 | ✅ | `--keep-h1` | 页标题已是 H1，正文里的 H1 降为 H2 |
| 去重 | ✅ 相邻完全相同的块 | `--keep-duplicates` | 模板里复制的占位段落 |
| 溯源卡片 | ✅ 每页顶部插入 callout | `--no-archive-card` | 记录来源 URL、引擎、提取时间、章节大纲 |

`synced_block`（同步块）会被**拆开**取其内容——同步块是跨页联动机制，
搬进自己空间后应该断链。

## Publish：写回你自己的 Notion

`publish.py`。这是全项目最脆弱的环节，核心决策：

### 1. 扁平追加，永不嵌套

Notion 的 `children.append` **每次请求最多嵌 2 层**、一次最多 100 个
块、总体 1000 块上限、500 KB body 上限。如果按「页面一次性带整棵子树」
的直觉写，稍深的树就会撞墙，而且错误信息很难定位到具体哪个块。

本工具的做法：**先只追加顶层块，用返回的块 ID 再逐层追加子内容**
（`_append_units` → `_append_kids` 递归）。2 层限制被完全绕开，
每个 payload 都是扁的，出错时精确知道是哪一块。

### 2. 分块 + 失败隔离

每批 ≤100 个 payload 且 ≤400 KB（留 20% 余量）。一批失败时**二分拆分**
定位，只丢弃真正坏的那个块，其余继续——一个畸形块不会炸掉整页。

### 3. 断点续传

`.na_state.json`（原子写入）记录每个页面创建后的 ID、已追加的
payload 数、数据库 schema 与已插入行数。中断后**重跑同一条命令**即续传：

- 页面已存在 → 复用，不重复创建
- 已追加 N 个 payload → 与线上实际子块数对账后接着追加
- 数据库已插入 M 行 → 从第 M+1 行继续

> 对账细节：`units_appended` 数的是**顶层 payload**；若页面里物化了
> 数据库，线上子块数 = 已追加 + 1（数据库本身也是一个块）。

### 4. 503 语义

Notion 对「已落地但响应超时」的写入会返回 503 且带
`retry_guidance: do_not_retry`。盲目重试会造成**重复内容**。
工具的做法：把这类响应上报给调用方并落状态，由续传机制去对账，
绝不自动重放。

### 5. 图标策略

Transform 决定 `node.icon`，Publish 只负责应用——策略与执行分离，
改图标规则不用碰写入代码。

## export-md：不进 Notion 的出口

`export_md.py` 把 IR 渲染成**可直接导入 Notion 的 Markdown 包**：
每页一个 `.md`（标题/列表/待办/引用/callout/代码/表格/图片全覆盖）、
数据库导 CSV、图片复制到 `assets/`、`INDEX.md` 汇总。
适合「只想要干净内容」或想先用 Git 管理内容的场景。

## demo：无凭证全链路

`demo.py` 内置一个「🚀 【付费】Second Brain OS ★」假模板库
（嵌套页面、数据库、同步块、噪音块、彩色文字、重复块、图片），
跑完全部三阶段并产出全套工件。`na demo` 一条命令即可看到每个阶段
的输出形状，**不需要任何 token**。

## 模块地图

```
src/notion_alchemist/
├── cli.py               # argparse 七个子命令：extract/transform/publish/
│                        #   export-md/run/demo/doctor
├── config.py            # Settings：env/.env → 校验 problems()
├── models.py            # IR dataclass + JSON 序列化
├── util.py              # 日志/限流/退避/slug/sha1/dotenv/ID 提取
├── notion_api.py        # 引擎 A：官方 API 提取
├── notion_unofficial.py # 引擎 B：exportBlock 兜底（experimental）
├── transform.py         # 清洗/图标/重排/标题/溯源卡
├── publish.py           # 写回：扁平追加、分块、续传、失败隔离
├── export_md.py         # Markdown 包渲染
└── demo.py              # 离线演示数据与全流程
```

## 依赖立场

运行时**只依赖 `requests`**（且仅网络阶段需要）；transform / export-md /
demo 纯标准库。开发期才需要 pytest/ruff。`--help`、`doctor`、`demo`
在没装 requests 的环境也能跑——CI 里可以先验证再装依赖。

## 明确不做的事

- **不做飞书/钉钉提取**：那是独立项目，用户明确要求分开。
- **不做 in-place 克隆**（v0.2 roadmap，需 saveTransactions，踩 Notion
  风控的概率高）。
- **不追新 API 版本**：稳定 > 新特性，除非旧版本被官方下线。
