# Agent Worklog

[![CI](https://github.com/mike840609/agent-worklog/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/agent-worklog/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/agent-worklog/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/agent-worklog/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/agent-worklog.svg)](https://pypi.org/project/agent-worklog/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/agent-worklog/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/agent-worklog/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/agent-worklog/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/agent-worklog)

[English](https://github.com/mike840609/agent-worklog/blob/main/README.md) | 繁體中文

Agent Worklog 把 coding agent 的工作階段（session）整理成給主管看的週報，替工程師省下時間。

![工作階段會被分組成每週工程報告](https://github.com/mike840609/agent-worklog/raw/refs/heads/main/docs/assets/agent-worklog-overview.png)

## 功能

Agent Worklog 目前支援 OpenCode，可以：

- 找出所有專案的 OpenCode 工作階段，不論你現在位於哪個資料夾。
- 依照最近幾天、某一個日曆週，或指定的日期區間挑選工作階段。
- 使用 `opencode export --sanitize` 匯出工作階段。
- 把屬於同一個 repository 的 Git worktree 歸為同一組。
- 讓子工作階段（child session）連結到正確的 repository。
- 使用 `--root-only` 排除 subagent 工作階段，只保留根工作階段。
- 在報告中列出每個 repository 的工作階段標題與工作資料夾。
- 依 `opencode stats` 彙整模型、token 與工具的使用狀況。
- 附上來源活動 ID 與信心程度作為佐證資訊。
- 在產生報告或送資料給選用的 LLM 之前，先檢查工作階段資訊中常見的機密字串樣式。
- 某個工作階段匯出失敗時仍會繼續執行，並在報告中加上警告。
- 在 POSIX 系統上，以僅擁有者可讀寫的 `0600` 權限寫出報告。

## 系統需求

- Python 3.11 以上
- 可以用 `opencode` 執行的 OpenCode
- 支援 `opencode db` 與 `opencode export --sanitize` 的 OpenCode 版本
- 可以用 `git` 執行的 Git

`opencode stats` 是選用的。沒有它時，Agent Worklog 會略過使用量區塊，仍然會產生報告。

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

先確認 OpenCode 與 Git 都可以使用：

```bash
agent-worklog doctor
```

預覽 Agent Worklog 如何把上一個完整週的資料分組成 repository：

```bash
agent-worklog scan --period last-week
```

不使用外部 LLM，直接產生 Markdown 報告：

```bash
agent-worklog report --period last-week --no-llm
```

預設輸出會寫到 `reports/` 底下。

## 指令參考

| 指令 | 用途 |
|---|---|
| `doctor` | 檢查 `opencode` 與 `git` 能否執行，以及能否找到 OpenCode 資料庫。 |
| `scan` | 顯示哪些工作階段落在指定期間內，以及它們如何分組成 repository。 |
| `report` | 產生指定期間的 Markdown 報告。 |

`scan` 與 `report` 共用這些選項：

| 選項 | 用途 |
|---|---|
| `--days N` | 統計到現在為止的最近 N 天。 |
| `--period last-week` | 統計上一個完整的日曆週。`last-week` 是唯一可用的值。 |
| `--since ISO` | 以指定時間作為期間起點。 |
| `--until ISO` | 以指定時間作為期間終點，必須搭配 `--since`。 |
| `--root-only` | 排除 subagent 工作階段。 |
| `--verbose` | 同時顯示匯出、備援與 LLM 相關的警告。 |
| `--quiet` | `scan` 只顯示工作階段數量，`report` 只顯示輸出路徑。 |

`report` 另外還接受：

| 選項 | 用途 |
|---|---|
| `--output PATH` | 寫到指定檔案，而不是預設資料夾。 |
| `--force` | 輸出檔案已存在時直接覆寫。 |
| `--dry-run` | 直接印出 Markdown，不寫入檔案。 |
| `--no-llm` | 不使用外部 LLM 產生摘要。 |

`doctor` 接受 `--quiet`，會隱藏檢查清單，只用結束代碼回報結果。

`scan` 與 `report` 有三條規則：

- `--days`、`--period`、`--since` 三者只能擇一使用。
- `--until` 只能搭配 `--since` 使用。
- `--verbose` 與 `--quiet` 不能同時使用。

## 統計期間

`last-week` 指的是設定時區底下上一個完整的日曆週，從星期一 00:00 開始，到下一個星期一 00:00 之前結束。

```bash
agent-worklog report --period last-week
```

用 `--days` 統計最近幾天的活動：

```bash
agent-worklog report --days 7
```

用 ISO 時間戳指定精確的起訖時間：

```bash
agent-worklog report \
  --since 2026-07-20T00:00:00+08:00 \
  --until 2026-07-27T00:00:00+08:00
```

你必須提供 `--period`、`--days` 或 `--since` 其中之一。若要使用 `--until`，就必須同時使用 `--since`。

## Subagent 工作階段

預設會包含 subagent 工作階段。每個 subagent 都會連結到它實際執行所在的 repository，所以在另一個 checkout 中工作的 subagent 會出現在那個 repository 底下。若只想統計根工作階段：

```bash
agent-worklog report --period last-week --root-only
```

`scan` 與 `report` 都接受 `--root-only`。

## Repository 分組

Agent Worklog 會逐一檢查每個工作階段，決定它屬於哪個 repository，並依下列順序判斷：

1. Git `origin` remote。
2. 由共用 Git 目錄雜湊產生的 ID。
3. OpenCode 專案 ID。
4. 由工作目錄雜湊產生的 ID。
5. 該工作階段專用的 unknown ID。

同一個 repository 的 SSH 與 HTTPS 位址會視為同一個 repository，不同分支也會被歸在一起。如果子工作階段在另一個 repository 中工作，它會留在那個 repository 底下。

## LLM 摘要

LLM 摘要是選用的。只有在下列條件全部成立時，Agent Worklog 才會連線到相容 OpenAI 的服務：

- 已開啟 LLM 支援。
- 沒有使用 `--no-llm`。
- 指定的環境變數中已設定 API 金鑰。

使用預設的 OpenAI 相容設定：

```bash
export OPENAI_API_KEY="..."
agent-worklog report --period last-week
```

LLM 請求包含的是挑選過的工作資訊，而不是完整逐字紀錄。Agent Worklog 在組出每個請求前，會先檢查工作階段資訊中常見的機密字串樣式。請求中仍可能包含 repository 與分支名稱、工作階段與活動 ID、目標、指令與檔名。

如果服務逾時、回傳 HTTP 429 或 5xx 錯誤，或回傳無效資料，Agent Worklog 會再重試一次。第二次仍失敗時，會改用不經 LLM 的方式產生摘要。使用 `--no-llm` 可以讓報告完全在你的電腦上產生。

## 使用量統計

每份報告都包含一個由 `opencode stats` 產生的使用量區塊，涵蓋模型、token 與工具。OpenCode 只回報「結束於現在」的期間，因此報告中顯示的期間會從報告期間的起點開始，一路延伸到報告產生的時間；它涵蓋報告期間，但範圍比較寬。如果沒有 `opencode stats`，Agent Worklog 會略過這個區塊，並在報告中加上警告。

## 輸出與檔案處理

用 `--output` 指定輸出檔案：

```bash
agent-worklog report \
  --period last-week \
  --no-llm \
  --output weekly.md
```

除非使用 `--force`，Agent Worklog 不會覆寫既有檔案：

```bash
agent-worklog report --period last-week --output weekly.md --force
```

用 `--dry-run` 預覽 Markdown，不寫入檔案：

```bash
agent-worklog report --period last-week --no-llm --dry-run
```

用 `--verbose` 顯示匯出與 LLM 備援的警告；用 `--quiet` 在報告成功後只顯示輸出路徑。

## 設定

Agent Worklog 透過環境變數進行設定。變數名稱以 `AGENT_WORKLOG_` 開頭，設定名稱的各層之間用 `__` 分隔。例如：

```bash
export AGENT_WORKLOG_REPORT__TIMEZONE="Asia/Taipei"
export AGENT_WORKLOG_REPORT__OUTPUT_DIRECTORY="reports"
export AGENT_WORKLOG_HARNESSES__OPENCODE__CLI__EXECUTABLE="opencode"
export AGENT_WORKLOG_LLM__MODEL="gpt-5-mini"
export AGENT_WORKLOG_LLM__BASE_URL="https://api.openai.com/v1/"
export AGENT_WORKLOG_LLM__ENABLED="false"
```

完整設定清單請見
[設定指南](https://github.com/mike840609/agent-worklog/blob/main/docs/configuration.md)。

## 隱私

Agent Worklog 使用 `--sanitize` 要求 OpenCode 匯出資料，並在產生報告或發出選用的 LLM 請求之前，檢查挑選過的工作階段資訊中常見的機密字串樣式。樣式檢查無法找出所有可能的機密資料。

報告中仍可能包含私人的目標、檔名、指令、工作描述，以及工作資料夾的完整路徑。這些路徑常常包含你的使用者名稱，以及客戶或雇主的名稱；機密字串檢查刻意保留它們，好讓報告能說明工作發生在哪裡。分享報告前請務必先檢查內容。

關於資料安全與目前的限制，詳見
[隱私與安全](https://github.com/mike840609/agent-worklog/blob/main/docs/privacy.md)。

## 失敗處理與結束代碼

如果某個工作階段無法匯出，Agent Worklog 會略過它並在報告中加上警告。如果所有工作階段都無法匯出，指令會直接以錯誤結束，而不會產生空白報告。

| 代碼 | 意義 |
|---:|---|
| 0 | 成功 |
| 2 | 指令選項無效 |
| 3 | 設定錯誤 |
| 4 | 沒有符合的活動 |
| 5 | OpenCode 或 Git 相依性錯誤 |
| 7 | 報告檔案錯誤 |

## 目前支援範圍與限制

- 目前只支援 OpenCode 這個 coding agent 工具。
- Agent Worklog 透過 OpenCode 命令列工具取得工作階段資料，不會直接讀取 SQLite 資料庫。
- 報告格式只有 Markdown。
- 使用量統計涵蓋的期間結束於報告產生的時間，並不會與報告期間完全一致。
- Agent Worklog 不會在多次執行之間保留快取，也沒有提供 `inspect` 指令。
- 較舊的工作階段若工作資料夾已被刪除，可能會使用備援 ID。
- Repository 分組使用的是產生報告當下可取得的 Git 資訊。
- 目前不支援 Codex 與 Claude Code。

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
