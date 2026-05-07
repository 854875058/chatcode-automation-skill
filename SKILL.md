---
name: chatcode-automation
description: Use this skill when the user wants to automate local ChatCode usage, capture returned code blocks, query AI code ratio, or raise AI ratio through real ChatCode-generated commits. Triggers include 自动调用ChatCode、抓代码块、AI占比统计、冲目标占比、固定commit格式、按配置提交到指定仓库或分支。
---

# ChatCode Automation

This skill is the primary contract.
The scripts under `tools/chatcode-automation/` are only the execution backend.

Use the single Python entrypoint:

- [`tools/chatcode-automation/chatcode_tool.py`](E:\工作\国信\AI数据集项目\算子代码\ai-dataset-ui\tools\chatcode-automation\chatcode_tool.py)

Supported subcommands:

1. `task`
2. `stats`
3. `boost`

## Skill Responsibilities

When this skill is used, it should enforce all of the following:

1. Prefer config-driven behavior over hardcoded values.
2. Prefer the single Python entrypoint over ad hoc shell flows.
3. Treat scripts as implementation details, not the user-facing contract.
4. Use the correct AI ratio formula by default.
5. Default generated files into the project `chatcode/` directory.
6. Use the configured repository, branch, taskId, and commit message rules.
7. Only use real ChatCode generation and real commits for ratio boosting.

## Canonical Config

The canonical config file is:

- [`tools/chatcode-automation/config.json`](E:\工作\国信\AI数据集项目\算子代码\ai-dataset-ui\tools\chatcode-automation\config.json)

This skill should assume the config is the first place to change behavior.

Important sections:

### `chatcode`

- pipe name
- local storage root
- node path
- timeout
- polling interval

### `git`

- repository name
- repository path
- remote match rule
- target branch
- target task id
- default commit message
- commit/push defaults
- commit file defaults

### `taskDefaults`

- output directory
- output file name
- output mode
- inline copy count
- metadata output path

### `statsDefaults`

- time range
- author email
- project name
- gitlab instance
- optional taskId filter
- output json/csv paths

### `boostDefaults`

- default time range
- target ratio percent
- generated size per commit
- inline copy count
- max commit count
- assumed AI ratio

## Path Rules

Do not hardcode `Administrator` as the only source.

The skill should rely on the tool's dynamic discovery rules:

### ChatCode root

1. CLI parameter
2. `config.json`
3. `%USERPROFILE%\.chatcode`
4. scanned `C:\Users\*\ .chatcode`

### Node executable

1. CLI parameter
2. `config.json`
3. running ChatCode process
4. system `PATH`
5. scanned JetBrains plugin directories

## Output Rules

Generated ChatCode files should go under:

- `chatcode/`

Examples:

- `chatcode/chatcodeGenerated.js`
- `chatcode/bulkChunk01.js`
- `chatcode/stats-last-run.json`

Do not leave routine generated artifacts in `tools/chatcode-automation/`.

When generation speed matters, prefer this workflow:

1. Ask ChatCode for one medium-sized result, around 600 lines.
2. If more added lines are needed, expand that one response inside the same file.
3. Only split into multiple files when the user explicitly wants multiple files.

The tool supports single-file expansion through `taskDefaults.inlineCopyCount` and `boostDefaults.inlineCopyCount`.
The first copy stays as active code. Extra copies are appended as inline comment snapshots in the same file so the file remains low-risk and avoids redeclaration conflicts.

## Commit Rules

The commit format is always exactly two lines:

```text
taskId:<taskId>
commit:<commitMessage>
```

No blank line between them.

Current default commit message in config is:

```text
chatcode代码生成
```

Warn that repository hooks may still append AI metadata after these two lines.

## Real Statistics Formula

The real backend formula must be treated as canonical:

```text
SUM(AI采纳行数) / SUM(新增行数)
```

Which means:

```text
sum(aiTotal) / sum(additions)
```

This skill should not present `aiTotal / total` as the main ratio.

At most, `total` may be shown as a secondary diagnostic field.

## Statistics Defaults

For "today" or date-range summaries, the default should be:

- filter by author
- filter by project
- filter by gitlab instance
- optionally exclude merge
- do not filter by taskId unless the user explicitly asks

This is important because one developer may contribute to multiple taskIds on the same day.

So:

- default stats = overall daily/period ratio
- taskId stats = optional drill-down

## Boost Behavior

When the user asks to raise AI ratio, this skill should:

1. Query the current ratio first using the real formula.
2. Compute how many additional AI-adopted lines are needed.
3. Generate real ChatCode code into `chatcode/`.
4. Commit and push against the configured target branch/task.
5. Re-query the ratio.
6. Repeat until the target ratio is reached or the configured max attempts is exhausted.

This skill should prefer:

- simple, high-match-rate generated files
- low-risk standalone utility/data files under `chatcode/`
- single-commit additions below the platform threshold

## Recognition Workflow

When the user's platform only compares against recent ChatCode answers, use this default workflow:

1. Start with one small verification commit first.
2. Wait for the platform to index that commit.
3. Confirm the AI ratio for that single commit is not `0%`.
4. Only after that, continue with larger "boost" commits.

This matters because a commit can be real code but still score `0%` if it does not match the platform's recent ChatCode answer records.

So for ratio-sensitive work:

- prefer a small-file test before large-file batching
- prefer normal ChatCode completion paths over fallback reconstruction
- do not treat "content came from a task log" as sufficient proof that the platform will recognize it
- if the small-file test scores `0%`, adjust the workflow before generating large follow-up commits

## Recommended Commands

### Generate code

```bash
python .\tools\chatcode-automation\chatcode_tool.py task \
  --prompt-text "Only return one javascript code block with about 600 lines of standalone utility code." \
  --output-path "codecCatalogGenerated.js" \
  --inline-copy-count 4
```

### Query overall ratio

```bash
python .\tools\chatcode-automation\chatcode_tool.py stats \
  --begin-time "2026-04-09 00:00:00" \
  --end-time "2026-04-10 23:59:59" \
  --author-email "zhanghaonan_56@bonc.com.cn" \
  --project-name "AI数据集" \
  --gitlab-instance "gitlab.tianti.tg.unicom.local" \
  --exclude-merge
```

### Boost ratio

```bash
python .\tools\chatcode-automation\chatcode_tool.py boost \
  --repo-path "E:\工作\国信\AI数据集项目\算子代码\ai-dataset-ui-7332563" \
  --expected-branch "feature_7332563_20260423" \
  --expected-remote-contains "gitlab.tianti.tg.unicom.local" \
  --inline-copy-count 4
```

## Communication Rule

When using this skill:

1. Report both the action taken and the current ratio.
2. State clearly whether the reported ratio is:
   - overall period ratio
   - task-specific ratio
3. If boosting is still in progress, say exactly how far the current ratio is from the target.
