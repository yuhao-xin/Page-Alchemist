# 飞书发布教程（Feishu Publish）

> 目标读者：想把 notion-alchemist 清洗后的内容**拷贝到飞书云文档**的人。
> 全程约 10 分钟，不需要写代码。只需要一个飞书**自建应用**的
> App ID / App Secret——不需要管理员，不需要企业认证（个人版飞书即可）。

---

## 目录

1. [它能做什么](#它能做什么)
2. [第 1 步：创建飞书自建应用](#第-1-步创建飞书自建应用)
3. [第 2 步：开通权限](#第-2-步开通权限)
4. [第 3 步：写入 .env](#第-3-步写入-env)
5. [第 4 步：dry-run 验证](#第-4-步dry-run-验证)
6. [第 5 步：正式发布](#第-5-步正式发布)
7. [行为说明（必读）](#行为说明必读)
8. [常见错误速查](#常见错误速查)
9. [Lark（国际版）用户](#lark国际版用户)
10. [安全须知](#安全须知)

---

## 它能做什么

`na publish-feishu` 把 `transformed.json`（IR）写成**一篇篇飞书云文档
（docx）**：

- 每个 Notion 页面 → 一篇飞书文档（标题即页面标题）
- 子页面 → 同一文件夹下的**同级文档**（飞书没有「文档内嵌子文档」的
  API，层级用每篇文档顶部的来源callout保留）
- 标题 / 正文 / 列表 / 待办 / 代码块 / 引用 / 高亮块 / 分割线 / 书签 /
  表格 → 一一对应；**本地图片自动上传**为飞书素材
- 内联数据库（inline database）→ 表格块（超过 200 行截断并在报告里提示）
- 进度记录在 `.na_feishu_state.json`：**重复运行不会产生重复文档**

```bash
notion-alchemist publish-feishu output/transformed.json
```

---

## 第 1 步：创建飞书自建应用

1. 浏览器登录飞书，打开 <https://open.feishu.cn/app>
2. 点 **创建企业自建应用**
3. 填写名称（如 `Notion Alchemist`）与描述，创建
4. 进入应用详情页，左侧 **凭证与基础信息** → 复制
   **App ID**（`cli_` 开头）和 **App Secret**

> ⚠️ 飞书要求自建应用先**发布应用版本**并通过，`tenant_access_token`
> 才可用。如果第 4 步报 `99991664` / 权限类错误，先去
> **版本管理与发布** 页创建版本并申请发布（企业内自用通常秒过）。

---

## 第 2 步：开通权限

左侧 **权限管理**，搜索并开通以下权限（最小集）：

| 权限 | 用途 |
|---|---|
| `docx:document` | 创建云文档、写入文档块 |
| `drive:drive` | 上传图片素材到文档 |
| `drive:file:upload` | 媒体上传（`medias/upload_all`） |

开通后需要**再次发布版本**，权限才生效。

---

## 第 3 步：写入 .env

在项目根目录的 `.env`（从 `.env.example` 复制）中：

```bash
NA_FEISHU_APP_ID=cli_xxxxxxxxxxxx
NA_FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxx
# 可选：指定文档创建到哪个文件夹（云空间文件夹 token）
# NA_FEISHU_FOLDER=fldxxxxxxxxxxxx
```

`NA_FEISHU_FOLDER` 留空时，文档创建在**应用自己的云空间根目录**
（飞书自建应用没有「我的空间」，应用创建的文档归属应用所有者可见）。
要拿到文件夹 token：在飞书云空间网页版打开目标文件夹，URL 最后一段
即 `fld...`。

---

## 第 4 步：dry-run 验证

```bash
notion-alchemist publish-feishu output/transformed.json --dry-run
```

dry-run **不发任何 API 请求**，也不需要凭证，但会打印每篇将创建的
文档、块数统计。看到 `errors : 0` 再往下。

---

## 第 5 步：正式发布

```bash
notion-alchemist publish-feishu output/transformed.json
```

完成后打印每篇文档的链接（`https://www.feishu.cn/docx/<id>`），报告
写入 `output/publish-feishu-report.json`。

断线 / 中断后**直接重跑同一命令**：已写完的文档自动跳过，创建了但没
写完的文档会在原文档上补写，不会重复建文档。

---

## 行为说明（必读）

| 主题 | 行为 |
|---|---|
| 层级 | 拍平为同级文档；每篇文档顶部有来源 callout（源 URL + 页面路径） |
| 图片 | 有本地文件 → 上传素材；只有外链 → 降级为链接段落（飞书不支持外链图片块） |
| 代码块 | 语言映射到飞书 `CodeLanguage` 枚举；未收录语言回落 `PlainText`（只影响高亮） |
| 表格 | 超宽（>20 列或 >400 单元格）降级为等宽文本行 |
| 数据库 | 渲染为表格，最多 200 行，超出部分在报告 `skipped` 里提示 |
| 颜色 | 不保留（transform 默认已剥色，与 Notion 发布一致） |
| 同步块 / 列布局 | 展开为顺序内容（容器本身丢弃） |
| 写入限速 | 复用 `NA_MAX_RPS`（默认 2.5 req/s），429 遵循 `Retry-After` |

---

## 常见错误速查

| 报错 | 原因 | 处理 |
|---|---|---|
| `NA_FEISHU_APP_ID is not set` | 没配凭证 | 回到第 3 步 |
| `code=99991661/99991663/99991664` | token 失效 / 应用未发布 | 脚本会自动刷新一次；持续出现则去发布应用版本 |
| `code=1069902` folder not found | `NA_FEISHU_FOLDER` 写错 | 核对文件夹 token；留空走根目录 |
| `code=1770001` permission denied | 权限没开通或版本没发布 | 回到第 2 步，发布版本 |
| 文档建出来了但内容是空的 | 上次写到一半被中断 | 重跑同一命令，会自动补写 |
| 图片变成链接段落 | 提取时用了 `--no-assets`，没有本地副本 | 重跑 extract（不加 `--no-assets`）再 publish-feishu |

---

## Lark（国际版）用户

把 base 换成 Lark 的开放平台域名即可，其余完全相同：

```bash
NA_FEISHU_BASE=https://open.larksuite.com
```

应用在 <https://open.larksuite.com/app> 创建，权限名一致。

---

## 安全须知

- `NA_FEISHU_APP_SECRET` 等同应用密码：**不要提交进 git**（`.env` 已在
  `.gitignore`），不要贴进 issue / 截图
- 自建应用的权限按上面的最小集开通即可，**不要**图省事开 `docx:document`
  通配或其他高危权限
- 应用创建的文档归属应用本身；团队协作场景建议由管理员审批后再发布版本
