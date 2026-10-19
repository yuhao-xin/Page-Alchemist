# Notion 凭证设置教程（Token Setup）

> 目标读者：完全没配过 Notion API 的人。全程约 5 分钟，不需要写代码。
> 两个引擎各需一种凭证：**官方 API 引擎**（推荐，稳定）用 *integration token*；
> **导出兜底引擎**（实验性）用 *token_v2 cookie*。只做 Markdown 导出 /
> demo 的话，一种都不用配。

---

## 目录

1. [引擎 A：官方 API（推荐）](#引擎-a官方-api推荐)
2. [引擎 B：导出兜底（实验性，仅查看权限页面）](#引擎-b导出兜底实验性仅查看权限页面)
3. [写入 .env](#写入-env)
4. [验证](#验证)
5. [常见错误速查](#常见错误速查)
6. [Docker / GitHub Actions 中传凭证](#docker--github-actions-中传凭证)
7. [安全须知](#安全须知)

---

## 引擎 A：官方 API（推荐）

需要**两个**页面权限：① 你要提取的**源页面**；② 你自己空间里用于接收内容的**父页面**。两者都要共享给集成。

### 第 1 步：创建内部集成

1. 浏览器登录 Notion（用**拥有目标 workspace 的账号**），打开
   <https://www.notion.so/my-integrations>
2. 点 **+ New integration**（新建集成）
3. 填写：
   - **Name**：起个能认出来的名字，如 `Page Alchemist`（这个名字会出现在
     页面的「连接」列表里）
   - **Associated workspace**：选择目标 workspace（集成与 workspace 绑定，
     换 workspace 要重新建）
   - **Logo**：可跳过
4. 点 **Submit**

> ⚠️ 只有 **Workspace Owner（ workspace 所有者）**能创建集成。成员
> （Member）和访客（Guest）看不到这个页面——让 Owner 代建，或把账号
> 权限提上去。

### 第 2 步：复制 Integration Secret

提交后进入集成配置页，找到 **Internal Integration Secret**：

- 新集成是一串 `ntn_` 开头的长字符串；2024 年底之前创建的老集成是
  `secret_` 开头——**两种格式 API 都认**，混用没关系。
- 点 **Show** 显示完整 token 并复制。
- 令牌**不会自动过期**；怀疑泄露就回这个页面点 **Refresh** 作废旧令牌。

### 第 3 步：配置 Capabilities（能力范围）

同一配置页的 **Capabilities** 区，本工具需要这三项**全部勾选**：

| 能力 | 用途 |
|---|---|
| ☑ **Read content** | extract 阶段读取源页面树 |
| ☑ **Insert content** | publish 阶段创建页面 / 追加块 |
| ☑ **Update content** | 图标、封面、恢复中断的发布 |

User capabilities 一律不用管。以后改能力**不需要**重新生成 token。

### 第 4 步：把页面共享给集成（最容易漏的一步）

**创建集成 ≠ 授权访问。** 不共享的话，API 会返回 `404 Could not find
object`——注意是 404 不是 403，这是 Notion 故意的（不向未授权集成
暴露页面是否存在）。

1. 在 Notion 里打开**源页面**（要提取的那个）
2. 点右上角 **···** 菜单
3. 找到 **Connections**（中文界面：「连接」/「添加连接」）
4. 搜索并选中你刚创建的集成名字
5. 对**父页面**（你空间里接收内容的那个）重复 1–4

共享是**向下继承**的：共享顶层页面后，它下面所有子页面、子数据库
自动都可访问。所以最省事的做法是只共享源库的根页面 + 你的目标父页面。

### 第 5 步：写进 `.env`

见下方[写入 .env](#写入-env)，只需填 `NOTION_TOKEN` 和 `NA_PARENT_PAGE`。

---

## 引擎 B：导出兜底（实验性，仅查看权限页面）

当你对页面只有**查看权限**（比如别人付费模板库的访客链接）、没法
分享给集成时，官方 API 走不通。本工具提供一个实验性兜底：调用
Notion 网页端的导出任务（`exportBlock`），效果等同于你在网页上点
「Export → Markdown & CSV」，只是自动化了。

它需要 `token_v2`——你**已登录 notion.so 浏览器会话**的 cookie：

1. Chrome/Edge 登录 <https://www.notion.so>
2. 按 `F12` 打开开发者工具 → **Application / 应用** 标签
3. 左侧 **Cookies → `https://www.notion.so`**
4. 找到名为 **`token_v2`** 的条目，复制它的 Value（一长串字符）
5. 写进 `.env` 的 `NOTION_TOKEN_V2=`

注意事项：

- `token_v2` **等同你的登录态**，谁拿到谁就能登录你的账号。它会在
  你退出登录或改密码后失效。只把它放在本机 `.env` 里，**不要**发给
  任何人、不要提交进 git。
- 导出引擎拿到的是 ZIP（Markdown + CSV + 图片），解析成与官方引擎
  完全相同的 IR，后续 transform / publish 流程一模一样。
- 该引擎依赖网页端内部接口，Notion 随时可能改它——所以标了
  **experimental**，不保证长期可用。能用官方 API 就别用它。

---

## 写入 .env

在项目根目录：

```bash
cp .env.example .env
```

然后编辑 `.env`：

```ini
# —— 引擎 A：官方 API（推荐）——
NOTION_TOKEN=ntn_你的集成密钥
NA_PARENT_PAGE=https://www.notion.so/你的父页面链接

# —— 引擎 B：导出兜底（实验性，可选）——
# NOTION_TOKEN_V2=你的token_v2 cookie

# —— 可选项，都有默认值 ——
# NA_ICON_MODE=retune          # keep | retune | none
# NA_MAX_RPS=2.5               # 写入速率上限，别调高
# NA_STATE_DIR=.               # .na_state.json 存放位置
# NA_OUTPUT_DIR=output
# NOTION_FILE_TOKEN=           # 备用文件上传令牌（一般不用填）
```

`NA_PARENT_PAGE` 可以填完整 URL，也可以只填页面 ID（32 位十六进制，
带不带连字符都行）。

---

## 验证

```bash
# 1. 本工具自检：令牌形状、目录可写、依赖是否就位
na doctor

# 2. 原生验证（可选）：直接问 Notion「这个集成能看到哪些数据库」
curl -X POST "https://api.notion.com/v1/search" \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d '{"filter": {"property": "object", "value": "database"}}'
```

返回的 `results` 里**能看到**你的页面/数据库 = 配好了。
`results` 为空 = token 有效但还没共享页面（回第 4 步）。

---

## 常见错误速查

| 现象 | 原因 | 解决 |
|---|---|---|
| `401 Unauthorized` | token 复制错了 / 被 Refresh 作废了 | 重新复制完整 `ntn_...` 串 |
| `404 Could not find object` | 页面没共享给集成（**最高频**） | 页面 `···` → Connections → 选集成 |
| `search` 返回空列表 | 同上，一个都没共享 | 同上 |
| `429 Too Many Requests` | 超过 ~3 req/s | 工具已内置限流重试；若在用别的脚本，调低 `NA_MAX_RPS` |
| `validation_error` | 请求体不符合 schema | 多半是升级了新 API 版本导致字段改名；本工具钉死 `2022-06-28`，别改 |
| `503` + `retry_guidance: do_not_retry` | 写入其实**已成功**，Notion 故意不让你重放 | 工具会记录到状态文件；重跑同一命令会续传，不会重复创建 |
| 看不到 `my-integrations` 页面 | 账号不是 Workspace Owner | 让 Owner 代建集成 |
| 提取成功但图片是死链 | Notion 文件 URL 约 1 小时过期 | 提取时已自动下载到 `output/assets/`；别用 `--no-assets` |

---

## Docker / GitHub Actions 中传凭证

**Docker**（`docker-compose.yml` 已留好注入点）：

```bash
# .env 同目录下执行，compose 自动读取
NOTION_TOKEN=ntn_xxx NA_PARENT_PAGE=https://... \
  docker compose run --rm alchemist run "<源页面URL>"
```

**GitHub Actions**（定时重新发布等场景）：进仓库
**Settings → Secrets and variables → Actions → New repository secret**，
添加 `NOTION_TOKEN`、`NA_PARENT_PAGE`，workflow 里这样引用：

```yaml
- run: page-alchemist run "$SOURCE_URL" --parent "$NA_PARENT_PAGE"
  env:
    NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
    NA_PARENT_PAGE: ${{ secrets.NA_PARENT_PAGE }}
```

---

## 安全须知

- `.env` 已在 `.gitignore` 里；**提交前再确认一遍**没有把它 `git add` 进去。
- 令牌只放在本机；不要在聊天窗、issue、截图里粘贴完整 token。
- 给每个项目建独立集成，不要全账号复用一个——页面的 Connections
  列表就是你最好的审计日志。
- 只提取**你有权访问**的内容，并尊重源材料的授权协议与 Notion 服务条款。
  本工具自动化的是你手动也能做的事，它不绕过任何权限。

---

*凭证相关字段的权威定义见 [`../src/page_alchemist/config.py`](../src/page_alchemist/config.py)；排错先跑 `na doctor`。*
