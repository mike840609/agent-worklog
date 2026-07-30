# Claude Code Adapter — Design Document

**Status:** Approved
**Date:** 2026-07-30
**Depends on:** [MVP Design](mvp-design.md) §9 Harness Source Abstraction
**Adds harness:** Claude Code (`claude-code`)

---

## 1. Executive Summary

在現有架構上新增 Claude Code 作為第二個 harness。`HarnessSessionSource`（`discover`/`load`
兩階段）與 canonical `AgentSession` 這層抽象已經足夠，**共用 pipeline 的核心邏輯不需要改**：
`RepositoryResolver`、`filter_session_to_period`、`hierarchy` 分組、`redactor`、summarizer、
renderer 全部沿用。

需要改的是四件事：CLI 目前寫死 OpenCode source、缺少 `--sanitize` 上游因此 adapter 必須自己
負責丟資料、usage 介面形狀是 OpenCode-shaped、以及幾處共用層對 harness 的滲漏。

第一版範圍：**一次執行只讀一個 harness**（`--harness` flag），不做多 harness 合併報告。

---

## 2. Goals

1. `agent-worklog scan --harness claude-code` 與 `report --harness claude-code` 可用。
2. Claude Code session 依 Git repository 分組，與 OpenCode 的分組結果格式一致。
3. `--root-only`、`--days`/`--period`/`--since`、`--dry-run` 等既有 option 行為不變。
4. 報告的 usage 區段從 session 內的 `message.usage` 產生，落在報告期間而非結束於現在的窗口。
   期間內每一筆 `message.usage` 都要計入，包含只有 `thinking` block、不產生 activity 的
   record（實測 4,227 筆帶 usage 的 assistant record 中有 1,171 筆如此，佔 25% output
   token）；其用量由同一 model 相鄰的 activity 帶入。
5. 現有 OpenCode 使用者行為零改變（`--harness` 預設 `opencode`）。

## 3. Non-Goals

- 同一份報告合併多個 harness。
- 實作 MVP design §9.3 的 `HarnessCapabilities`。
- 用 session 記錄的 `gitBranch` 取代報告產生時現撈的 branch。
- 結構化 usage model（`UsageSummary`）。
- Codex adapter。

---

## 4. Claude Code 資料形狀（實測）

以下皆為 2026-07-30 在 Claude Code `2.1.220` 的本機資料上實測，供實作者參考。

### 4.1 儲存位置

```
~/.claude/projects/
  <path-slug>/                         # 例：-Users-chuntsai-Projects-agent-worklog
    <session-uuid>.jsonl               # root session
    <session-uuid>/
      subagents/
        agent-<id>.jsonl               # subagent transcript
        agent-<id>.meta.json           # {agentType, description, toolUseId, spawnDepth, model}
```

Claude Code **沒有 export 指令**（`claude` 的 subcommands 只有 agents / auth / auto-mode /
doctor / gateway / install / mcp / plugin / project / setup-token / ultrareview / update）。
資料只能直讀檔案。這與 OpenCode 透過 `opencode export --sanitize` 取得資料的路徑不同，
是本設計最重要的差異來源。

單一 session 檔案可達數 MB（實測最大 2.9 MB）。

### 4.2 Record 種類

每行一個 JSON object，以 `type` 區分。實測分佈（單一 session）：

| `type` | 用途 | 本設計如何處理 |
|---|---|---|
| `user` | 使用者輸入、tool_result 回填、hook 注入、system-reminder | **條件性採用**，見 §6.2 |
| `assistant` | 模型回應（`text` / `thinking` / `tool_use` blocks） | 採用 |
| `attachment` | hook stdout、檔案附件 | 丟棄 |
| `file-history-snapshot` | 檔案快照 | 丟棄 |
| `ai-title` | session 標題（`aiTitle`） | **不產生 activity**，僅取值作為 session `title`（§6.4） |
| `last-prompt` / `mode` / `permission-mode` / `bridge-session` / `queue-operation` | session 狀態 | 丟棄 |

### 4.3 共用欄位

`user` 與 `assistant` record 都帶：`uuid`、`parentUuid`、`timestamp`（ISO 8601 UTC）、
`cwd`、`gitBranch`、`sessionId`、`version`、`isSidechain`、`userType`、`entrypoint`。

比 OpenCode 更豐富：`cwd` 與 `gitBranch` 逐筆記錄，不需要從 export metadata 推斷。

### 4.4 Token usage

`assistant` record 的 `message.usage` 提供 per-request 用量：

```json
{
  "input_tokens": 2,
  "cache_creation_input_tokens": 35868,
  "cache_read_input_tokens": 0,
  "output_tokens": 308,
  "service_tier": "standard",
  "cache_creation": {"ephemeral_1h_input_tokens": 35868, "ephemeral_5m_input_tokens": 0}
}
```

`message.model` 提供模型名稱。語意為 **incremental**（per-request，非累計）。

這比 OpenCode 好：`opencode stats` 只接受「結束於現在」的滾動窗口，所以報告必須把窗口撐寬
並加 warning；Claude Code 的用量直接綁在落在報告期間的 activity 上。

### 4.5 `toolUseResult` 沒有 exit code

Bash 工具結果的欄位只有：

```
{interrupted, isImage, noOutputExpected, stderr, stdout}
```

**沒有任何 exit code 欄位。** 這代表 `extraction/pipeline.py` 的 `_exit_code()` 在 Claude Code
資料上永遠回 `None`，於是兩條 evidence 會消失：`nonzero_exit_code` → `errors`、
`successful_verification_command` → `outcomes`（「Verification passed: pytest」）。
處理方式見 §7。

### 4.6 Session 內的 cwd / branch 穩定性

實測 70 個帶 `cwd` 的 session：

- **2 個** session 橫跨多個 `cwd`（皆為 git worktree 情境）。
- **17 個** session 橫跨多個 `gitBranch`（單一 session 最多 15 個 branch）。

`AgentSession.working_directory` 是單一欄位，因此 adapter 必須選一個代表值（見 §6.4）。
branch 的多值問題屬於既有設計限制（README 已載明「Repository grouping uses the Git
information available when the report is created」），列為 Non-Goal。

### 4.7 `isSidechain`

欄位存在於 record schema，但實測 72 個檔案中**全部為 `false`**。subagent 是靠
`subagents/` 子目錄區分，不是靠這個欄位。本設計不依賴 `isSidechain`。

---

## 5. 架構決策

### 5.1 一次一個 harness

`ScanService.__init__` 的 `source: HarnessSessionSource` 維持單一。多 harness 合併報告需要
`list[HarnessSessionSource]`、跨 harness 的 repository 合併、以及兩種 usage 形狀並存，
第一版不做。

CLI 新增：

```
--harness {opencode,claude-code}    # 預設 opencode
```

預設值為 `opencode` 確保現有使用者零 breaking change。

### 5.2 新增與搬動的檔案

```
src/agent_worklog/harnesses/claude_code/
  __init__.py
  source.py      # ClaudeCodeFileSource(HarnessSessionSource)
  mapper.py      # JSONL records → AgentSession
  usage.py       # TokenUsage 聚合 → markdown 表格字串

src/agent_worklog/process.py      # 由 harnesses/opencode/cli_runner.py 搬移
```

搬動 `cli_runner.py` 的原因：`repositories/resolver.py:9` 與 `services/doctor.py:7` 目前從
`harnesses.opencode.cli_runner` import `CommandResult`，是共用層 import harness 內部實作的
滲漏。搬到 `agent_worklog/process.py` 後兩者改 import 中性模組，`harnesses/opencode/` 也一併
改用新位置。

---

## 6. Claude Code Source

### 6.1 `discover`

```python
class ClaudeCodeFileSource(HarnessSessionSource):
    def __init__(
        self,
        *,
        projects_directory: Path,
        root_only: bool = False,
    ) -> None: ...
```

流程：

1. Glob `{projects_directory}/*/*.jsonl` 取得 root session。
2. `root_only` 為 false 時，額外 glob `{projects_directory}/*/*/subagents/*.jsonl`；
   `parent_session_id` 取 `subagents/` 的上層目錄名（即 parent session UUID）。
   同名 `.meta.json` 的 `description` 可作為 `title`。
3. **時間 prefilter**：檔案 `mtime >= period.since` 才納入。這是便宜的第一道過濾。
4. `updated_at` = 檔案 mtime；`created_at` = 第一筆帶 `timestamp` 的 record。
5. 精確的期間過濾**不在 discover 做**，交給既有的 `filter_session_to_period`（`load` 之後）。
   discover/load 兩階段設計本來就是為此，不需要新機制。

`projects_directory` 預設 `~/.claude/projects`，可透過
`AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__PROJECTS_DIRECTORY` 覆寫。

`SessionDescriptor.harness` 一律為 `"claude-code"`。

### 6.2 `load` — 刻意丟資料

**這是本設計的安全核心。** OpenCode 有 `export --sanitize` 作為第一層防線，
`security/redactor.py`（61 行、pattern-based）是第二層。Claude Code 只剩第二層，因此
adapter 必須在 map 階段就刻意丟資料，而不是全部映射後倚賴 redaction。

只處理 `type` 為 `user` / `assistant` 的 record，其餘全部丟棄（§4.2）。

**`user` record 的採用條件（不可省略）：**

```
origin.kind == "human"  AND  not isMeta
```

Claude Code 的 `type: "user"` 同時裝載 tool_result 回填、hook 注入內容、
`<system-reminder>` 區塊。若不過濾，hook stdout 與 skill 說明文字會被
`extraction/pipeline.py` 當成使用者目標寫進 `goals`，污染整份報告。

符合條件者 → `ActivityType.USER_MESSAGE`。

**版本下限：`origin` 欄位大約自 Claude Code `2.1.187` 起才寫入。** 更早版本寫出的
transcript 完全沒有這個 key，因此上述條件會濾掉該檔案的**每一筆** user message——實測 72 個
近期 root session 中有 10 個如此，其中一個帶 188 筆 assistant record，卻產生零個 goal。
`discover` 的 `mtime >= period.since` prefilter 代表一份被 resume 的舊 transcript 在一般的
週報執行中就會被讀到。

這個條件**不放寬**：任何啟發式的 fallback 都可能把它本來要擋掉的 hook 與 system-reminder
噪音重新放進來。改為讓損失可見——`services/scan.py` 在一個 session 有 assistant activity
但沒有任何 `USER_MESSAGE` 時發出 warning，形狀比照既有的 timestamp-less activity warning。

**該 warning 只針對 root session。** subagent 是由 parent 寫的 prompt 產生的，本來就不會有
人類 prompt：實測一週內 44 個 subagent transcript **全部**沒有，而 root session 是 10 個裡
有 1 個。若不排除 subagent，唯一有意義的那一筆會被 44 筆噪音埋掉。

**`assistant` record 的 `message.content[]`：**

| block `type` | 處理 |
|---|---|
| `text` | → `ASSISTANT_MESSAGE`，`content` = `text` |
| `tool_use` | → `TOOL_CALL`，`tool_name` = `name`，`tool_call_id` = `id`，`content` 見下 |
| `thinking` | 丟棄 |

`tool_use` 的 `content` 取值優先序：

1. `input.command`（Bash）
2. `input.file_path`（Edit / Write / Read / NotebookEdit）
3. `json.dumps(input)` 截斷至上限長度

**`toolUseResult` 只萃取兩個布林值進 `metadata`：**

```python
metadata = {
    "stderr_empty": not (result.get("stderr") or "").strip(),
    "interrupted": bool(result.get("interrupted")),
}
```

`stdout` 與 `stderr` 的**文字內容一律不進入 `AgentSession` 任何欄位**。這兩個欄位裝的是完整
檔案內容、環境變數 dump、以及 hook 輸出，是本 harness 最大的洩漏面。

布林值足夠支撐 §7 的 heuristic，因為 evidence 的 `text` 用的是**指令本身**而不是 stderr
（見 `extraction/pipeline.py:141`）。

### 6.3 Activity ID

`activity_id` = `f"{record.uuid}:{block_index}"`。record 的 `uuid` 保證存在且唯一，
與 OpenCode mapper 的 `{message_id}:{part_index}` 形狀一致，report 的 provenance 區段
不需要改。

### 6.4 Session 層級欄位

| 欄位 | 取值 |
|---|---|
| `harness` | `"claude-code"` |
| `session_id` | 檔名 stem（root）或 `agent-<id>`（subagent） |
| `parent_session_id` | subagent 為上層目錄名，root 為 `None` |
| `title` | `ai-title` record 的 `aiTitle`，或 `.meta.json` 的 `description` |
| `created_at` / `updated_at` | 第一筆 / 最後一筆帶 `timestamp` 的 record |
| `working_directory` | **最後一筆 `cwd`**（§4.6：70 個 session 中僅 2 個跨 cwd，皆為 worktree） |
| `project_id_hint` | 上層 path-slug 目錄名 |
| `token_usage` | `TokenUsage(semantics=INCREMENTAL, ...)`，累加所有 `message.usage` |

`token_usage` 是 `TokenUsage` model 首次被實際填值——OpenCode mapper 目前寫死
`UsageSemantics.UNKNOWN`。

---

## 7. Extraction：exit code 缺口

§4.5 說明 Claude Code 沒有 exit code。**不能因此改用 stderr 推論「通過」**：實測 113 筆這類
推論中，96 筆（85%）來自自己重導 stderr 的指令（`2>&1`、`2>/dev/null`），`stderr_empty` 為真
是它自己造成的，訊號量為零；另有 22 筆（19%）可證明為假，包含 stdout 出現 `FAILED` 的
`pytest`，以及回報 `E501` 的 `ruff check .`。

因此 `extraction/pipeline.py` 的 command 分支在 `_exit_code()` 回 `None` 且 `metadata` 有
`stderr_empty` 時，只記錄「指令跑過」，不記錄結果：

| 條件 | 產出 | status | confidence | `extraction_method` |
|---|---|---|---|---|
| 指令重導 stderr（`2>`、`&>`、`\|&`） | **無**（指令本身仍留在 `commands`） | — | — | — |
| `stderr_empty` 且 `not interrupted` 且 `is_verification_command` | `outcomes`（`Ran verification command: <cmd>`） | `UNKNOWN` | `MEDIUM` | `stderr_heuristic` |
| `not stderr_empty` | **無** | — | — | — |

最後一列同樣是實測的結果：**stderr 非空不代表失敗**。`git` 成功時也一直往 stderr 寫東西，
所以這條規則在真實逐字紀錄上產出了 31 筆 `git stash`、`cd … && uv sync` 之類的噪音——報告
沒有任何區塊會渲染它們，但它們全都進了對外的 LLM 請求。只有觀測到的 exit code 才值得記為失敗。

「Verification passed」這個字串只保留給 OpenCode 的 exit-code 路徑
（`successful_verification_command`，`HIGH`），那條路徑觀測到真實的 exit code。

`extraction/rules.py` 的 tool name 集合**不需要修改**。`pipeline.py` 已對 `tool_name`
做 `casefold()`，因此 Claude Code 的 `Edit` → `edit`、`Bash` → `bash`、`Write` → `write`
直接命中現有集合。

### 7.1 `RuleBasedSummarizer`：未觀測到的結果放在 In Progress

`summarizers/rule_based.py` 的 `_completed()` 只收 `status == COMPLETED`，因此上述
`UNKNOWN` 項目不會（也不該）出現在 `#### Completed`——沒有觀測到的結果不算完成。但它們也
不能就這樣消失，所以 `_unobserved()` 把 `status == UNKNOWN` 且 `confidence == MEDIUM` 的
outcome 併入 `in_progress`，在報告中以 `#### In Progress` 呈現。

`LOW`（`assistant_claim`）在兩個區段都維持排除：模型自稱完成不是證據。

`_completed()` 對 `MEDIUM` 的 `" (inferred)"` 後綴保留，作為 summarizer 對「推論得到的
COMPLETED evidence」的映射契約；目前沒有 extractor 產生這種組合。

---

## 8. Usage 區段

`harnesses/claude_code/usage.py` 將載入的 sessions 的 `TokenUsage` 依 `model` 聚合，
輸出 markdown 表格字串塞入 `WorklogReport.usage_text`：

```markdown
| Model | Input | Output | Cache read |
|---|---:|---:|---:|
| claude-opus-5 | 12,480 | 84,201 | 1,204,880 |
```

`usage_days` 傳 `None`。`templates/worklog.md.j2:70` 已有 `{% if report.usage_days %}`
守衛，因此「窗口比報告期間寬」那段 caveat 會自動省略——**template 零改動**。

**介面調整（一處）：** `ReportService` 的 `usage_provider` 目前是
`Callable[[], str]`，在 scan 完成後才被呼叫（`services/report.py:108`）。Claude Code 的
usage 需要 session 資料，因此簽章改為：

```python
usage_provider: Callable[[ScanResult], str] | None = None
```

OpenCode 的 provider 忽略該參數。

---

## 9. Doctor

`doctor` 依 `--harness` 分派檢查項：

| harness | 檢查項 |
|---|---|
| `opencode` | `opencode --version`、`opencode db path`、`git --version`（現狀不變） |
| `claude-code` | `projects_directory` 存在且可讀、`git --version` |

Claude Code 路徑不執行任何外部 harness CLI。

---

## 10. 共用層去 OpenCode 化

| 位置 | 現狀 | 改為 |
|---|---|---|
| `repositories/resolver.py:9` | import `harnesses.opencode.cli_runner` | import `agent_worklog.process` |
| `services/doctor.py:7` | 同上 | 同上 |
| `services/scan.py:91` | `"all OpenCode session exports failed"` | 帶 harness 名的訊息 |
| `services/report.py:112` | `"OpenCode usage statistics unavailable"` | 同上 |
| `cli.py:225,282` | `"no OpenCode activity found..."` | 同上 |
| `config.py:24` `HarnessSettings` | 僅 `opencode` 欄位 | 加 `claude_code: ClaudeCodeSettings` |
| `cli.py:101` `_build_scan_service` | 直接 new `OpenCodeCliSource` | 依 `--harness` 分派 |

新增設定：

```python
class ClaudeCodeSettings(BaseModel):
    enabled: bool = True
    projects_directory: Path = Path.home() / ".claude" / "projects"
```

---

## 11. 測試

### 11.1 Adapter 單元測試

以手寫的小型 fixture JSONL 驅動，內容刻意包含：

- 一筆 `attachment` record（hook stdout）
- 一筆 `type: "user"` 但內容為 `<system-reminder>` 且 `isMeta: true` 的 record
- 一筆 `type: "user"` 且 `origin.kind == "human"` 的真實 prompt
- 一筆 `assistant` record 含 `text` + `thinking` + `tool_use` blocks
- 一筆帶 `toolUseResult`（含非空 `stderr` 與敏感 `stdout`）的 record
- 多個 `cwd` 與多個 `gitBranch`

必要斷言：

1. hook stdout 與 system-reminder 內容**不出現在** `goals`。
2. **`stdout` / `stderr` 的文字不出現在 `AgentSession` 的任何欄位**（序列化整個
   model 後做 substring 檢查）。這是安全邊界，不可省略。
3. `thinking` 內容不出現在任何 activity。
4. `working_directory` 等於最後一筆 `cwd`。
5. `token_usage.semantics == INCREMENTAL` 且數值為所有 `message.usage` 的總和。

### 11.2 Extraction 測試

MEDIUM heuristic 的兩條路徑各一個 case：`stderr_empty` + verification command → MEDIUM
outcome；非空 stderr → MEDIUM error。同時斷言 OpenCode 的 exit-code 路徑仍產出 HIGH。

### 11.3 整合測試

`scan --harness claude-code` 與 `report --harness claude-code --no-llm --dry-run`
跑在 fixture projects 目錄上，斷言 repository 分組與 usage 表格出現在輸出中。
`--root-only` 斷言 `subagents/` 底下的 session 被排除。

### 11.4 迴歸

現有 OpenCode 測試全數不修改即應通過（`--harness` 預設 `opencode`）。
`tests/unit/test_documentation.py` 會驗證 README 內容，因此 §12 的文件更新必須與它同步。

---

## 12. 文件更新

- `README.md` / `README.zh-TW.md`：Capabilities、Requirements、Command reference
  （新增 `--harness`）、Current support and limits（移除「Claude Code are not currently
  supported」）。
- `docs/configuration.md`：新增 `AGENT_WORKLOG_HARNESSES__CLAUDE_CODE__*`。
- `docs/privacy.md`：**必須更新。** 目前的敘述建立在 `opencode export --sanitize` 之上；
  Claude Code 路徑直讀本機檔案，沒有 harness 端的 sanitize，防線是 §6.2 的刻意丟資料
  加上 `security/redactor.py`。這個差異必須向使用者明確說明。
- `CHANGELOG.md`。

---

## 13. 已知限制

1. Claude Code transcript 不提供驗證指令的 observed exit code，因此報告不會宣稱驗證指令通過或失敗。
   stderr 為空、沒有重導且未中斷的驗證指令只會記為 `UNKNOWN`；中斷的指令不會產生
   outcome，stderr 非空也不會單獨視為失敗，因為 Git 等工具成功時仍可能寫入 stderr。
2. 跨 cwd 的 session（worktree 情境）只會被歸到最後一個 cwd 對應的 repository。
3. 單一 session 橫跨多 branch 時，報告顯示的是產生報告當下 `git branch --show-current`
   的結果，而非 session 當時實際的 branch。
4. Session 檔案可達數 MB，`load` 會將整個 transcript 讀進記憶體後才丟資料。
   `discover` 的 mtime prefilter 是唯一的成本控制手段。
5. JSONL record schema 屬 Claude Code 內部實作，可能隨版本變動。實測基準為 `2.1.220`。
6. Claude Code `2.1.187` 之前寫出的 transcript 沒有 `origin` 欄位，該 session 不會產生任何
   goal（§6.2）。`scan` 與報告的 warning 區段會列出這些 session。
