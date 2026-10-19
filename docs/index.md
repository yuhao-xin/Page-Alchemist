# Documentation index

Language tags: **en** = English · **zh** = 中文.
Both READMEs link here; every doc below is also reachable from
[`README.md`](../README.md) / [`README.zh-CN.md`](../README.zh-CN.md).

## Start here

| Doc | Lang | What it is | Read it when |
|---|---|---|---|
| [notion-token-setup.en.md](notion-token-setup.en.md) | en | Credential tutorial, ~5 min, no code | **First.** You cannot run extract/publish without it |
| [notion-token-setup.md](notion-token-setup.md) | zh | 同上，中文版 | 同上 |

## How it is built

| Doc | Lang | What it is | Read it when |
|---|---|---|---|
| [architecture.en.md](architecture.en.md) | en | IR shape, both engines, write-back strategy, API-version policy | You want to know *why* it is built this way, or plan to contribute |
| [architecture.md](architecture.md) | zh | 同上，中文版 | 同上 |
| [transform-rules.md](transform-rules.md) | zh | Every cleanse rule with before/after examples | You want to know exactly what "cleanse" changes |
| [pm-review.md](pm-review.md) | zh | Product-manager review + SkillHub rubric cross-check | You want the honest critique, including what is *not* built |

## Reference

| Doc | Lang | What it is |
|---|---|---|
| [../references/cli-reference.md](../references/cli-reference.md) | en | Full CLI surface, generated from `--help` |
| [../SKILL.md](../SKILL.md) | en | Agent-Skill instructions, golden rules, intent→command map |
| [feishu-publish.en.md](feishu-publish.en.md) | en | Copy the IR into Feishu/Lark Docs — app setup, scopes, behaviour notes |
| [feishu-publish.md](feishu-publish.md) | zh | 同上，中文版（发布到飞书云文档） |
| [faq.md](faq.md) | zh | Common problems, error codes, copyright stance |

## Tooling

| Script | What it is |
|---|---|
| [../scripts/skillhub_preflight.py](../scripts/skillhub_preflight.py) | 12-item SkillHub pre-flight self-check, exit `0`/`1`/`2` |
| [../scripts/run_tests.py](../scripts/run_tests.py) | Zero-dependency test runner (`python scripts/run_tests.py`) |
| [../scripts/na.sh](../scripts/na.sh) · [../scripts/na.ps1](../scripts/na.ps1) | Run from a checkout without installing |

## Ops & repo

| Doc | Lang | What it is |
|---|---|---|
| [github-upload.md](github-upload.md) | zh | Push this repo to GitHub, step by step |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | en | How to contribute |
| [../SECURITY.md](../SECURITY.md) | en | Security policy and reporting |

## Sample output

| Path | What it is |
|---|---|
| [../examples/sample-output/](../examples/sample-output/) | A trimmed, committed `na demo` result — before/after + reports, viewable without installing anything |

---

*Translation status: the highest-friction docs (credentials, architecture,
Feishu publish) are bilingual. `transform-rules.md`, `faq.md` and
`github-upload.md` are Chinese-only for now; the primary audience for those is
Chinese-speaking users. Contributions of English versions are welcome.*