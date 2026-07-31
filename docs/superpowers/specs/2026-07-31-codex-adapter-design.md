# Codex Adapter — Design Document

**Status:** Approved
**Date:** 2026-07-31
**Depends on:** [MVP Design](../../mvp-design.md) §9 Harness Source Abstraction,
[Claude Code Adapter](../../claude-code-adapter-design.md)
**Adds harness:** Codex (`codex`)

---

## 1. Executive Summary

新增 Codex 作為第三個 harness。與 Claude Code adapter 相同，`HarnessSessionSource`
（`discover`/`load` 兩階段）與 canonical `AgentSession` 這層抽象已經足夠，**共用 pipeline 不需要
修改**：`RepositoryResolver`、`filter_session_to_period`、`hierarchy`、`redactor`、summarizer、
renderer 全部沿用，`extraction/pipeline.py` 一行都不改。

Codex 與前兩個 harness 的關鍵差異是**它有一個現成的 session 索引**。
`~/.codex/state_*.sqlite` 的 `threads` 表已經記錄了 id、rollout 檔案路徑、cwd、title、時間戳、
token 總量、model、`thread_source`，另有 `thread_spawn_edges` 表記錄 parent/child。這讓
discovery 變成一次 SQL 查詢，不必為了決定「這個 session 在不在報告期間」而開啟數百個檔案。

第一版範圍：一次執行只讀一個 harness（`--harness codex`），不做多 harness 合併報告。

---

## 2. Goals

1. `agent-worklog doctor|scan|report --harness codex` 可用。
2. Codex session 依 Git repository 分組，輸出格式與既有兩個 harness 一致。
3. `--root-only`、`--days`/`--period`/`--since`/`--until`、`--dry-run`、`--quiet`、`--verbose`
   行為不變。
4. Usage 區段從 session 內記錄的 token 計數產生，涵蓋報告期間而非結束於現在的窗口。
5. 沒有 `state_*.sqlite` 時，adapter 退回掃描 rollout 檔案目錄，功能等價。
6. 現有 OpenCode 與 Claude Code 使用者行為零改變（`--harness` 預設仍為 `opencode`）。

## 3. Non-Goals

- 同一份報告合併多個 harness。
- 從 Codex 記錄中宣稱任何命令「通過」或「失敗」（見 §6.3）。
- 解析 `exec` 工具內的 JavaScript 以取得其中執行的命令（見 §6.4）。
- 用 `threads.git_branch` / `git_origin_url` 取代報告產生時現撈的 Git 資訊。
- 實作 MVP design §9.3 的 `HarnessCapabilities`。
- 在 `cli.py` 引入 harness registry 抽象（見 §8.2）。

---

## 4. Codex 資料形狀（實測）

以下皆為 2026-07-31 在本機 Codex 資料上實測，樣本為 `~/.codex/sessions/`（238 個 rollout 檔案）
與 `~/.codex/archived_sessions/`（174 個），合計 412 個檔案、411 筆 threads。
CLI 版本範圍 `0.144.0`–`0.146.0-alpha.3.1`。

### 4.1 儲存位置

```
~/.codex/
  state_5.sqlite                                   # session 索引；檔名帶版本號
  state_5.sqlite-wal, state_5.sqlite-shm           # WAL 模式
  sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl    # 活躍 session transcript
  archived_sessions/rollout-<ts>-<uuid>.jsonl      # 封存 session transcript
```

`state_5.sqlite` 的 `5` 是 schema 版本，Codex 升級時會出現 `state_6.sqlite`。實作必須 glob
`state_*.sqlite` 並取數字後綴最大者，不可寫死。

### 4.2 `threads` 表

實測 411 筆，其中 `archived=1` 有 174 筆。**411 筆的 `rollout_path` 全部指向存在的檔案**
（archived 的指向 `archived_sessions/`），也就是索引與磁碟一致，無孤兒列。

| 欄位 | 型別 | 用途 |
|---|---|---|
| `id` | TEXT | `SessionDescriptor.session_id` |
| `rollout_path` | TEXT | `source_location` |
| `created_at` / `updated_at` | INTEGER | **unix 秒**（另有 `created_at_ms` / `updated_at_ms`，不使用） |
| `cwd` | TEXT | `working_directory_hint` |
| `title` | TEXT | `title`；subagent 常為空字串 |
| `agent_nickname` | TEXT | `title` 為空時的替代（實測值如 `Ampere`、`Gibbs`） |
| `thread_source` | TEXT | 用於 `--root-only`。實測值：`subagent` 293、`user` 56、NULL 64、`automation` 4、`system` 1、`realtime_voice` 1 — 可為 NULL，且不只兩種值 |
| `model` | TEXT | 不使用，改用 `turn_context.model`（見 §6.5） |
| `tokens_used` | INTEGER | 不使用，改用 rollout 內的差值（見 §6.5） |
| `archived` | INTEGER | **不用於過濾**（見 §5.3） |
| `git_branch` / `git_origin_url` / `git_sha` | TEXT | 不使用（見 §3 Non-Goals） |

`thread_spawn_edges(parent_thread_id, child_thread_id, status)` 實測 277 筆，提供
`parent_session_id`。

### 4.3 Rollout JSONL 記錄型別

每行一個 JSON 物件，外層 `{"timestamp", "type", "payload"}`。全樣本計數：

| `type` / `payload.type` | 次數 | 用途 |
|---|---:|---|
| `event_msg` / `token_count` | 19,695 | usage |
| `event_msg` / `agent_message` | 11,798 | assistant 訊息 |
| `response_item` / `custom_tool_call` | 7,242 | 工具呼叫（`exec`、`apply_patch`） |
| `event_msg` / `patch_apply_end` | 1,677 | 檔案變更 |
| `turn_context` | 1,358 | 每 turn 的 model / cwd |
| `event_msg` / `user_message` | 1,327 | goals |
| `session_meta` | 899 | session 中繼資料 |

`session_meta` 899 筆分佈在 412 個檔案，單一檔案最多 68 筆（resume / fork 時追加）。
**實作只取第一筆。**

### 4.4 工具呼叫的兩種載體

工具呼叫依工具而定，出現在 `response_item/function_call`（arguments 為 JSON 字串）或
`response_item/custom_tool_call`（input 為自由文字）。實作必須同時處理兩種。
`~/.codex/sessions/` 內的分佈：

| 載體 | 工具 | 次數 |
|---|---|---:|
| `custom_tool_call` | `exec` | 4,961 |
| `function_call` | `exec_command` | 2,586 |
| `function_call` | `wait_agent` | 1,096 |
| `custom_tool_call` | `apply_patch` | 495 |
| `function_call` | `write_stdin` | 412 |

`exec_command` 的 arguments 是結構化的：

```json
{"cmd": "nl -ba tests/e2e/calendar.spec.ts | sed -n '285,450p'",
 "workdir": "/Users/chuntsai/Projects/asset_tracker/.worktrees/calendar-entries",
 "yield_time_ms": 10000, "max_output_tokens": 20000}
```

`exec` 的 input 是**任意 JavaScript 程式**，且大多不是 shell 命令：

```javascript
const xs = ALL_TOOLS.filter(x => /browser|chrome/.test(x.name)); text(xs);
```

```javascript
const r = await tools.mcp__node_repl__js({title:"開啟分享的聊天記錄", code:`...`});
for (const c of (r?.content||[])) { if (c.type==="text") text(c.text); }
```

4,963 次 `exec` 中只有 43% 字面上出現 `"cmd":`，而「整個 input 恰好是單一
`await tools.exec_command({...})` 呼叫」的嚴格解析**命中 0 次**。`exec` 是通用 JS sandbox，
不是 shell 工具。

### 4.5 `patch_apply_end`

```json
{"type": "patch_apply_end", "call_id": "call_3KU8...", "success": true,
 "stdout": "...", "stderr": "",
 "changes": {"/abs/path/plans/fix-649.md": {"type": "update", "content": "<整個檔案內容>"}}}
```

`changes` 的 value 帶 `content`，**是完整檔案內容**。見 §6.6。

### 4.6 `token_count`

```json
{"type": "token_count", "info": {
  "last_token_usage":  {"input_tokens":21599, "cached_input_tokens":20224,
                        "cache_write_input_tokens":0, "output_tokens":351,
                        "reasoning_output_tokens":11, "total_tokens":21950},
  "total_token_usage": {"input_tokens":42836, ...}}}
```

`total_token_usage` 為 session 累計。實測某 session 38 筆 `token_count`：
加總 `last_token_usage.total_tokens` 得 **2,635,327**，而最後一筆 `total_token_usage.total_tokens`
為 **2,540,568** — 相差 3.7%，因為有重複發出的 `token_count` 事件。見 §6.5。

### 4.7 `turn_context`

每 turn 一筆，帶 `turn_id`、`cwd`、`model`、`effort` 等。實測同一 session 內 `model` 會變動
（樣本中 `gpt-5.6-terra` 與 `gpt-5.6-sol` 交替）。

### 4.8 `session_meta`

頂層欄位包含 `session_id`、`parent_thread_id`、`timestamp`、`cwd`、`thread_source`、
`agent_nickname`、`agent_path`、`git`、`cli_version`、`originator`。
無 sqlite 時，備援路徑所需的一切都在這一筆記錄裡。

---

## 5. Discovery

### 5.1 模組

```
src/agent_worklog/harnesses/codex/
├── __init__.py
├── source.py            CodexSource：實作 HarnessSessionSource，選擇 catalog
├── thread_catalog.py    讀 state_*.sqlite（唯一含 SQL 的檔案）
├── rollout_catalog.py   目錄掃描備援
└── mapper.py            rollout records → AgentSession
```

兩個 catalog 都回傳 `list[SessionDescriptor]`，`mapper` 與下游無從得知資料來自哪一條路徑。

### 5.2 路徑選擇

1. 於 `home_directory` glob `state_*.sqlite`，取數字後綴最大者。
2. 以 `sqlite3.connect("file:<path>?mode=ro", uri=True)` 開啟。WAL 檔案存在時唯讀開啟正常
   （已實測）。
3. 開啟失敗、找不到檔案、或查詢因 schema 漂移而拋 `sqlite3.OperationalError` → 記錄一則
   warning 並改用 `rollout_catalog`。**不得因此讓整個指令失敗。**

### 5.3 sqlite 路徑

```sql
SELECT t.id, t.rollout_path, t.created_at, t.updated_at, t.cwd, t.title,
       t.agent_nickname, t.thread_source, e.parent_thread_id
  FROM threads t
  LEFT JOIN thread_spawn_edges e ON e.child_thread_id = t.id
 WHERE t.updated_at >= :since AND t.created_at < :until
```

`:since` / `:until` 為 unix 秒。此條件與 Claude Code adapter 的 mtime / `created_at` 邏輯同構。

- `--root-only` 時追加 `AND t.thread_source IS NOT 'subagent'`。**必須用 `IS NOT` 而非 `!=`**：
  SQL 三值邏輯讓 `NULL != 'subagent'` 求值為 NULL，該列會被排除。實測 411 筆中有 64 筆
  （16%）`thread_source` 為 NULL，用 `!=` 會讓它們在 `--root-only` 報告中無聲消失。
- `archived` **不參與過濾**：封存只是 UI 狀態，不代表那週沒有做那件事。
- `title` 為空字串時改用 `agent_nickname`，兩者皆空則為 `None`。
- `rollout_path` 指向的檔案不存在時，跳過該列並記錄 warning（實測 0 筆，但索引與磁碟可能漂移）。

### 5.4 rollout_catalog 備援

掃描 `sessions/**/rollout-*.jsonl` 與 `archived_sessions/rollout-*.jsonl`：

1. 以檔案 mtime 初篩（`mtime < since` 直接跳過），沿用 Claude Code adapter 的做法。
2. 讀開頭至多 50 筆記錄取**第一筆** `session_meta`，取得 `timestamp`、`cwd`、
   `thread_source`、`parent_thread_id`、`agent_nickname`。
3. `created_at >= until` 則跳過。
4. `--root-only` 時排除 `thread_source == "subagent"`。

### 5.5 `load`

讀取 `descriptor.source_location`，逐行解析 JSON，交給 `CodexRolloutMapper`。
最後一行可能因 Codex 正在寫入而截斷 — 沿用 Claude Code source 的做法，忽略解析失敗的行而非
讓整個 session 失敗。檔案不可讀則拋 `SessionParseError`，由既有機制降級為報告中的一則 warning。

---

## 6. Mapping

### 6.1 對應表

| rollout record | `ActivityType` | `content` | `activity_id` | metadata |
|---|---|---|---|---|
| `event_msg/user_message` | `USER_MESSAGE` | `message` | `<行序號>` | — |
| `event_msg/agent_message` | `ASSISTANT_MESSAGE` | `message` | `<行序號>` | — |
| `function_call` / `custom_tool_call` name=`exec_command` | `COMMAND` | arguments 的 `cmd` | `call_id` | `workdir` |
| 其他 `function_call` / `custom_tool_call` | `TOOL_CALL` | **空字串** | `call_id` | — |
| `event_msg/patch_apply_end` `success:true` | `FILE_CHANGE`（每路徑一筆） | 檔案路徑 | `<call_id>:<i>` | — |
| `event_msg/token_count` | 不產生 activity | — | — | 附加至該 turn 的 activity |
| `turn_context` | 不產生 activity | — | — | 記錄當前 `model` |

`activity_id` 在 session 內必須唯一 — `EvidenceItem` 要求每則 evidence 至少指向一個
`source_activity_id`。無 `call_id` 的記錄以行序號為 id。

### 6.2 goals

`user_message` 的 `message` 進入 `USER_MESSAGE` activity，由既有的
`is_meaningful_user_text` 過濾後成為 HIGH confidence 的 goal。Codex 的 `user_message` 可能帶
plugin 前綴（實測 `[@superpowers](plugin://...) 規劃下一步應該做什麼`），這與 OpenCode／Claude Code
的使用者輸入同性質，不另作處理。

### 6.3 不設定 `exit_code` 與 `stderr_empty`

Codex 的命令結果確實含 exit code，但格式散落在自由文字輸出中，實測至少三種：
`{"exit_code":1,"output":"..."}`、`Process exited with code 1`、`#656 exit=0`。以 regex 從輸出
文字反推執行結果，會在 Codex 改變輸出格式時無聲失準。

因此 mapper **一律不設定** `activity.metadata["exit_code"]` 與 `["stderr_empty"]`。其結果由既有
pipeline 自然導出：

- `pipeline.py:239` 的 `_exit_code()` 回傳 `None`。
- 落入 `pipeline.py:264` 的 `elif exit_code is None` 分支。
- `_append_stderr_heuristic` 因 `stderr_empty` 不為 `True` 而不產生任何項目。

**報告不會宣稱任何一條命令通過或失敗。** 這與 Claude Code 的處置一致，且更保守（Claude Code
至少有 stderr 啟發式）。`extraction/pipeline.py` 零修改。

**推論出來的一個後果，實作期間才確認：Codex 命令不會出現在報告的任何區段。**
`templates/worklog.md.j2` 的區段是 Completed、Problems Resolved、In Progress、Key Files、
Directories、Sessions、Branches、Usage、Warnings — **沒有 Key Commands**。`evidence.commands`
不被任何 renderer 讀取；`summarizers/rule_based.py` 只讀 `goals`、`outcomes`、`files_changed`。
命令唯一的去向是 LLM 請求，因為 `openai_compatible.py` 送出整個
`evidence.model_dump(mode="json")`。

因此 `--no-llm` 的 Codex 報告完全看不到命令，加了 LLM 才可能在敘述中被提及。這與 Claude Code
有實質差異：Claude Code 的 stderr 啟發式會把驗證命令變成 **outcome**，而 outcome 會渲染在
「In Progress」底下（`Ran verification command: <command>`）。Codex 兩個訊號都不設，所以連那條
路徑都不會走到。README 的限制條目必須照這個事實寫，不能宣稱命令會出現在報告裡。

實作結果的唯一結構化訊號是 `patch_apply_end.success`，見 §6.6。

### 6.4 `exec` 的 content 留空

`exec` 是通用 JS sandbox（§4.4），其 input 不是命令。mapper 發出 `TOOL_CALL` activity 但
`content` 為空字串，因此：

- `pipeline.py:228` 的 `if is_command and content` 短路，不產生 command evidence。
- 該段 JavaScript 不會進入報告，也不會進入 LLM 請求。

仍然發出 activity，因為 usage 需要依附於 activity（§6.5），純 `exec` 的 turn 否則會在 usage
表中消失。

**已知限制（須寫入 README）：** 從 `exec` 內部呼叫 `tools.exec_command` 執行的命令不會出現在
報告中。實測 `~/.codex/sessions/` 內 `exec`:`exec_command` 為 4,961:2,586，且較新的 Codex 版本
偏好 `exec`，這個缺口會隨版本上升。升級路徑：若要補回，唯一穩健的做法是在 Codex 開始把
`exec` 內的子命令記錄為獨立結構化記錄時改讀那些記錄，而非解析 JavaScript。

### 6.5 Usage

**用 `total_token_usage` 的逐 turn 差值，不是加總 `last_token_usage`。** 依 §4.6 實測，加總
`last` 會多算 3.7%，而差值的總和依定義等於 Codex 自己的累計數字。

演算法：

1. 維護 `previous_total`，初值為全零。
2. 每筆 `token_count` 取 `info.total_token_usage`，逐欄位減去 `previous_total` 得 delta。
3. 任一欄位 delta 為負 → 視為累計重置（fork / compaction），該筆改用原始值。
4. 更新 `previous_total`。
5. 將 delta 附加至**此筆 `token_count` 之前、最近一個尚未帶 usage 的 activity**，形式為
   `metadata["model"]` 與 `metadata["usage"]`，與 Claude Code mapper 相同的形狀。
6. 若不存在這樣的 activity（該段記錄只有 reasoning 或只有 `exec`），delta 暫存於
   `pending_usage[model]`，併入同一 model 的下一個 activity — 沿用 Claude Code mapper
   既有的機制。session 結束時仍有殘留，則併入同一 model 最後一個帶 usage 的 activity。

欄位對應：

| Codex | canonical |
|---|---|
| `input_tokens` | `input_tokens` |
| `output_tokens` | `output_tokens` |
| `cached_input_tokens` | `cache_read_tokens` |
| `cache_write_input_tokens` | `cache_write_tokens` |
| `reasoning_output_tokens` | **丟棄**（已含於 `output_tokens`，計入會重複） |

model 取最近一筆 `turn_context.model`；`turn_context` 出現前的 usage 以 `session_meta` 或
`threads.model` 為初值，兩者皆無則跳過該筆（不製造 `unknown` 列）。

### 6.6 `patch_apply_end` 與隱私

只取 `changes` 這個 dict 的 **key**（檔案絕對路徑），value 整個丟棄。

value 的 `content` 欄位是完整檔案內容（§4.5）。`EVIDENCE_TEXT_MAX_LENGTH = 300` 確實擋得住，
但沒有理由讓整份檔案先進入 activity 再被截斷 — 它會佔用記憶體、出現在偵錯輸出，並在任何未來
新增的 activity 消費者面前重新成為風險。**在 mapper 就丟棄。**

`success` 為 `false` 的 `patch_apply_end` 不產生 `FILE_CHANGE`。失敗的修補沒有改到檔案，
把它列進 Key Files 會是錯的；pipeline 也沒有「檔案變更失敗」這個 evidence 類別，為此新增
一個不符合本版範圍。

---

## 7. Usage 模組共用

`harnesses/claude_code/usage.py` 全檔只讀 `activity.metadata` 的 `model` 與 `usage`，與 harness
無關。移至 `renderers/usage.py`，函式更名 `render_activity_usage`，由 Claude Code 與 Codex 共用。
OpenCode 維持走 `opencode stats`。

`HarnessSourceError("Claude Code sessions carried no token usage")` 的訊息改為接受 harness 名稱
參數。`tests/unit/harnesses/claude_code/test_usage.py` 一併移至 `tests/unit/renderers/test_usage.py`。

此模組移動不改變任何行為，Claude Code 報告的輸出必須逐字元不變 — 既有測試即為此保證。

---

## 8. CLI、設定與 doctor

### 8.1 設定

```python
class CodexSettings(BaseModel):
    """Codex harness settings."""

    # `false` makes `--harness codex` fail with a configuration error, so an
    # operator can forbid reading `~/.codex` on a whole machine.
    enabled: bool = True
    home_directory: Path = Field(default_factory=lambda: Path.home() / ".codex")
```

加入 `HarnessSettings.codex`。`state_*.sqlite`、`sessions/`、`archived_sessions/` 全部由
`home_directory` 推導，不開三個設定項。環境變數
`AGENT_WORKLOG_HARNESSES__CODEX__HOME_DIRECTORY`、
`AGENT_WORKLOG_HARNESSES__CODEX__ENABLED`。

### 8.2 `cli.py`

`Harness` enum 加入 `CODEX = "codex"`。

`_require_enabled_harness` 的 if/else 改為一行查表：

```python
enabled = getattr(settings.harnesses, harness.name.lower()).enabled
```

`OPENCODE`→`opencode`、`CLAUDE_CODE`→`claude_code`、`CODEX`→`codex`，enum 名稱與設定欄位名
本就對應，之後再加 harness 不必再改這裡。

`_build_scan_service` 與 `_usage_provider` **維持 if/elif 鏈**。三個分支各自建構不同型別的物件，
改成 dict-of-callables 不會更短，只會多一層間接。**本版不引入 harness registry 抽象。**

### 8.3 `doctor`

`--harness codex` 檢查 `home_directory` 存在且可讀，detail 標明將採用哪條 discovery 路徑：

```
codex home directory   /Users/x/.codex (state_5.sqlite)
codex home directory   /Users/x/.codex (directory scan)
```

讓使用者一眼看出備援是否被觸發。加上既有的 `git --version`。目錄不存在 → 既有的 exit code 5
（harness 相依性錯誤），不新增 exit code。

---

## 9. 錯誤處理

| 情況 | 處置 |
|---|---|
| `home_directory` 不存在 | `HarnessSourceError` → exit 5 |
| `state_*.sqlite` 不存在 | 靜默改用 rollout_catalog（`--verbose` 時顯示） |
| `state_*.sqlite` 開啟失敗或 schema 漂移 | warning + 改用 rollout_catalog |
| `rollout_path` 指向的檔案不存在 | 跳過該 session + warning |
| rollout 檔案不可讀 | `SessionParseError` → 跳過該 session + 報告內 warning |
| rollout 最後一行截斷 | 忽略該行，其餘照常使用 |
| 期間內無任何 session | 既有的 exit code 4 |
| 所有 session 皆無 token 計數 | usage 區段省略 + warning（沿用 Claude Code 行為） |

---

## 10. 測試

| 檔案 | 內容 |
|---|---|
| `tests/unit/harnesses/codex/test_thread_catalog.py` | 期間過濾邊界、`--root-only`、parent 邊、archived 不被排除、`state_*.sqlite` 取最大版本號、schema 漂移退回備援 |
| `tests/unit/harnesses/codex/test_rollout_catalog.py` | 無 sqlite 時產出與 sqlite 路徑等價的 descriptor、只取第一筆 `session_meta` |
| `tests/unit/harnesses/codex/test_mapper.py` | 各 record 型別映射、`function_call` 與 `custom_tool_call` 兩種載體、token 差值與重置、model 中途更換、`exec` content 為空 |
| `tests/unit/renderers/test_usage.py` | 由 `tests/unit/harnesses/claude_code/test_usage.py` 移入，加上 Codex 案例 |
| `tests/integration/test_codex_end_to_end.py` | 對照 `test_claude_code_end_to_end.py`，釘住 usage 表的具體數值 |

sqlite fixture **在測試中以 SQL 建立**，不 commit 二進位檔。rollout fixture 置於
`tests/fixtures/codex/`，內容為手寫的最小 JSONL。

三項必要的回歸測試：

1. Codex 報告的任何區段都不得出現 `Verification passed`。
2. `patch_apply_end.changes` 的 `content` 不得出現在報告或 LLM 請求中。
3. `exec` 的 JavaScript input 不得出現在報告或 LLM 請求中。

維持 `--cov-fail-under=80`。

---

## 11. 文件

- `README.md` / `README.zh-TW.md`：移除「Codex is not currently supported」；Capabilities、
  Requirements、`--harness` 選項表、Privacy、Current support and limits 各補 Codex 段落。
- Current support and limits 新增三條：
  - 從 `exec` 工具內部執行的命令不會出現在報告中（§6.4）。
  - Codex usage 計入每次 API 請求的完整 input，與 Codex 自身顯示的數字一致，但不是「不重複
    token 數」。
  - Codex 報告不宣稱任何命令通過或失敗（§6.3）。
- `docs/privacy.md`：Codex 段落 — 讀取範圍、`patch_apply_end.content` 的丟棄、`exec` JS 的丟棄。
- `docs/configuration.md`：`CodexSettings` 兩個設定項。
- `CHANGELOG.md`：Unreleased 區段。

---

## 12. 交付順序

1. `CodexSettings` + `Harness.CODEX` + `_require_enabled_harness` 一行化。
2. `thread_catalog.py` + 單元測試。
3. `rollout_catalog.py` + 單元測試。
4. `source.py`（路徑選擇與 `load`）+ 單元測試。
5. `mapper.py` + 單元測試（含三項回歸測試）。
6. `renderers/usage.py` 模組移動 + 測試移動（Claude Code 輸出必須不變）。
7. `_build_scan_service` / `_usage_provider` / `doctor` 接線 + 整合測試。
8. 文件與 CHANGELOG。
