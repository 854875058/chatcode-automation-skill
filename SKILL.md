---
name: chatcode-automation
description: Use this skill when you want to automate local ChatCode usage, capture returned code blocks, query AI code adoption ratio, or raise AI ratio through real ChatCode-generated commits. Triggers include 自动调用ChatCode、抓代码块、AI占比统计、冲目标占比、固定commit格式、按配置提交到指定仓库/分支.
---

# ChatCode Automation

This skill uses the local scripts under `tools/` as its execution backend.

Main entrypoint:

- `tools/chatcode_tool.py`

Supported subcommands:

1. `task`
2. `stats`
3. `boost`

## What this skill should do

When this skill is triggered, it should:

1. Prefer configuration over hardcoded values.
2. Use the single Python entrypoint instead of ad hoc manual command chains.
3. Put generated files under a configurable output directory, recommended: `chatcode/`.
4. Use the real backend AI ratio formula:
   `sum(aiTotal) / sum(additions)`
5. Treat overall daily/period ratio as the default statistics view.
6. Only use real ChatCode generation and real commits for ratio improvement.

## Configuration

Edit:

- `config.json`

Important sections:

- `chatcode`
- `git`
- `taskDefaults`
- `statsDefaults`
- `boostDefaults`

Typical settings:

- target repository path
- target branch
- task id
- commit message
- output directory
- default statistics range
- default ratio target

## Output Rules

Recommended generated output location:

- `chatcode/`

Typical artifacts:

- `chatcode/chatcodeGenerated.js`
- `chatcode/last-run.json`
- `chatcode/stats-last-run.json`
- `chatcode/stats-last-run.csv`

## Path Discovery

This skill should not assume one fixed Windows username.

The tool resolves ChatCode local storage in this order:

1. CLI parameter
2. `config.json`
3. `%USERPROFILE%\.chatcode`
4. scanned `C:\Users\*\ .chatcode`

The tool resolves `node.exe` in this order:

1. CLI parameter
2. `config.json`
3. running ChatCode process
4. system `PATH`
5. scanned JetBrains plugin directories

## Commit Format

Use exactly two lines:

```text
taskId:<taskId>
commit:<commitMessage>
```

No blank line between them.

Warn that repository hooks may append extra AI metadata automatically.

## Real Statistics Formula

Use this as the canonical ratio:

```text
SUM(AI采纳行数) / SUM(新增行数)
```

That means:

```text
sum(aiTotal) / sum(additions)
```

Do not present `aiTotal / total` as the primary ratio.

## Recommended commands

### Generate code

```bash
python .\tools\chatcode_tool.py task \
  --prompt-text "请只输出一个 javascript 代码块，生成一个视频编码工具文件。" \
  --output-path "codecCatalogGenerated.js"
```

### Query overall ratio

```bash
python .\tools\chatcode_tool.py stats \
  --begin-time "2026-04-09 00:00:00" \
  --end-time "2026-04-10 23:59:59" \
  --exclude-merge
```

### Boost ratio

```bash
python .\tools\chatcode_tool.py boost \
  --repo-path "D:\path\to\repo" \
  --expected-branch "feature_xxx" \
  --expected-remote-contains "gitlab.example.com"
```
