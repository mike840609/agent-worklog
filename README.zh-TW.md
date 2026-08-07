# Agent Worklog

[![CI](https://github.com/mike840609/agent-worklog/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/agent-worklog/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/agent-worklog/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/agent-worklog/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/agent-worklog.svg)](https://pypi.org/project/agent-worklog/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/agent-worklog/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/agent-worklog/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/agent-worklog/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/agent-worklog)

[English](https://github.com/mike840609/agent-worklog/blob/main/README.md) | 繁體中文

Agent Worklog 把 coding-agent 的工作階段整理成給主管看的週報，替工程師省下時間。

![Agent 工作階段被分組為每週工程報告](https://github.com/mike840609/agent-worklog/raw/refs/heads/main/docs/assets/agent-worklog-overview.png)

## 架構

<!-- 這裡用 render 好的圖而非 mermaid 區塊：GitHub 手機 App 與 PyPI 會把 mermaid
     原始碼當純文字顯示。要修改請編輯 docs/assets/architecture.mmd，
     並依該檔開頭的指令重新產生 SVG。 -->

![架構圖：CLI 讀取三種工作階段來源之一，掃描並解析 repository，再擷取、去敏、摘要並寫出報告](https://github.com/mike840609/agent-worklog/raw/refs/heads/main/docs/assets/architecture.svg)

Agent Worklog 會依 harness 選用三種來源之一，只載入與指定期間重疊的工作階段，依
repository 分組，再對佐證資料做去敏與摘要，最後以僅擁有者可讀寫的權限原子性地寫出
Markdown 報告。

## 功能

Agent Worklog 支援 OpenCode、Claude Code 與 Codex。無論選用哪一種支援的 coding-agent
harness，都可以：

- 找出所有專案的 coding-agent 工作階段，不受目前所在資料夾限制。
- 依照最近幾天、某一個日曆週，或指定的日期區間挑選工作階段。
- 把屬於同一個 repository 的 Git worktree 歸為同一組。
- 讓 child 與 subagent 工作階段連結到正確的 repository，或使用 `--root-only` 排除它們。
- 在報告中列出每個 repository 的工作階段標題與工作資料夾。
- 在所選 harness 提供資料時，依模型彙整 token 使用量。
- 在產生報告或呼叫本機敘事式 `opencode run` 之前，先檢查工作階段資訊中常見的機密字串樣式。

## 系統需求

- Python 3.11 以上。
- 可以用 `git` 執行的 Git。
- 一個 coding-agent harness：OpenCode（預設）、Claude Code 或 Codex。OpenCode 需要一個提供
  `opencode db` 與 `opencode export` 的 `opencode` 執行檔；預設的敘事式報告還會用到
  `opencode run`，usage 統計則會用到 `opencode stats`；Claude Code 與 Codex
  不需要命令列工具，只需要一個可讀取的逐字紀錄存放處（`~/.claude/projects` 或 `~/.codex`）。

## 安裝

建議使用 `pipx` 安裝這個命令列工具：

```bash
pipx install agent-worklog
```

也可以安裝在一般的 Python 環境中：

```bash
pip install agent-worklog
```

開發用：

```bash
git clone https://github.com/mike840609/agent-worklog.git
cd agent-worklog
uv sync --locked --extra dev
```

## 快速開始

先確認所選的 harness 與 Git 都可以使用：

```bash
agent-worklog doctor
```

預覽 Agent Worklog 如何把上一個完整週的資料分組成 repository：

```bash
agent-worklog scan --period last-week
```

產生 Markdown 報告；預設會在本機執行 `opencode run` 來撰寫敘事式週報：

```bash
agent-worklog report --period last-week
```

要改為決定性的結構化報告，加上 `--no-llm`：

```bash
agent-worklog report --period last-week --no-llm
```

預設輸出會寫到 `reports/` 底下。

上面三個指令預設都是 `--harness opencode`。要用 Claude Code 或 Codex 的話，各自加上
`--harness claude-code` 或 `--harness codex` 即可。敘事式預設對所有 harness 一致：
它會讀取該 harness 的工作階段，並同樣呼叫本機的 `opencode run` 來撰寫週報。若未安裝
OpenCode，加上 `--no-llm`；決定性的結構化報告對所有 harness 都可用，且不需要 OpenCode：

```bash
agent-worklog doctor --harness claude-code
agent-worklog report --harness claude-code --period last-week
agent-worklog report --harness claude-code --period last-week --no-llm
agent-worklog doctor --harness codex
agent-worklog report --harness codex --period last-week
agent-worklog report --harness codex --period last-week --no-llm
```

## 指令參考

| 指令 | 用途 |
|---|---|
| `doctor` | 檢查目前選用的 harness 與 `git` 是否就緒。 |
| `scan` | 顯示哪些工作階段落在指定期間內，以及它們如何分組成 repository。 |
| `report` | 產生指定期間的 Markdown 報告。 |
| `config` | 顯示與編輯設定檔：`path`、`list`、`set`、`unset`。 |

`scan` 與 `report` 共用這些選項：

| 選項 | 用途 |
|---|---|
| `--days N` | 統計到現在為止的最近 N 天。 |
| `--period last-week` | 統計上一個完整的日曆週。`last-week` 是唯一可用的值。 |
| `--since ISO` | 以指定時間作為期間起點。 |
| `--until ISO` | 以指定時間作為期間終點，必須搭配 `--since`。 |
| `--harness NAME` | 讀取工作階段所用的 harness：`opencode`（預設）、`claude-code` 或 `codex`。 |
| `--root-only` | 排除 child 與 subagent 工作階段。 |
| `--sanitize / --no-sanitize` | 開啟或關閉 OpenCode 匯出去敏；預設使用 raw export。僅適用 OpenCode。 |
| `--verbose` | 同時顯示匯出、備援與敘事式摘要相關的警告。用於 `scan` 時，也會列出每個 repository 的工作階段標題與工作目錄。 |
| `--quiet` | `scan` 只顯示工作階段數量，`report` 只顯示輸出路徑。 |

`scan` 與 `report` 執行時會顯示暫時性的進度狀態，指出目前所在階段。處理工作階段與
repository 時也會顯示 `已完成數/總數`。`--quiet` 會隱藏進度狀態。使用
`report --dry-run` 時，進度會寫入 stderr，stdout 只會包含 Markdown。

`report` 另外還接受：

| 選項 | 用途 |
|---|---|
| `--output PATH` | 寫到指定檔案，而不是預設資料夾。 |
| `--force` | 輸出檔案已存在時直接覆寫。 |
| `--dry-run` | 直接印出 Markdown，不寫入檔案。 |
| `--no-llm` | 跳過本機 `opencode run` 的敘事式報告，直接輸出決定性的結構化報告。 |
| `--detail LEVEL` | 報告的詳細程度：`full`（預設）或 `brief`。 |

`--detail brief` 會產生適合貼進週報的簡短報告：保留標頭，每個 repository 保留
`Repository:` 遠端資訊那一行、工作階段數量，以及摘要與 Completed、Problems Resolved、
In Progress 各最多五條，不輸出 Key Files、Directories、Sessions、Branches 與用量表格。
警告在兩種詳細程度下都會保留，因為警告說明的是工具讀不到的資料，而不是你做過的工作。

`doctor` 也接受 `--harness NAME`、`--quiet` 與 `--verbose`。`--quiet` 會隱藏檢查清單，只用結束代碼回報結果；`--verbose` 不會改變 `doctor` 的輸出內容。
使用 `--harness claude-code` 時，`doctor` 會改為檢查設定的 `~/.claude/projects` 資料夾是否存在且可讀，而不是檢查 `opencode` 執行檔與資料庫。使用 `--harness codex` 時，`doctor` 會檢查設定的 `~/.codex` 資料夾是否存在且可讀，並回報將採用哪一種探索方式：依名稱顯示的狀態資料庫，或在資料庫不存在時顯示 `directory scan`。

有三條規則：

- `--days`、`--period`、`--since` 三者只能擇一使用（`scan` 與 `report`）。
- `--until` 只能搭配 `--since` 使用（`scan` 與 `report`）。
- `--verbose` 與 `--quiet` 不能同時使用（三個指令都適用）。

## 設定

Agent Worklog 的每項設定都先讀環境變數，環境變數沒有設定的部分則讀設定檔。每項設定的
順序是：環境變數、設定檔、預設值。

設定一次就會寫進設定檔：

```bash
agent-worklog config set opencode.cli.model deepseek-r1
agent-worklog config set report.timezone Europe/Berlin
agent-worklog config list
```

`config list` 會列出每項設定的目前值、該值來自環境變數、設定檔或預設值，以及預設值本身。
每項設定都是選填的：值留空即回到預設值，`unset` 也是同樣的效果。

```bash
agent-worklog config set opencode.cli.model ""
agent-worklog config unset report.timezone
```

`agent-worklog config path` 會印出設定檔位置。設定 `AGENT_WORKLOG_CONFIG_FILE` 可以改用
其他檔案。

變數名稱以 `AGENT_WORKLOG_` 開頭，設定名稱的各層之間用 `__` 分隔。已匯出的環境變數在該
shell 中會覆蓋設定檔：

```bash
export AGENT_WORKLOG_REPORT__TIMEZONE="Asia/Taipei"
export AGENT_WORKLOG_REPORT__OUTPUT_DIRECTORY="reports"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE="opencode"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__SANITIZE="false"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__RUN_TIMEOUT_SECONDS="600.0"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__MODEL=""
```

完整設定清單請見
[設定指南](https://github.com/mike840609/agent-worklog/blob/main/docs/configuration.md)。

## 隱私

OpenCode 預設使用 raw export，讓報告保留可用的工作細節。Agent Worklog 會先在本機清理
常見機密，然後把分組、去敏後的原始 transcript 交給本機安裝的 `opencode run` 撰寫敘事式
週報；資料不會離開本機，也不需要 API key。要決定性的結構化報告可用 `--no-llm`。需要
OpenCode 強力遮蔽時可加入 `--sanitize`，但這會刻意移除大部分工作 evidence。報告仍可能
包含私人目標、檔名、指令與完整路徑——分享前請務必檢查。

詳細的資料安全與目前限制，請見
[隱私與安全](https://github.com/mike840609/agent-worklog/blob/main/docs/privacy.md)。

## 結束代碼

| 代碼 | 意義 |
|---:|---|
| 0 | 成功 |
| 2 | 指令選項無效 |
| 3 | 設定錯誤 |
| 4 | 沒有符合的活動 |
| 5 | Harness 或 Git 相依性錯誤 |
| 7 | 報告檔案錯誤 |

如果某個工作階段無法讀取，Agent Worklog 會略過它並在報告中加上警告。如果所有工作階段
都無法讀取，指令會直接以錯誤結束，而不會產生空白報告。

## 支援範圍與限制

目前支援的工具是 OpenCode、Claude Code 與 Codex，用 `--harness` 挑選。報告格式只有
Markdown，而且 Agent Worklog 不會在多次執行之間保留快取。

- [使用指南](https://github.com/mike840609/agent-worklog/blob/main/docs/guides.md) — 統計期間、subagent、repository 分組、敘事式與結構化報告與輸出處理。
- [使用量統計](https://github.com/mike840609/agent-worklog/blob/main/docs/usage-statistics.md) — 使用量區塊的產生方式與期間但書。
- [目前支援範圍與限制](https://github.com/mike840609/agent-worklog/blob/main/docs/limitations.md) — 各 harness 的完整但書清單。

## 開發檢查

```bash
uv sync --locked --extra dev
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
```

發布流程請見
[Releasing Agent Worklog](https://github.com/mike840609/agent-worklog/blob/main/docs/releasing.md)。

## 授權

MIT
