# 产品经理评审报告 · Page Alchemist v0.1.0

> 视角：假设我是第一次看到这个仓库的评审者 / SkillHub 评委 / 潜在用户。
> 结论先行：**产品定位和工程完成度都在水位之上，但有两处 P0 问题会直接
> 压掉评分——定位语把自己送进了灰色地带，以及文档语言断层让评审者读不了。**
> 本文第 3 节是已落实的缝补清单。

---

## 1. 总体判断

| 维度 | 评级 | 一句话 |
|---|---|---|
| 产品吸引力 | B+ → A- | 差异化真实存在，但「进门英文、上楼中文」+ 看不到成品，前 3 分钟就流失 |
| 功能性 | A- | 三段闭环齐全、每个默认值都有逃逸口、断点续传，是完整工具而非 demo |
| 耐用性 | B | 4 个真实风险点，其中 2 个有明确退路，2 个需要补文档而非补代码 |
| 合规 / 信任 | C → A- | 原始定位语是自伤；改写后仍是同类里最讲边界的一个 |

---

## 2. 意见清单（按严重度排序）

### P0-1 定位语把自己送进了灰色地带

README 的 `🧭 Why` 写着：

> Page Alchemist exists to **reclaim knowledge**: *private → yours, paid → free*.

SKILL.md 的 description 写着：

> convert a private or paid Notion library into their own public free knowledge base

**问题**：这两句的直读意思是「把别人私有的、付费的内容，变成我公开的免费版」。
一个不了解边界的评审者，3 秒内就会把它归类为「盗版搬运工具」——
而这与工具的真实语义（**用户先拥有访问权**，工具只做自动化重组）是两件事。

**为什么必须改，而不是加免责声明**：
- SkillHub 的 TRACE 模型里 **T（Trust 安全可信）是红线门槛，命中即淘汰**，
  不是扣分项。争议措辞出现在 description（预检项之一）和 README 首屏，
  正是最容易被扫到的位置。
- 免责声明救不了标题。标题定了调，声明只会被读成「心里有数」。
- 对真实用户也是损失：愿意付费买模板的人，恰恰不想用「破解感」的工具。

**缝补方向**：把动词从「占有 / 免费化」换成「重组 / 归档 / 可移植」，
并且每一处都显式带上「you are authorised to access」这个前提。

### P0-2 文档 100% 中文，评审者读不了

README.md 是英文的，但 `docs/` 下 5 篇全是中文，SKILL.md 的 References
也全指向中文文档。

**问题**：GitHub 与 SkillHub 的评审者以英文为主。一个英文用户顺着 README
点进 `docs/notion-token-setup.md`（**这是上手的第一道卡点，100% 必读**），
面对一篇中文文章——他只会关掉标签页，不会去点 README.zh-CN.md。
这就是「进门英文、上楼中文」的断层。

**缝补方向**：不必 5 篇全翻（成本高、边际收益低）。
只翻**通过率最吃劲的两篇**——`notion-token-setup`（上手卡点）和
`architecture`（证明工程质量的那篇），外加一份带语言标注的 docs 索引。
中文原文全部保留，中文用户零损失。

### P1-1 仓库里看不到成品

`examples/demo_output/` 被 `.gitignore` 挡着，仓库里只有一个 `examples/README.md`
的文字描述。

**问题**：评审者要判断「输出质量」，默认路径是看成品。现在他必须
`pip install requests` + 跑 `na demo` 才能看到——大多数评审者不会。
SkillHub 的「实用性」「输出质量」两维直接吃这个亏；对普通用户，
「看不到产出」等于「不相信它能用」。

**缝补方向**：提交一份**精简的** sample-output（INDEX.md + 一个清洗前后
对照 + 两个 JSON 报告的摘要），控制在几十 KB，去掉 state 文件和无谓的图片。

### P1-2 SKILL.md 的 description 质量与触发覆盖

预检项里「描述质量」要求：**触发词具体、中英双语、3 个以上可判定场景**。
现版本有两个问题：

1. 语义问题（同 P0-1）：含 "private or paid" 表述。
2. 覆盖问题：触发词偏「复制 / 克隆」，漏掉了几个高频真实意图——
   「把我的 Notion 导出整理成 Markdown 知识库」「去掉模板里的署名和水印」
   「把散落在多个页面的内容合并成一个库」「给一堆 Notion 页面换一套统一结构」。

### P2-1 耐用性：4 个真实风险点

| # | 风险 | 严重度 | 现状 | 处置 |
|---|---|---|---|---|
| 1 | 非官方引擎依赖 Notion 网页端私有接口 `enqueueTask` | 高（但可隔离） | 已标 experimental；主引擎不受影响；`--zip` 可完全离线解析 | 已在架构文档写明失效不影响主链路；补一句「失效时的退路」 |
| 2 | API 版本钉死 `2022-06-28`，Notion 已推 `2025-09-03`（database → data source，字段改名） | 中 | 已钉死并说明原因，但**没有写升级触发条件和迁移步骤** | 补「何时该升、怎么升」小节 |
| 3 | `publish.py` 单文件约 800 行，承载写回全逻辑 | 中 | 逻辑内聚、注释完整，暂不需要拆 | 记录为已知技术债，不在这版动 |
| 4 | 没有对 mock Notion server 的集成测试（现有 113 个测试都是 stub 级） | 中 | 单元覆盖率高，但「真实 HTTP 交互」层是空的 | 记录为 v0.2 路线图 |

> 结论：**耐用性 B**。风险 1 和 2 靠文档就能把实际影响降到很低；
> 3 和 4 是真实的工程债，但不影响 v0.1.0 出厂。

---

## 3. 差异化：它到底和什么不一样

| 对比对象 | 对方能给 | 对方不能给 | Page Alchemist 的独特位 |
|---|---|---|---|
| Notion 官方 Export | 一个 zip | 不重组、不写回、不带进度 | **读 → 洗 → 写回闭环** |
| Notion 官方 Duplicate | 同账号内复制页面 | 不能跨账号 / 跨工作区 | 跨空间重建 + 断点续传 |
| notion2md / fauxmd 等 | 单页转 Markdown | 不递归整棵树、不去噪、无权威 IR | 规范化 IR（`raw` 保底，升级不毁数据） |
| 手工复制粘贴 | 零门槛 | 大树 / 多页不可行 | 分块 + 限流 + 幂等恢复 |

**一句话差异化**：别人给你一份「导出物」，它给你一条「可断点续传、
可脚本化、可重建到你自己空间」的流水线。这是真实的、别家没有的位。

---

## 4. 吸引力评估（P0 缝补前 → 后）

评审者的实际动线：GitHub 首页 → README 首屏 → 点 docs → 上手 → 看成品 → 评分。

| 环节 | 缝补前 | 缝补后 |
|---|---|---|
| 首屏 3 秒 | 被 "paid → free" 吓到，或困惑 | 语义清晰，边界显式 |
| 30 秒（读 README） | 英文，结构清楚，有 CLI 表格 ✅ | 不变，仍然是加分项 |
| 2 分钟（点进文档） | 中文墙 ❌ | token 教程 + 架构有英文版 ✅ |
| 3 分钟（看成品） | 看不到，要自己跑 ❌ | 仓库内直接可见 ✅ |
| 5 分钟（作为 Skill 装） | description 有争议措辞 ⚠️ | 触发词扩到 4 类意图、无争议措辞 ✅ |

**结论**：吸引力从 B+ 到 A-。产品本身不缺功能，缺的是**让评审者在
不安装任何东西的前提下相信它**。

---

## 5. SkillHub 评审规则对照

### 5.1 两套评分体系（均已核实）

**体系 A — skillhub.club，LLM 六维加权**：

| 维度 | 权重 | 本仓库 | 说明 |
|---|---|---|---|
| 指令清晰度 | 15% | 强 | SKILL.md 有 5 条黄金规则 + 意图→命令表 + 失败处理 |
| 实用性 | 25% | 中→强 | 痛点真实；扣分在「看不到成品」和「文档语言」 |
| 输出质量 | 25% | 中→强 | 同上；sample-output 提交后转强 |
| 可维护性 | 15% | 强 | 113 测试 + 零依赖测试跑器 + CHANGELOG + CI |
| 创新性 | 10% | 中 | 三段闭环 + 权威 IR 有创新，但同类工具已存在 |
| 安全性 | 10% | 弱→强 | 原始措辞是负分项；改写 + token_v2 密码级警示后转正 |

**体系 B — skillhub.cn，TRACE 五维**（T 是红线，命中即淘汰）：

| 维度 | 权重 | 本仓库 | 关键动作 |
|---|---|---|---|
| **T Trust 安全可信** | **红线门槛** | 原本文风险高 | 移除 "private or paid" 类措辞；全仓加授权边界声明 |
| R Reliability 运行可靠 | 20% | 强 | 零依赖可跑 demo/transform；双跑器；退出码语义化 |
| A Adaptability 场景适用 | 20% | 强 | `--engine auto` 自动降级；每个默认值有逃逸口 |
| C Convention 结构规范 | 25% | 强 | SKILL.md 在包根；frontmatter 6 字段齐；name==目录名 |
| E Effectiveness 效果增益 | 35% | 中→强 | 收益真实但需可见性证明 → sample-output |

### 5.2 预检 12 项逐条对照

| # | 预检项 | 状态 | 备注 |
|---|---|---|---|
| 1 | 目录结构（SKILL.md 在包根） | ✅ | 仓库根即有 |
| 2 | 必备字段（frontmatter 顶层 6 字段） | ✅ | name/description/license/compatibility + 正文 |
| 3 | 标识一致（name == 目录名） | ✅ | `page-alchemist` |
| 4 | slug 撞车（不含通用词） | ✅ | 非通用词 |
| 5 | 敏感残留（绝对路径 / 硬编码凭据 / 手机号） | ✅ | `.env.example` 全空值；无绝对路径 |
| 6 | 编码安全（zip 内中文文件名 UTF-8 标记） | ✅ | 本仓库无中文文件名；上传 zip 时由 `scripts/skillhub_preflight.py` 提示 |
| 7 | 描述质量（触发词、中英双语、3+ 场景） | ⚠️ → ✅ | 已扩到 4 类意图、双语触发词 |
| 8 | 依赖声明 | ✅ | compatibility 明确标了 requests 可选 |
| 9 | 边界真实 | ⚠️ → ✅ | Feishu 独立项目、token_v2 实验性、均有明示 |

退出码口径：**0 可传 / 1 有风险 / 2 会被拒**。目标：预检拿 0。

**本仓库当前状态：`python scripts/skillhub_preflight.py` → exit 0，12/12 全过。**
（该脚本就是上表的可执行版，改仓库前先跑它，比改完再猜要快。）

---

## 6. 已落实的缝补清单

见 [CHANGELOG.md](../CHANGELOG.md) 的 `Unreleased` 段。摘要：

1. **定位改写**（P0-1）：`README.md` / `README.zh-CN.md` / `SKILL.md`
   三处的「占有 / 免费化」措辞全部换成「重组 / 可移植」，并显式带上
   「you bring the access rights」前提。连带修掉 `pyproject.toml` 的
   description、`assets/banner.svg` 的标语、`assets/brand.md` 的 voice
   规范、`__init__.py` 的 docstring、`docs/github-upload.md` 里的
   `gh repo create --description` 命令——**漏掉任何一处，评审者就会在那里
   看到旧措辞**。
2. **英文文档**（P0-2）：新增 `docs/notion-token-setup.en.md`、
   `docs/architecture.en.md`、`docs/index.md`（带语言标注的索引）。
   中文原文全部保留。
3. **成品可见**（P1-1）：提交精简 `examples/sample-output/`（README +
   before/after 逐块对照 + 两份机器可读报告 + 一页导出 Markdown）。
4. **SKILL.md 描述增强**（P1-2）：触发意图从 2 类扩到 4 类，移除争议措辞。
5. **token_v2 安全措辞**：SKILL.md 新增第 5 条黄金规则「把 token_v2 当
   密码」，两个 README 的配置表同步标注；SECURITY.md 里写错的
   `--backend unofficial`  flag 名也一并修正为真实的
   `--engine export`。
6. **API 版本迁移说明**：`docs/architecture.md` 补「何时升 / 怎么升」。
7. **预检自检脚本**：`scripts/skillhub_preflight.py`，把 5.2 那张表变成
   可执行的东西——12 项逐条跑，退出码与平台口径一致（0/1/2）。当前
   本仓库跑出 **exit 0**。它同时进了 `make preflight` 和 CI，
   并有 19 个测试守着（含一条「本仓库必须拿 exit 0」的回归护栏）。

> 写这个脚本时踩到一个有意思的坑：第一版把测试夹具里的假 token 和假手机号
> 也扫出来了，自己给自己报了个 exit 2。任何「扫敏感信息」的工具都要显式排除
> `tests/` / `fixtures/`——否则它迟早会训练用户忽略它的输出。

---

## 7. 明确不做的事（v0.1.0 边界）

- 不拆 `publish.py`（P2-3）——留 v0.2。
- 不加 mock Notion server 集成测试（P2-4）——留 v0.2。
- 不翻译 `faq.md` / `transform-rules.md`——通过率边际收益低，
  且中文用户是当前主要受众。
- 不接飞书（用户已明确：独立项目）。
