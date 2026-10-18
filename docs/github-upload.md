# 上线到 GitHub（Upload Guide）

本地仓库已 `git init` 并完成首次提交（53 个文件）。推到 GitHub 是**外部动作**，
按你的操作规范由你确认后执行——本文给你一条可直接跑的命令序列。

> ⚠️ 推送前先确认：仓库里没有 `.env`、`output/`、`examples/demo_output/`
> （都已在 `.gitignore`）。当前提交只含源码、测试、文档与品牌资产。

## 第 1 步：替换占位符 `YOUR_GITHUB_USERNAME` —— ✅ 已完成

占位符已全部替换为实际用户名 `yuhao-xin`，涉及 5 个文件：`pyproject.toml`、
`README.md`、`README.zh-CN.md`、`CONTRIBUTING.md`、`docs/github-upload.md`（本文件）。
校验方式（应无输出）：

```bash
grep -rn "YOUR_GITHUB_USERNAME" . --include="*.md" --include="*.toml" | grep -v "./.git/"
```

## 第 2 步：在 GitHub 建仓库

**方式 A — 网页**：<https://github.com/new> → 仓库名 `notion-alchemist` →
**不要**勾选 "Add a README"（本地已有）→ Create repository。

**方式 B — GitHub CLI**（已装 `gh` 并登录的话）：

```bash
gh repo create notion-alchemist --public \
  --description "Extract, cleanse, restructure and re-publish Notion pages you are authorised to access, into your own workspace or an import-ready Markdown bundle."
```

## 第 3 步：推送

```bash
git remote add origin https://github.com/yuhao-xin/notion-alchemist.git
git branch -M main
git push -u origin main
```

## 第 4 步：上线后检查清单

| 项 | 操作 |
|---|---|
| About 描述 | 仓库页右侧齿轮 → 粘贴 description（见方式 B 的命令） |
| Topics | `notion` `notion-api` `knowledge-base` `automation` `cli` `agent-skill` `python` |
| Issues | 确认 bug/feature 模板生效（`.github/ISSUE_TEMPLATE/`） |
| Actions | Push 后 CI 自动跑：stdlib 测试、pytest、ruff、CLI smoke。全绿才算上线成功 |
| Social preview | Settings → General → Social preview，可上传 `assets/banner.svg` 渲染图 |
| Releases | Tags → New release `v0.1.0`（CHANGELOG 已备好条目） |
| Secrets（仅定时任务需要） | Settings → Secrets → Actions → 加 `NOTION_TOKEN` / `NA_PARENT_PAGE`，**不要**提交进仓库 |

## 常见问题

**Q：push 被拒 `remote contains work that you do not have locally`？**
建仓库时勾了 "Add a README"。先 `git pull --rebase origin main` 再推，
或删掉远程仓库重建（别勾初始化项）。

**Q：想改成私有仓库？**
建库时选 Private 即可；代码与功能无差异。README 里的徽章链接仍指向你的
用户名，无需改动。

**Q：CI 红了怎么办？**
点进 Actions → 失败的 job → 展开日志。最常见是 `requests` 未装导致
extract/publish 相关 job 失败——CI 里已 `pip install -e ".[dev]"`，
若自定义 workflow 记得带上这步。
