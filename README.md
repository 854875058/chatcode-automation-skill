# chatcode-automation-skill

This repository contains a reusable Codex skill plus helper scripts for:

1. driving local ChatCode automatically
2. extracting final code blocks
3. querying AI code adoption ratio
4. boosting AI ratio through real ChatCode-generated commits

## Included files

- `SKILL.md`
- `config.example.json`
- `tools/chatcode_tool.py`
- `tools/run-chatcode-task.js`
- `tools/query-git-commit-stats.js`

## Main entrypoint

Use:

```bash
python .\tools\chatcode_tool.py <subcommand> ...
```

Subcommands:

- `task`
- `stats`
- `boost`

## Config

Copy:

- `config.example.json`

to:

- `config.json`

Then edit:

- ChatCode root
- node path
- target repo path
- target branch
- task id
- commit message
- output directory
- stats defaults
- boost defaults

## Recommended output directory

Use a dedicated output directory such as:

- `chatcode/`

This keeps generated files and runtime metadata out of the tools folder.

## Real AI ratio formula

Use the backend rule:

```text
SUM(AI采纳行数) / SUM(新增行数)
```

That means:

```text
sum(aiTotal) / sum(additions)
```

## Typical usage

### Generate code

```bash
python .\tools\chatcode_tool.py task \
  --prompt-text "Please output exactly one javascript code block." \
  --output-path "chatcodeGenerated.js"
```

### Query ratio

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
