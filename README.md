<div align="center">

# ChatCode Automation Skill

**ChatCode 自动化技能工具包**

*Programmatic ChatCode driver for automated code generation, AI adoption metrics, and ratio optimization*

[![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python)](https://python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-18+-339933?logo=node.js)](https://nodejs.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows)](https://www.microsoft.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## Overview

企业推进 AI 辅助编码时面临三大痛点：**代码生成依赖手动操作**、**AI 采纳率缺乏量化手段**、**指标提升无法自动化闭环**。

本工具包通过 Windows IPC 命名管道直接驱动 ChatCode，实现从 **自动化代码生成** → **AI 采纳率统计** → **指标优化提升** 的完整闭环。三个子命令覆盖全流程，一条命令即可完成过去需要手动操作数十分钟的工作。

```
┌─────────────────────────────────────────────────────────┐
│                  ChatCode Automation Skill               │
├──────────────┬──────────────────┬────────────────────────┤
│  task        │  stats           │  boost                 │
│  代码生成     │  采纳率统计       │  指标优化               │
├──────────────┴──────────────────┴────────────────────────┤
│           Windows IPC Named Pipe + ChatCode API          │
├─────────────────────────────────────────────────────────┤
│              Git Repository + Backend API                 │
└─────────────────────────────────────────────────────────┘
```

## Key Features

### Automated Code Generation (`task`)
通过 IPC 命名管道驱动本地 ChatCode 实例，支持 CLI 文本或文件输入 Prompt，自动提取生成的代码块并保存到指定路径。全程无需打开 IDE，适合 CI/CD 集成。

### AI Adoption Metrics (`stats`)
查询 ChatCode 后端 API 获取 Git 提交统计，基于 `sum(aiTotal) / sum(additions)` 公式精确计算 AI 代码采纳率。支持按作者、项目、GitLab 实例、任务 ID 等多维度筛选，输出 JSON + CSV 双格式。

### Ratio Optimization (`boost`)
自动生成 ChatCode 提交以达到目标 AI 采纳率。可配置目标百分比、每批提交数、假设 AI 比率，自动创建特性分支并提交生成代码。

### Hierarchical Configuration
三级配置优先级：`CLI 参数` → `config.json` → `环境默认值`。自动发现 ChatCode 安装路径、Node.js 可执行文件、Git 仓库位置。

## Tech Stack

```
CLI Layer                         IPC Layer                        Data Layer
─────────────────                 ─────────────────                ─────────────────
Python 3 (Entrypoint)            Windows Named Pipes              Git Repository
argparse (CLI Parsing)            Node.js (IPC Driver)             ChatCode Backend API
JSON (Config)                     ChatCode Protocol                CSV / JSON (Output)
subprocess (Process Mgmt)         execjs (JS Runtime)              Commit History
```

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    chatcode_tool.py (Python CLI)              │
│  ┌──────────┐    ┌──────────────┐    ┌────────────────────┐  │
│  │  task     │    │    stats     │    │      boost         │  │
│  │ 代码生成  │    │  采纳率查询   │    │   指标优化提升      │  │
│  └────┬─────┘    └──────┬───────┘    └─────────┬──────────┘  │
│       │                 │                      │              │
│  ┌────▼─────────┐ ┌────▼──────────┐  ┌────────▼───────────┐ │
│  │ run-chatcode │ │ query-git     │  │  task + commit      │ │
│  │ -task.js     │ │ -commit       │  │  loop               │ │
│  │ (Node.js)    │ │ -stats.js     │  │  (Python + Node.js) │ │
│  └────┬─────────┘ └────┬──────────┘  └────────┬───────────┘ │
├───────┼─────────────────┼──────────────────────┼─────────────┤
│  ┌────▼─────────┐ ┌────▼──────────┐  ┌────────▼───────────┐ │
│  │  ChatCode    │ │  ChatCode     │  │  Git Repository    │ │
│  │  IPC Pipe    │ │  Backend API  │  │  + ChatCode        │ │
│  └──────────────┘ └───────────────┘  └────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Clone
git clone https://github.com/854875058/chatcode-automation-skill.git
cd chatcode-automation-skill

# 2. Configure
cp config.example.json config.json
# Edit config.json: set ChatCode root, node path, repo path, etc.

# 3. Generate code
python tools/chatcode_tool.py task \
  --prompt-text "Please output exactly one javascript code block." \
  --output-path "chatcode/chatcodeGenerated.js"

# 4. Query AI adoption ratio
python tools/chatcode_tool.py stats \
  --begin-time "2026-04-01 00:00:00" \
  --end-time "2026-04-14 23:59:59" \
  --exclude-merge

# 5. Boost ratio to target
python tools/chatcode_tool.py boost \
  --repo-path "D:\path\to\repo" \
  --expected-branch "feature_xxx"
```

## Project Structure

```
chatcode-automation-skill/
├── tools/
│   ├── chatcode_tool.py           # Python CLI entrypoint (task / stats / boost)
│   ├── run-chatcode-task.js       # Node.js IPC driver for ChatCode
│   └── query-git-commit-stats.js  # Node.js stats query via Backend API
├── config.example.json            # Configuration template
├── SKILL.md                       # Codex skill definition
└── README.md
```

## Usage

| Subcommand | Description | Key Options |
|------------|-------------|-------------|
| `task` | 驱动 ChatCode 生成代码 | `--prompt-text`, `--prompt-file`, `--output-path` |
| `stats` | 查询 AI 代码采纳率 | `--begin-time`, `--end-time`, `--author-email`, `--exclude-merge` |
| `boost` | 自动提交达到目标采纳率 | `--repo-path`, `--expected-branch`, `--target-ratio`, `--commits-per-batch` |

### AI Adoption Ratio Formula

```
AI 采纳率 = sum(aiTotal) / sum(additions)
```

### Commit Format

```
taskId:<taskId>
commit:<commitMessage>
```

## License

MIT
