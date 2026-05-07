# ChatCode Automation

Unified entrypoint:

- `chatcode_tool.py`

Supported commands:

1. `task`
2. `stats`
3. `ready`
4. `boost`

## Files

- `chatcode_tool.py`
- `config.json`
- `config.example.json`
- `run-chatcode-task.js`
- `query-git-commit-stats.js`

## Config

The tool reads `config.json` in this directory by default.

Main sections:

1. `chatcode`
2. `git`
3. `commitRatio`
4. `taskDefaults`
5. `statsDefaults`
6. `boostDefaults`

`taskDefaults.inlineCopyCount` controls single-file expansion:

- `1`: write the generated code once
- `>1`: keep the first copy as active code, then append extra inline comment snapshots in the same file

`boostDefaults.inlineCopyCount` applies the same expansion during `boost`, so one model call can contribute more added lines without splitting into multiple files.

`chatcode.host` controls readiness behavior:

- `ensureReady`: whether to check readiness before `task` or `boost`
- `launchMode`: `manual` or `pycharm`
- `launcherPath`: optional override for the host executable
- `launcherArgs`: optional launcher arguments, supports `{repo_path}`
- `startupTimeoutSec`: wait timeout for the `chatcode-ipc` pipe

`commitRatio` controls per-commit shaping:

- `enabled`: whether to add manual non-AI padding before commit
- `minAiRatioPercent`: lower bound for estimated single-commit AI ratio
- `maxAiRatioPercent`: upper bound for estimated single-commit AI ratio
- `targetAiRatioPercent`: shaping target, recommended to stay between the bounds

The commit workflow also has two built-in safety rails:

- it refuses to commit if unrelated files are already staged
- after `push`, it can automatically poll the ChatCode stats API by `commitId`

## Output Layout

Generated files should go under the project `chatcode/` directory.

Default outputs:

- `chatcode/chatcodeGenerated.js`
- `chatcode/last-run.json`
- `chatcode/stats-last-run.json`
- `chatcode/stats-last-run.csv`

## Ratio Formula

The primary AI ratio is:

```text
sum(aiTotal) / sum(additions)
```

`aiTotal / total` is only a secondary diagnostic value.

## Examples

Generate one file from ChatCode:

```powershell
python .\tools\chatcode-automation\chatcode_tool.py task `
  --prompt-text "Only return one javascript code block that exports a utility array." `
  --output-path "codecCatalogGenerated.js"
```

Generate once and expand the result inside the same file:

```powershell
python .\tools\chatcode-automation\chatcode_tool.py task `
  --prompt-text "Only return one javascript code block with about 600 lines of standalone utility code." `
  --output-path "codecCatalogGenerated.js" `
  --inline-copy-count 4
```

Query ratio stats:

```powershell
python .\tools\chatcode-automation\chatcode_tool.py stats `
  --begin-time "2026-04-09 00:00:00" `
  --end-time "2026-04-10 23:59:59" `
  --exclude-merge
```

Warm up ChatCode and confirm the IPC pipe is ready:

```powershell
python .\tools\chatcode-automation\chatcode_tool.py ready `
  --host-launch-mode pycharm
```

Dry-run a boost plan:

```powershell
python .\tools\chatcode-automation\chatcode_tool.py boost `
  --begin-time "2026-04-09 00:00:00" `
  --end-time "2026-04-10 23:59:59" `
  --target-ratio-percent 70 `
  --dry-run
```

Boost with single-file inline copies:

```powershell
python .\tools\chatcode-automation\chatcode_tool.py boost `
  --begin-time "2026-04-09 00:00:00" `
  --end-time "2026-04-10 23:59:59" `
  --inline-copy-count 4 `
  --push
```

Run a real boost:

```powershell
python .\tools\chatcode-automation\chatcode_tool.py boost `
  --repo-path "E:\工作\国信\AI数据集项目\算子代码\ai-dataset-ui" `
  --expected-branch "feature_7332563_20260423" `
  --expected-remote-contains "gitlab.tianti.tg.unicom.local" `
  --push
```

Ensure ChatCode is ready, and only fall back to PyCharm if needed:

```powershell
python .\tools\chatcode-automation\chatcode_tool.py task `
  --ensure-ready `
  --host-launch-mode pycharm `
  --prompt-text "Only return one javascript code block that exports const readyPing = true;" `
  --output-path "readyPing.js"
```

Override the single-commit AI ratio target:

```powershell
python .\tools\chatcode-automation\chatcode_tool.py task `
  --ensure-ready `
  --host-launch-mode pycharm `
  --target-commit-ai-ratio-percent 92 `
  --prompt-text "Only return one javascript code block that exports const ratioPing = true;" `
  --output-path "ratioPing.js" `
  --commit
```

## Commit Message Format

The generated commit message file uses exactly two lines:

```text
taskId:7332563
commit:chatcode code generation
```

## Notes

- `boost` first queries current stats, then computes the missing additions needed to reach the target ratio.
- `boost` writes generated files under `chatcode/` and can commit and push them with the configured branch and task id.
- when `inlineCopyCount > 1`, the tool reuses one ChatCode response inside the same file by appending line-comment snapshots, which is much faster than waiting for multiple large generations.
- if your platform only compares commits against ChatCode answers from the last 5 days, use a two-step workflow: first push one small verification commit, confirm it is not `0%`, then push larger commits for volume.
- for ratio-sensitive commits, normal ChatCode completion is preferred over fallback reconstruction from task logs, because fallback reconstruction may not be recognized by the platform as ChatCode code.
- committed task outputs are automatically padded to the configured single-commit AI ratio target unless you disable shaping.
- pushed commits are verified against the stats API by default.
- Repository hooks may still append extra metadata after commit creation.
