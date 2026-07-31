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

Agent Worklog 支援 OpenCode、Claude Code 與 Codex，可以：

- 找出所有專案的 OpenCode 工作階段，不論你現在位於哪個資料夾。
- 直接從 `~/.claude/projects` 讀取 Claude Code 工作階段，包含 subagent 逐字紀錄。
- 直接從 `~/.codex` 讀取 Codex 工作階段，若存在 Codex 狀態資料庫則優先使用，否則改為掃描 rollout 檔案。
- 依照最近幾天、某一個日曆週，或指定的日期區間挑選工作階段。
- OpenCode 專屬：使用 `opencode export --sanitize` 匯出工作階段。Claude Code 與 Codex 都沒有匯出指令，因此沒有對應的步驟。
- 把屬於同一個 repository 的 Git worktree 歸為同一組。
- 讓子工作階段（child session）連結到正確的 repository。
- 使用 `--root-only` 排除 subagent 工作階段，只保留根工作階段。
- 在報告中列出每個 repository 的工作階段標題與工作資料夾。
- 依模型彙整 token 使用量：OpenCode 取自 `opencode stats`，Claude Code 與 Codex 則取自工作階段本身記錄的計數。
- 附上來源活動 ID 與信心程度作為佐證資訊。
- 在產生報告或送資料給選用的 LLM 之前，先檢查工作階段資訊中常見的機密字串樣式。
- 某個工作階段讀取失敗時仍會繼續執行，並在報告中加上警告。
- 在 POSIX 系統上，以僅擁有者可讀寫的 `0600` 權限寫出報告。

## 系統需求

使用 `--harness opencode`（預設值）時：

- Python 3.11 以上
- 可以用 `opencode` 執行的 OpenCode
- 支援 `opencode db` 與 `opencode export --sanitize` 的 OpenCode 版本
- 可以用 `git` 執行的 Git

使用 `--harness claude-code` 時：

- Python 3.11 以上
- 可以用 `git` 執行的 Git
- 一個可讀取的 `~/.claude/projects` 資料夾（或由
  `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` 設定的資料夾）

不需要安裝 Claude Code 命令列工具；Agent Worklog 會直接讀取工作階段的逐字紀錄檔案。

使用 `--harness codex` 時：

- Python 3.11 以上
- 可以用 `git` 執行的 Git
- 一個可讀取的 `~/.codex` 資料夾（或由
  `AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY` 設定的資料夾）

不需要安裝 Codex 命令列工具；Agent Worklog 會直接讀取狀態資料庫或 rollout 檔案。

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

上面三個指令預設都是 `--harness opencode`。要用 Claude Code 或 Codex 的話，各自加上
`--harness claude-code` 或 `--harness codex` 即可，不需要安裝 OpenCode：

```bash
agent-worklog doctor --harness claude-code
agent-worklog report --harness claude-code --period last-week --no-llm
agent-worklog doctor --harness codex
agent-worklog report --harness codex --period last-week --no-llm
```

## 指令參考

| 指令 | 用途 |
|---|---|
| `doctor` | 檢查目前選用的 harness 與 `git` 是否就緒。 |
| `scan` | 顯示哪些工作階段落在指定期間內，以及它們如何分組成 repository。 |
| `report` | 產生指定期間的 Markdown 報告。 |

`scan` 與 `report` 共用這些選項：

| 選項 | 用途 |
|---|---|
| `--days N` | 統計到現在為止的最近 N 天。 |
| `--period last-week` | 統計上一個完整的日曆週。`last-week` 是唯一可用的值。 |
| `--since ISO` | 以指定時間作為期間起點。 |
| `--until ISO` | 以指定時間作為期間終點，必須搭配 `--since`。 |
| `--harness NAME` | 讀取工作階段所用的 harness：`opencode`（預設）、`claude-code` 或 `codex`。 |
| `--root-only` | 排除 subagent 工作階段。 |
| `--verbose` | 同時顯示匯出、備援與 LLM 相關的警告。 |
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
| `--no-llm` | 不使用外部 LLM 產生摘要。 |

`doctor` 也接受 `--harness NAME` 與 `--quiet`。`--quiet` 會隱藏檢查清單，只用結束代碼回報結果。
使用 `--harness claude-code` 時，`doctor` 會改為檢查設定的 `~/.claude/projects` 資料夾是否存在且可讀，而不是檢查 `opencode` 執行檔與資料庫。使用 `--harness codex` 時，`doctor` 會檢查設定的 `~/.codex` 資料夾是否存在且可讀，並回報將採用哪一種探索方式：依名稱顯示的狀態資料庫，或在資料庫不存在時顯示 `directory scan`。

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
3. harness 的專案 ID——OpenCode 的專案 ID，或 Claude Code 用來存放逐字紀錄的各專案資料夾名稱。
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

使用 `--harness opencode` 時，每份報告都包含一個由 `opencode stats` 產生的使用量區塊，涵蓋模型、token 與工具。OpenCode 只回報「結束於現在」的期間，因此報告中顯示的期間會從報告期間的起點開始，一路延伸到報告產生的時間；它涵蓋報告期間，但範圍比較寬。如果沒有 `opencode stats`，Agent Worklog 會略過這個區塊，並在報告中加上警告。

使用 `--harness claude-code` 或 `--harness codex` 時，使用量區塊是根據工作階段本身記錄的 token 計數產生的，因此涵蓋的是報告期間，而不是一段結束於報告產生時間的窗口；上述「範圍比較寬」的但書並不適用。期間內的每一個模型 turn 都會被計入，包含只產生內部推理（thinking）的 turn，它們的 token 由相鄰那筆有記錄的活動一併帶入。這也是它唯一的誤差來源：正好落在期間邊界上的 turn，可能會被算到邊界的另一側。就 Codex 而言，這個計數本身就是 Codex 針對每次 API 請求的完整輸入所回報的數字，而不是相異 token 的數量。

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

Agent Worklog 使用 `--sanitize` 要求 OpenCode 匯出資料。Claude Code 沒有匯出指令，所以使用 `--harness claude-code` 時，Agent Worklog 會直接讀取 `~/.claude/projects` 底下的逐字紀錄，改為仰賴 mapper 只保留人類提示、助理文字訊息、工具名稱，以及每次工具呼叫（若有的話）的一組指令或路徑。如果一次工具呼叫兩者都沒有——例如 WebFetch 的 `url`、WebSearch 的 `query`、TodoWrite 整份的 `todos` 清單，或一般的 MCP 工具呼叫——就會改成把整個輸入序列化成 JSON，並截斷到 200 個字元。工具原始的 `stdout`／`stderr`、思考內容與 hook 輸出，都會在資料進入報告或 LLM 請求之前被捨棄。

Codex 同樣沒有匯出指令，所以使用 `--harness codex` 時會直接讀取 rollout JSONL 檔案。mapper 會直接捨棄兩種內容，而不是留到後面才處理：每一筆 `patch_apply_end` 變更的 `content` 欄位（裡面裝著該次修補寫入的整份檔案），以及每一次 `exec` 呼叫的輸入（一段任意的 JavaScript 程式）。只有被改動檔案的路徑與工具名稱會保留下來。指令只會從 `exec_command` 保留，因為它的參數會用一個欄位指名該指令。

接著，三種 harness 進入報告的每一筆佐證資訊（evidence）都會被截斷到 300 個字元，並在截斷處標上 `…`。這道長度上限的作用，是攔下像 `cat > design.md <<'EOF' … EOF` 這種 heredoc——它把整個檔案內容包在同一個指令字串裡——避免整段內容被複製進報告或 LLM 請求。機密字串樣式檢查做不到這件事：一份設計文件或事件說明裡沒有任何金鑰樣式，只有長度上限能把它移除。

三種 harness 都會在產生報告或發出選用的 LLM 請求之前，經過常見的機密字串樣式檢查。樣式檢查無法找出所有可能的機密資料。

報告中仍可能包含私人的目標、檔名、指令、工作描述，以及工作資料夾的完整路徑。這些路徑常常包含你的使用者名稱，以及客戶或雇主的名稱；機密字串檢查刻意保留它們，好讓報告能說明工作發生在哪裡。分享報告前請務必先檢查內容。

關於資料安全與目前的限制，詳見
[隱私與安全](https://github.com/mike840609/agent-worklog/blob/main/docs/privacy.md)。

## 失敗處理與結束代碼

如果某個工作階段無法讀取，Agent Worklog 會略過它並在報告中加上警告——OpenCode 是 `opencode export` 失敗，Claude Code 或 Codex 則是逐字紀錄檔案無法讀取。如果所有工作階段都無法讀取，指令會直接以錯誤結束，而不會產生空白報告。

| 代碼 | 意義 |
|---:|---|
| 0 | 成功 |
| 2 | 指令選項無效 |
| 3 | 設定錯誤 |
| 4 | 沒有符合的活動 |
| 5 | Harness 或 Git 相依性錯誤 |
| 7 | 報告檔案錯誤 |

## 目前支援範圍與限制

- 目前支援的 coding agent 工具是 OpenCode、Claude Code 與 Codex；用 `--harness` 挑選其中一個。
- 使用 `--harness opencode` 時，Agent Worklog 透過 OpenCode 命令列工具取得工作階段資料，不會直接讀取 SQLite 資料庫。
- 報告格式只有 Markdown。
- 使用量的期間但書只適用於 OpenCode：`opencode stats` 涵蓋的期間結束於報告產生的時間，範圍比報告期間寬。Claude Code 與 Codex 的使用量都是根據工作階段本身產生的，涵蓋的就是報告期間，誤差不超過期間兩端各一個模型 turn。
- Agent Worklog 不會在多次執行之間保留快取，也沒有提供 `inspect` 指令。
- 較舊的 OpenCode 工作階段若工作資料夾已被刪除，可能會使用備援 ID。
- Repository 分組使用的是產生報告當下可取得的 Git 資訊。
- Claude Code 工作階段沒有結束代碼（exit code），因此 Claude Code 的報告不會聲稱任何測試或 lint 指令通過或失敗。stderr 為空的驗證指令會以 `Ran verification command: <command>` 列在「In Progress」底下；若指令自己重導了 stderr（`2>`、`&>`、`|&`），則完全不產生任何結果判定，因為這種情況下 stderr 為空並不代表任何事。stderr 非空同樣不視為失敗——Git 成功時也會往 stderr 寫東西。只有 OpenCode 有真正的 exit code，才會把驗證結果報告為通過。Codex 既沒有設定 exit code，也沒有這個 stderr 訊號，因此同樣不會套用這項推論規則。
- 若一個 Claude Code 工作階段橫跨多個工作目錄，會被歸到最後一個工作目錄底下。
- Codex 的報告會顯示目標、變更過的檔案與 token 使用量，但不會列出指令。透過 `exec_command` 記錄的指令只會進入選用的 LLM 摘要，不會出現在報告的其他地方；使用 `--no-llm` 時，報告裡完全不會有它的蹤跡。
- 從 Codex 的 `exec` 工具內執行的指令，甚至連這一步都不會被記錄下來。`exec` 接受的是一段 JavaScript 程式，而不是指令，因此沒有指令可以記錄。
- 沒有任何 Codex 報告會聲稱某個指令成功或失敗。Codex 只在自由格式的工具輸出裡記錄結束代碼（exit code），而且格式不只一種，因此只有 `patch_apply_end` 結構化的 `success` 欄位會被採信——而它回報的是檔案變更，不是驗證結果。
- Codex 的使用量計算的是每一次 API 請求的完整輸入，這也是 Codex 本身回報的數字，並不是相異 token 的數量。
- 當找不到可讀取的 Codex 狀態資料庫、Agent Worklog 改為掃描 rollout 檔案時，工作階段標題會遺失：rollout 檔案只帶有 `agent_nickname`，從來沒有 `title`，`title` 只存在於狀態資料庫中。
- 附帶附件送出的 Codex 訊息——瀏覽器上下文、提及的檔案、shell 指令與其輸出、slash 指令、背景工作通知，或是續接摘要——不會產生任何目標（goal）。Agent Worklog 無法在不解析這種未有文件記載的格式的情況下，從整個附件包裹中分辨出真正的請求，因此寧可漏掉這個目標，也不要把它歸錯對象。

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
