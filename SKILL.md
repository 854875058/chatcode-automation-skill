---
name: chatcode-automation
description: 当你需要自动调用本地 ChatCode、抓取返回代码、查询 AI 占比、控制单次提交 AI 占比，或者在目标分支上完成真实 commit/push/回查时使用。适用于自动调用 ChatCode、抓代码块、AI 占比统计、单次提交占比控制、固定 commit 格式、按配置提交到指定仓库/分支等场景。
---

# ChatCode Automation

这是这个 skill 的主说明文件。

统一入口：

- `tools/chatcode_tool.py`

支持命令：

1. `task`
2. `stats`
3. `ready`
4. `boost`

## 这个 skill 的职责

1. 优先读取配置文件，而不是把仓库、分支、taskId 等值写死。
2. 统一通过 `tools/chatcode_tool.py` 执行，不鼓励零散脚本直调。
3. 默认把生成文件和运行产物写到仓库的 `chatcode/` 目录。
4. 统计主口径固定为 `sum(aiTotal) / sum(additions)`。
5. 提交流程必须校验目标分支和远程仓库。
6. 提交前要阻止无关 staged 文件混入。
7. `push` 后要支持按 `commitId` 自动回查统计接口。
8. 单次提交的 AI 占比要支持压到配置区间内，默认目标 `93%`，范围 `90%-95%`。

## 仓库布局

- `SKILL.md`
- `README.md`
- `config.example.json`
- `tools/chatcode_tool.py`
- `tools/run-chatcode-task.js`
- `tools/query-git-commit-stats.js`

## 配置重点

优先修改：

- `config.json`

关键字段：

- `git.repoPath`
- `git.remoteContains`
- `git.branch`
- `git.taskId`
- `git.commitMessage`
- `git.postPushVerify*`
- `commitRatio.*`
- `chatcode.host.*`
- `taskDefaults.*`
- `statsDefaults.*`
- `boostDefaults.*`

## 关键约束

### 目标分支

如果执行 `commit` 流程，必须有明确目标分支：

- 优先取 `config.json -> git.branch`
- 或者显式传 `--expected-branch`

没有目标分支时，工具应拒绝继续执行。

### staged 污染保护

如果当前 index 里已经有与本次 `commitFiles` 不相干的 staged 文件，工具应拒绝提交。

### 单次提交占比控制

当执行 `task --commit` 时，工具默认应尝试把单次提交 AI 占比控制在：

- 最低 `90%`
- 最高 `95%`
- 默认目标 `93%`

### push 后回查

当执行 `push` 时，工具默认应继续按 `commitId` 查询统计接口，确认平台已经记录该提交。

## 推荐用法

### 1. 先预热 ChatCode

```powershell
python .\tools\chatcode_tool.py ready `
  --host-launch-mode pycharm
```

### 2. 生成并提交

```powershell
python .\tools\chatcode_tool.py task `
  --ensure-ready `
  --host-launch-mode pycharm `
  --prompt-text "Only return one javascript code block..." `
  --output-path "chatcodeGenerated.js" `
  --commit `
  --push
```

### 3. 查询整体占比

```powershell
python .\tools\chatcode_tool.py stats `
  --begin-time "2026-04-08 00:00:00" `
  --end-time "2026-04-13 23:59:59" `
  --exclude-merge
```

### 4. 查询指定提交

```powershell
python .\tools\chatcode_tool.py stats `
  --begin-time "2026-04-13 00:00:00" `
  --end-time "2026-04-13 23:59:59" `
  --commit-id "<commit-id>"
```
