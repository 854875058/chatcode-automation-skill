# chatcode-automation-skill

这是一个可分享的 ChatCode 自动化技能仓库，用来把下面这几件事稳定串起来：

1. 自动调用本地 ChatCode
2. 抓取返回代码或工作区工具修改结果
3. 查询 AI 占比
4. 在目标分支上做真实 `commit + push`
5. 控制单次提交 AI 占比在设定区间内
6. `push` 后按 `commitId` 自动回查平台统计

## 仓库内容

- `SKILL.md`
- `README.md`
- `config.example.json`
- `tools/chatcode_tool.py`
- `tools/run-chatcode-task.js`
- `tools/query-git-commit-stats.js`

## 统一入口

```powershell
python .\tools\chatcode_tool.py <subcommand> ...
```

支持命令：

- `task`
- `stats`
- `ready`
- `boost`

## 配置方式

先复制：

- `config.example.json`

为：

- `config.json`

然后按需修改：

- ChatCode 本地目录
- node 路径
- 目标仓库路径
- 目标分支
- taskId
- commit message
- 单次提交占比目标
- push 后回查策略

## 关键能力

### 1. `ready`

单独做环境预热和就绪探测：

- 检查 `chatcode-ipc`
- 识别 ChatCode 插件 `node.exe`
- 识别 `.chatcode` 根目录
- 必要时兜底拉起宿主

### 2. `task`

完成一次真实生成流程：

- 等待 ChatCode 就绪
- 调用 IPC 发任务
- 抓返回结果
- 写入目标文件
- 可选 commit / push

### 3. staged 污染保护

如果当前已经有无关 staged 文件，工具会拒绝提交，避免把非目标文件混进本次 commit。

### 4. 单次提交 AI 占比控制

默认配置：

- 最低 `90%`
- 最高 `95%`
- 目标 `93%`

工具会在提交前自动补齐少量非 AI 新增行，把单次提交控制到目标区间附近。

### 5. push 后自动回查

推送后会继续按 `commitId` 查询平台统计接口，直接确认：

- `commitCount`
- `additions`
- `aiTotal`
- `aiRatioPercent`

## 常用示例

### 预热环境

```powershell
python .\tools\chatcode_tool.py ready `
  --host-launch-mode pycharm
```

### 生成并提交

```powershell
python .\tools\chatcode_tool.py task `
  --ensure-ready `
  --host-launch-mode pycharm `
  --prompt-text "Only return one javascript code block..." `
  --output-path "chatcodeGenerated.js" `
  --commit `
  --push
```

### 查询时间区间整体占比

```powershell
python .\tools\chatcode_tool.py stats `
  --begin-time "2026-04-08 00:00:00" `
  --end-time "2026-04-13 23:59:59" `
  --exclude-merge
```

### 查询单次提交占比

```powershell
python .\tools\chatcode_tool.py stats `
  --begin-time "2026-04-13 00:00:00" `
  --end-time "2026-04-13 23:59:59" `
  --commit-id "<commit-id>"
```
