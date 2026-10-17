# Transform 规则详解（Transform Rules）

Transform 是「把别人的库变成你的库」的那一步。全部规则**确定性执行、
离线、无 LLM 调用**——同一个输入永远得到同一个输出，可复现、可测试。

每个规则都有对应的 CLI 开关，默认值以「让内容最大化地变成你的」为准。

---

## 规则总览

| # | 规则 | 默认 | 开关 | 计数字段 |
|---|---|---|---|---|
| 1 | 去结构噪点 | 开 | `--keep-noise` | `dropped` |
| 2 | 拆同步块 | 开 | `--keep-noise` | `dropped[synced_block]` |
| 3 | 去颜色 | 开 | `--keep-colors` | `colors_stripped` |
| 4 | 图标重调 | 开（retune） | `--icon-mode keep\|retune\|none` | `icons_retuned` |
| 5 | 标题规范化 | 开 | `--keep-titles` | `titles_normalized` |
| 6 | H1 降级 | 开 | `--keep-h1` | `h1_demoted` |
| 7 | 相邻去重 | 开 | `--keep-duplicates` | `duplicates_removed` |
| 8 | 溯源卡片 | 开 | `--no-archive-card` | `cards_added` |

报告在 `transform-report.json`，每条规则命中了多少一目了然。

---

## 1. 去结构噪点

这些块是**源库的导航/机制痕迹**，搬进个人库后只会显得像复制品：

| 块类型 | 为什么丢 |
|---|---|
| `table_of_contents` | Notion 目录块，重排后引用全部失效 |
| `breadcrumb` | 显示源页面的层级路径，暴露来源结构 |
| `template` | 「Duplicate this template」按钮 |
| `ai_block` | 源库的 AI 功能残留 |
| `unsupported` | Notion 自己都不渲染的块 |

## 2. 拆同步块（synced_block）

同步块是 Notion 的**跨页实时联动**机制：改一处，所有引用处一起变。
搬进自己空间后这个链接必须断掉，否则你改自己的内容会改到源库
（或反过来）。

处理方式：**丢掉 synced_block 外壳，保留并提升其子内容**。

```
源 IR                              转换后
├─ synced_block                    ├─ paragraph "这是原本被同步的内容"
│  └─ paragraph "这是原本被同步的内容"   （外壳消失，内容原地顶替）
```

## 3. 去颜色

文字颜色、背景高亮色是模板最显眼的「胎记」。规则：所有 `RichText.color`
非 `default` 的一律还原为 `default`。数据库属性、图标不受影响。

```
源：  RichText(text="限时优惠", color="red", background="yellow_background")
后：  RichText(text="限时优惠", color="default")
```

## 4. 图标重调

源库图标（🚀💎⭐…）是作者的个人品牌。三种模式：

| 模式 | 行为 |
|---|---|
| `retune`（默认） | 用页面 slug 的 sha1 从 30 个「知识管理向」emoji 里确定性挑选 |
| `keep` | 保留源图标 |
| `none` | 清空图标 |

**确定性**是关键：`pick_emoji("weekly-review")` 永远返回同一个 emoji。
重复提取、重跑 transform、换机器，结果一致——不会这次 🧭 下次 🌱。

```python
pick_emoji("second-brain-os")  # -> 固定值，sha1(slug) % 30
```

## 5. 标题规范化

按顺序剥离，直到干净为止：

1. **首尾符号装饰**：emoji、`★`、`☆`、`—`、引号类符号
   （Unicode `U+2000–U+2BFF`、`U+1F000–U+1FAFF` 区间；**故意不含 CJK**，
   中文标题不会被误伤）
2. **商业前缀**：`【付费】` `【VIP】` `[VIP]` `VIP` `PRO` `Premium`
   `付费` `会员` `模板` `Template`（大小写不敏感）
3. **短括号标签**：开头 ≤20 字的 `【…】`/`[…]`/`(…)`
4. **压缩连续空白**为单个空格

```
源标题：🚀 【付费】Second Brain OS ★
规范化：Second Brain OS

源标题：[Template] Ultimate Dashboard (2026 Edition)
规范化：Ultimate Dashboard (2026 Edition)

源标题：我的读书笔记模板           ← 中文无符号前缀，原样保留
```

兜底：若剥离后标题为空（比如标题整个就是个 `【模板】`），保留原题，
绝不产出空标题。

## 6. H1 降级

Notion 页面里，**页标题本身就是视觉上的 H1**。源模板常在正文里再放
一个 `heading_1`，导入后会出现「两个大标题」。

规则：正文中的 `heading_1` → `heading_2`（页面的顶层块；子块里的 H1
同理降级）。页标题本身不动。

## 7. 相邻去重

只删**相邻且完全相同**的兄弟块（同类型、同勾选状态、同文本）。
模板常见的「Copy this page」占位段、复制粘贴产生的重复条目会被清掉。

```
源：  paragraph "Click duplicate to start"  ×3（连续）
后：  paragraph "Click duplicate to start"  ×1
```

保守设计：不相邻的重复、有子块的重复都不动——内容优先于整洁。

## 8. 溯源卡片

每页顶部插入一个生成的 callout，内容：

```
📌 来源：https://www.notion.so/...
   提取时间：2026-10-18T… · 引擎：api
   章节：Weekly review / Bonus: Advanced Prompts
   本页由 notion-alchemist 归档整理（源 12 个内容块）
```

这不是「抄袭痕迹」而是**你自己的归档元数据**：三个月后看到这页，
你知道它从哪来、什么时候抓的、原始规模多大。不想要就
`--no-archive-card`。

---

## 执行顺序

规则按 5→1/2/3/6/7→4→8 的顺序作用于每个页面（深度优先遍历所有页面）：

```
页面标题规范化
      ↓
块级清洗（去噪/拆同步/去色/H1降级/去重/删空块）
      ↓
图标重调
      ↓
插入溯源卡片（位置 0）
```

> 细节：空块删除对 `table_row` 豁免——表格行的内容在 `cells` 里而不在
> `text` 里，按文本判空会误杀整张表。

## 想完全跳过 Transform？

`publish` 可以直接吃 `structure.json`（未转换版），或 `run` 时把所有
`--keep-*` 开关打开。但推荐至少跑一次默认 transform——它才是这个工具
区别于「Notion 自带导出」的价值所在。
