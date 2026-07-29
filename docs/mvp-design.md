# Agent Worklog — MVP Design Document

**Status:** Draft  
**Version:** 0.1  
**Implementation:** Python 3.11+  
**Primary harness:** OpenCode  
**Package:** `agent-worklog`  
**Python module:** `agent_worklog`  
**CLI:** `agent-worklog`  
**Default timezone:** `Asia/Taipei`

---

## 1. Executive Summary

Agent Worklog 是一個 local-first CLI 工具，負責收集 coding-agent harness 的歷史 session，將指定期間內的工作活動依 Git repository 聚合，並產生工程工作報告。

MVP 以 OpenCode 為第一個 harness，直接以唯讀方式查詢 OpenCode 全域資料庫。查詢範圍涵蓋所有 project，不受執行 CLI 時所在目錄限制。系統會找出指定天數或日期區間內有實際 activity 的 session，再解析 session 的 working directory 與 Git repository，最後依 canonical Git repository identity 分組。

長期架構不綁定 OpenCode DB。OpenCode、Codex、Claude Code 等 harness 各自實作 session source adapter，並輸出相同的 canonical `AgentSession` model。Git grouping、evidence extraction、secret redaction、summarization 與 report rendering 皆由共用 pipeline 處理。

核心原則：

> Harness adapters collect session evidence.  
> Canonical models isolate storage differences.  
> Git repositories define project identity.  
> Report services turn activity into worklogs.

---

## 2. Product Identity

### 2.1 Naming

| Layer | Name |
|---|---|
| Product | Agent Worklog |
| Repository | `agent-worklog` |
| PyPI distribution | `agent-worklog` |
| Python package | `agent_worklog` |
| CLI executable | `agent-worklog` |

### 2.2 Positioning

> Agent Worklog turns coding-agent sessions into repository-based engineering reports.

中文定位：

> 將 OpenCode、Codex、Claude Code 等 coding-agent sessions，依 Git repository 整理成工程工作報告。

### 2.3 Why “Worklog”

`worklog` 不限制輸出一定是週報。系統未來可以支援：

- Daily report
- Weekly report
- Monthly report
- Sprint report
- Release report
- Arbitrary date range report

MVP 預設使用最近七天，但產品與資料模型不綁定 weekly cadence。

---

## 3. Problem Statement

Coding-agent harness 會累積大量 session 資料，包括：

- User goals and prompts
- Assistant responses
- Tool calls and tool results
- Shell commands
- Files read or changed
- Build, test, and lint results
- Errors and debugging history
- Session hierarchy and subagents
- Model and token usage
- Working directory and project metadata

這些資料能反映實際工程工作，但存在以下問題：

1. 不同 harness 使用不同的 session storage。
2. OpenCode、Codex、Claude Code 的資料模型不同。
3. Sessions 分散在多個 project、clone 與 worktree。
4. 長 session 包含大量重複 context、build log 和低價值輸出。
5. Session folder 不等於 project identity。
6. 同一 Git repository 可能存在於多個 filesystem path。
7. 原始 session 可能包含 credentials、API keys 或公司程式碼。
8. 直接將完整 session 傳給 LLM 成本高且風險大。
9. 只依 session creation time 查詢，會漏掉持續多天的 session。
10. 直接依 harness 的 internal schema 實作，容易因版本更新失效。

---

## 4. Goals

MVP 必須：

1. 提供可透過 `pipx` 或 `pip` 安裝的 Python CLI。
2. 支援 OpenCode 全域資料庫，不限定 current project。
3. 查詢指定天數或日期區間內有 activity 的 sessions。
4. 支援 session 建立於較早日期、但期間內仍有活動的情境。
5. 將 OpenCode DB records 轉換成 canonical `AgentSession`。
6. 支援 parent/child session hierarchy。
7. 依 canonical Git repository identity 聚合 sessions。
8. 將不同 folder、clone path 或 worktree 中的同一 repository 合併。
9. 從 session 抽取 goals、commands、files、errors、outcomes 與 usage。
10. 在任何外部 LLM 呼叫前執行 secret redaction。
11. 不使用 LLM 時仍能產生有用的 deterministic report。
12. 支援 Markdown 與 JSON 輸出。
13. 讓未來 Codex 與 Claude Code adapter 不需修改 report pipeline。
14. 對 OpenCode schema 差異提供 adapter 與版本檢查。
15. 對單一 session 的解析失敗採 partial-failure 策略。

---

## 5. Non-Goals

MVP 不包含：

- Web UI
- Team server
- Centralized session upload
- Slack or email delivery
- GitHub PR 或 Azure DevOps Work Item 自動關聯
- 工程師績效評分
- Productivity score
- Source code semantic review
- 完整 Git diff 上傳
- Codex adapter 正式支援
- Claude Code adapter 正式支援
- 跨機器 session 同步
- 即時 hooks ingestion
- 自動排程 daemon
- npm 原生核心實作

MVP 會預留 extension points，但只正式支援 OpenCode。

---

## 6. Key Design Decisions

### 6.1 OpenCode DB Is the MVP Session Source

MVP 直接從 OpenCode 全域 SQLite database 查詢 sessions。

DB discovery 不依賴 current working directory，也不可加入 current project filter。

```text
OpenCode global DB
    → sessions across all projects
    → date/activity filtering
    → canonical sessions
```

### 6.2 Harness Storage Is Not the Core Abstraction

核心不可直接依賴 `OpenCodeDatabaseRepository`。

共用 abstraction 是：

```text
HarnessSessionSource
    → SessionDescriptor
    → AgentSession
```

OpenCode DB 只是第一個 implementation。

### 6.3 Activity Time Defines the Reporting Period

週報代表期間內發生的工作，不是期間內新建立的 session。

納入條件：

```text
A logical session is included when at least one activity satisfies:

since <= activity.timestamp < until
```

### 6.4 Git Repository Defines Project Identity

主要 grouping unit 是 Git repository，不是：

- Current folder
- OpenCode project folder
- Session folder
- Repository basename
- Branch
- Worktree path

### 6.5 Deterministic Extraction Before LLM

完整 session 不直接傳給 LLM。

```text
Raw session
    → normalize
    → filter
    → extract evidence
    → redact
    → summarize
```

### 6.6 Local-First and Read-Only

Agent Worklog 預設：

- 僅讀取 local harness storage
- 以 read-only 模式開啟 harness database
- 不更新或 migration harness database
- 不自動上傳 session
- 不執行 OpenCode write operation

---

## 7. User Stories

### 7.1 Report the Last Seven Days

```bash
agent-worklog report --days 7
```

或：

```bash
agent-worklog report --since 7d
```

結果：

```text
reports/worklog-2026-07-23_2026-07-29.md
```

### 7.2 Query All OpenCode Projects

```bash
agent-worklog scan --harness opencode --days 7
```

即使 command 在任意 folder 執行，也會查詢 OpenCode DB 中所有符合時間範圍的 sessions。

### 7.3 Inspect Repository Grouping

```bash
agent-worklog scan --days 7 --verbose
```

顯示：

```text
Assets Tracker
  Repository: github.com/mike/assets-tracker
  Sessions: 8
  Working directories:
    /home/mike/projects/assets-tracker
    /home/mike/worktrees/assets-tracker-ofx
```

### 7.4 Inspect One Session

```bash
agent-worklog inspect ses_123
```

### 7.5 Generate Without LLM

```bash
agent-worklog report --days 7 --no-llm
```

### 7.6 Historical Range

```bash
agent-worklog report \
  --since 2026-07-01 \
  --until 2026-07-08
```

---

## 8. High-Level Architecture

```text
┌─────────────────────────────────────┐
│ Harness Session Sources             │
│                                     │
│ OpenCode DB                         │
│ Codex SQLite + JSONL        (future)│
│ Claude transcript/hooks    (future) │
└──────────────────┬──────────────────┘
                   │ SessionDescriptor
                   ▼
┌─────────────────────────────────────┐
│ Harness Adapter                     │
│ - discover/query sessions           │
│ - load transcript                   │
│ - normalize fields                  │
│ - expose capabilities               │
└──────────────────┬──────────────────┘
                   │ AgentSession
                   ▼
┌─────────────────────────────────────┐
│ Logical Session Builder             │
│ - parent/child hierarchy            │
│ - activity range filtering          │
│ - duplicate event protection        │
└──────────────────┬──────────────────┘
                   │ LogicalSession
                   ▼
┌─────────────────────────────────────┐
│ Repository Resolver                 │
│ - working directory                 │
│ - Git origin remote                 │
│ - Git common directory              │
│ - fallback identity                 │
└──────────────────┬──────────────────┘
                   │ RepositoryActivity
                   ▼
┌─────────────────────────────────────┐
│ Evidence Pipeline                   │
│ - goals                             │
│ - commands                          │
│ - files                             │
│ - errors                            │
│ - outcomes                          │
│ - secret redaction                  │
└──────────────────┬──────────────────┘
                   │ Structured evidence
                   ▼
┌─────────────────────────────────────┐
│ Summarizers                         │
│ - rule-based                        │
│ - OpenAI-compatible LLM             │
└──────────────────┬──────────────────┘
                   │ Report model
                   ▼
┌─────────────────────────────────────┐
│ Renderers                           │
│ - Markdown                          │
│ - JSON                              │
└─────────────────────────────────────┘
```

---

## 9. Harness Source Abstraction

### 9.1 Session Descriptor

Descriptor 是輕量 metadata，用於 discovery 階段，避免一開始載入完整 transcript。

```python
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class SessionDescriptor(BaseModel):
    harness: str
    session_id: str

    source_kind: str
    source_location: str | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None

    working_directory_hint: str | None = None
    project_id_hint: str | None = None
    parent_session_id: str | None = None

    metadata: dict[str, object] = Field(default_factory=dict)
```

### 9.2 Source Interface

```python
from abc import ABC, abstractmethod
from datetime import datetime


class HarnessSessionSource(ABC):
    name: str

    @abstractmethod
    def capabilities(self) -> "HarnessCapabilities":
        """Describe fields supported by this harness source."""

    @abstractmethod
    def discover(
        self,
        since: datetime,
        until: datetime,
    ) -> list[SessionDescriptor]:
        """Return candidate sessions across all projects."""

    @abstractmethod
    def load(
        self,
        descriptor: SessionDescriptor,
    ) -> "AgentSession":
        """Load and normalize one complete session."""
```

### 9.3 Capabilities

```python
class HarnessCapabilities(BaseModel):
    activity_timestamps: bool = False
    message_content: bool = False
    tool_calls: bool = False
    tool_results: bool = False
    token_usage: bool = False
    file_changes: bool = False
    working_directory: bool = False
    parent_child_sessions: bool = False
    model_metadata: bool = False
```

缺少的 capability 必須表示為 unavailable，不可用 `0` 假裝資料存在。

---

## 10. OpenCode MVP Source

### 10.1 DB Discovery

OpenCode DB path 不應只 hard-code 單一檔名。

Discovery priority：

1. CLI `--database PATH`
2. Config `providers.opencode.database.path`
3. `OPENCODE_DB`
4. Known platform/version-specific candidate paths
5. `doctor` failure with actionable message

```python
class OpenCodeDatabaseLocator:
    def locate(self) -> Path:
        ...
```

### 10.2 Read-Only Requirements

DB connection 必須：

- 使用 SQLite read-only mode
- 設定 `PRAGMA query_only = ON`
- 不執行 migration
- 不建立 table 或 index
- 不修改 user database
- 設定短查詢 timeout
- 正確處理 WAL database
- 在 schema 不支援時停止該 provider，而不是猜測 column
- 避免 long-running transaction 阻塞 OpenCode

### 10.3 Schema Adapter

OpenCode schema 是 harness internal implementation，可能隨版本改變。

```python
class OpenCodeSchemaAdapter(ABC):
    @abstractmethod
    def detect(self, connection) -> bool:
        ...

    @abstractmethod
    def query_session_candidates(
        self,
        connection,
        since: datetime,
        until: datetime,
    ) -> list[SessionDescriptor]:
        ...

    @abstractmethod
    def load_session(
        self,
        connection,
        session_id: str,
    ) -> AgentSession:
        ...
```

Adapter selection：

```text
Inspect tables and columns
    → match known schema adapter
    → return adapter
    → otherwise fail with unsupported-schema error
```

不可根據 OpenCode version string 單獨決定 schema。

### 10.4 Cross-Project Query

Query 不得包含：

```text
current directory
current project ID
current repository
```

概念查詢：

```sql
SELECT DISTINCT session_id
FROM activity_source
WHERE activity_timestamp >= :since
  AND activity_timestamp < :until;
```

實際 tables 與 columns 由 schema adapter 決定。

### 10.5 Candidate and Exact Filtering

若 schema 支援 message/part timestamp query，直接由 DB 找出精確 session。

若只能取得 session `updated_at`：

1. 查詢所有 `updated_at >= since` 的 candidate sessions。
2. 不加入 `updated_at < until`。
3. 載入 candidate activities。
4. 在 Python 以 activity timestamp 精確過濾。

不加入上界的原因：

```text
Session 在報告期間有活動，
但在報告期間結束後又繼續更新，
其 updated_at 會大於 until。
```

### 10.6 OpenCode API Is Optional, Not MVP Source

OpenCode 提供 session/message API，可作為未來 source adapter。

MVP 選擇 DB 的原因：

- 不要求 OpenCode server 正在執行
- 能查詢全域歷史資料
- 適合 local CLI batch report
- 可使用 read-only connection

API adapter 可在未來作為較穩定但需要 server lifecycle 的替代方案。

---

## 11. Canonical Session Model

### 11.1 Activity Types

```python
from enum import StrEnum


class ActivityType(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    COMMAND = "command"
    FILE_CHANGE = "file_change"
    ERROR = "error"
    SYSTEM = "system"
```

### 11.2 Session Activity

```python
class SessionActivity(BaseModel):
    activity_id: str
    activity_type: ActivityType
    timestamp: datetime | None = None

    content: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None

    metadata: dict[str, object] = Field(default_factory=dict)
```

### 11.3 Token Usage

```python
class TokenUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
```

`None` 表示 harness 未提供，不等於零。

### 11.4 Agent Session

```python
class AgentSession(BaseModel):
    harness: str
    session_id: str
    parent_session_id: str | None = None

    source_kind: str
    source_location: str | None = None
    source_version: str | None = None

    title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    working_directory: str | None = None
    project_id_hint: str | None = None

    activities: list[SessionActivity] = Field(default_factory=list)
    token_usage: TokenUsage | None = None

    raw_metadata: dict[str, object] = Field(default_factory=dict)
```

---

## 12. Logical Sessions and Subagents

Coding harness 可能為 subagent 或 fork 建立 child session。若所有 child sessions 都當成獨立工作，報告會重複計數。

### 12.1 Logical Session

```python
class LogicalSession(BaseModel):
    logical_session_id: str
    root_session_id: str

    harness: str
    sessions: list[AgentSession]

    activities: list[SessionActivity]
    working_directories: list[str]

    started_at: datetime | None = None
    updated_at: datetime | None = None
```

### 12.2 Aggregation Rules

- Root session 是 logical session identity。
- Child sessions 的 evidence 合併至 root。
- Child session 不重複列為 top-level completed item。
- Metrics 分別顯示：
  - Logical sessions
  - Root sessions
  - Child sessions
- 若 child 有期間內 activity，但 parent 沒有，logical session 仍納入。
- 若 parent metadata 無法載入，child 可以成為 synthetic root。
- Activity 使用 `activity_id` 或 provider-specific stable key 去重。

---

## 13. Date and Time Semantics

### 13.1 Supported Inputs

```bash
--days 7
--since 7d
--since 2026-07-20
--until 2026-07-27
```

### 13.2 Range Definition

所有範圍採 half-open interval：

```text
since <= timestamp < until
```

### 13.3 Defaults

```text
Timezone: Asia/Taipei
Until: current time
Days: 7
```

`--days 7` 等同：

```text
since = now - 7 days
until = now
```

它是 rolling seven-day range，不等同 calendar week。

未來可增加：

```bash
agent-worklog report --week current
agent-worklog report --week previous
```

### 13.4 Missing Timestamps

若 activity 無 timestamp：

1. 使用 message timestamp。
2. 再使用 session updated/created timestamp 作低信心 fallback。
3. 標記 `timestamp_inferred=true`。
4. 無任何可用 timestamp 時，不納入 date-filtered evidence。
5. `inspect` 顯示 warning。

---

## 14. Git Repository Resolution

### 14.1 Identity Priority

```text
1. Normalized Git origin remote
2. Git common directory
3. Harness project ID
4. Normalized path fallback
5. Per-session unknown identity
```

### 14.2 Working Directory Resolution

來源優先順序：

1. Session metadata directory
2. Session working directory
3. Tool call working directory
4. Harness project record
5. Provider-specific path hint

不可使用 `Path.cwd()` 覆蓋 session 本身的 directory。

### 14.3 Canonical Remote

以下 remote：

```text
git@github.com:mike/assets-tracker.git
https://github.com/mike/assets-tracker.git
ssh://git@github.com/mike/assets-tracker.git
```

正規化為：

```text
github.com/mike/assets-tracker
```

Project ID：

```text
git:github.com/mike/assets-tracker
```

### 14.4 Git Commands

```text
git rev-parse --show-toplevel
git remote get-url origin
git rev-parse --git-common-dir
git branch --show-current
```

Requirements：

- 使用 argument list
- 不使用 `shell=True`
- 設定 timeout
- 設定 `GIT_TERMINAL_PROMPT=0`
- 捕捉 stderr
- 不記錄 credentials
- 失敗時 fallback
- 支援 detached HEAD
- 支援 worktree

### 14.5 Worktrees

同一 remote 的 sessions，即使位於：

```text
/home/mike/projects/assets-tracker
/home/mike/worktrees/assets-tracker-ofx
/home/mike/worktrees/assets-tracker-ui
```

全部聚合為：

```text
git:github.com/mike/assets-tracker
```

Branch 保留為 metadata，不參與 project grouping。

### 14.6 Deleted Paths

若歷史 session 的 directory 已刪除：

```text
cached repository mapping
    → harness project ID
    → normalized path fallback
```

MVP 尚未建立 cache 時：

```text
harness project ID
    → normalized path fallback
```

### 14.7 Unknown Sessions

不可將所有 unknown sessions 聚合到相同 project。

使用：

```text
unknown:<harness>:<session-id>
```

避免不相關 session 被錯誤合併。

---

## 15. Repository Identity Model

```python
class RepositoryIdentityType(StrEnum):
    GIT_REMOTE = "git_remote"
    GIT_COMMON_DIR = "git_common_dir"
    HARNESS_PROJECT = "harness_project"
    PATH_FALLBACK = "path_fallback"
    UNKNOWN = "unknown"


class RepositoryIdentity(BaseModel):
    repository_id: str
    display_name: str
    identity_type: RepositoryIdentityType

    normalized_remote: str | None = None
    repository_host: str | None = None
    repository_owner: str | None = None
    repository_name: str | None = None

    git_root: str | None = None
    git_common_dir: str | None = None

    branches: list[str] = Field(default_factory=list)
    working_directories: list[str] = Field(default_factory=list)

    harness_project_ids: list[str] = Field(default_factory=list)
    resolution_method: str
```

Display name priority：

```text
Explicit mapping
    → repository name
    → Git root basename
    → path suffix
    → harness project name
    → Unknown
```

Display name collision 不影響 grouping。必要時顯示 owner：

```text
API — team-a
API — team-b
```

---

## 16. Evidence Extraction

### 16.1 Session Evidence

```python
class CommandEvidence(BaseModel):
    command: str
    timestamp: datetime | None = None
    working_directory: str | None = None
    exit_code: int | None = None
    successful: bool | None = None


class ErrorEvidence(BaseModel):
    message: str
    timestamp: datetime | None = None
    command: str | None = None
    resolved: bool | None = None


class SessionEvidence(BaseModel):
    logical_session_id: str

    goals: list[str] = Field(default_factory=list)
    commands: list[CommandEvidence] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    errors: list[ErrorEvidence] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)

    activity_count: int = 0
    token_usage: TokenUsage | None = None
```

### 16.2 Goal Extraction

Sources：

- User messages
- Session title
- Meaningful follow-up requests

Filter：

- `ok`
- `continue`
- confirmation-only messages
- repeated prompts
- pasted logs without request

### 16.3 Command Extraction

Extract：

- Command
- Timestamp
- Working directory
- Exit code
- Success state

Do not preserve inline secrets or full environment.

### 16.4 File Changes

Sources：

- Edit/write/patch tool calls
- Session diff metadata
- Harness-provided changed files
- Explicit file paths from tool output

MVP 不重新執行 `git diff` 來修改或補全歷史狀態，因為 repository 現況可能與 session 當時不同。

### 16.5 Error Extraction

Signals：

- Non-zero exit code
- Exception traceback
- Build/test failure
- Tool failure
- stderr
- Explicit error response

重複錯誤應以 normalized signature 合併。

### 16.6 Outcome Extraction

Sources：

- Successful command/test/build
- Final assistant completion summary
- Explicit user confirmation
- Completed file modification

無足夠 evidence 時，不可推測完成。

---

## 17. Noise Reduction

Default limits：

```yaml
extraction:
  max_activity_chars: 5000
  max_tool_result_chars: 3000
  max_error_chars: 2000
  max_goals_per_logical_session: 12
  max_commands_per_logical_session: 100
  max_files_per_logical_session: 100
```

Reduce or omit：

- Dependency install logs
- Lockfile content
- Repeated compiler warnings
- Duplicate stack traces
- Binary/base64 content
- Complete source files
- Full reasoning content
- System instructions
- Replayed historical context

Truncated content must contain：

```text
[truncated]
```

---

## 18. Secret Redaction

### 18.1 Redaction Stages

1. Immediately after parsing activity content.
2. After evidence extraction.
3. Immediately before external LLM request.
4. Before verbose/debug output.

### 18.2 Default Patterns

At minimum：

- OpenAI/Anthropic/provider API keys
- GitHub tokens
- AWS credentials
- Bearer tokens
- Basic auth
- JWTs
- Database URLs with passwords
- Generic password assignments
- Private key blocks
- Cookie/session tokens

### 18.3 Exclusions

```yaml
security:
  redact_secrets: true
  exclude_patterns:
    - "*.env"
    - ".env.*"
    - "*credentials*"
    - "*secret*"
    - "*.pem"
    - "*.key"
```

Agent Worklog 不應讀取這些檔案內容。Session 中已記錄的內容仍需 redaction。

---

## 19. Summarization

### 19.1 Rule-Based Mode

```bash
agent-worklog report --no-llm
```

Mapping：

```text
Goals               → Worked on
Successful outcomes → Completed
Resolved errors     → Problems resolved
Unresolved goals    → In progress
Files changed       → Key files
```

### 19.2 LLM Mode

MVP 支援 OpenAI-compatible endpoint。

LLM 只接收 redacted structured evidence，不接收完整 transcript。

```yaml
llm:
  enabled: true
  provider: openai-compatible
  model: gpt-5-mini
  base_url: https://api.openai.com/v1
  api_key_env: OPENAI_API_KEY
```

### 19.3 Structured Output

```json
{
  "summary": "This period focused on...",
  "completed": [],
  "problems_resolved": [],
  "in_progress": [],
  "key_files": []
}
```

Failure behavior：

1. Retry once for transient/invalid structured response.
2. Fallback to rule-based summarizer.
3. Add warning.
4. Still render report.

### 19.4 Summary Rules

- 不誇大成果
- 不創造 evidence 中不存在的內容
- 合併重複活動
- 區分 completed 與 in-progress
- 不使用 token count 評價 productivity
- 不包含 secrets
- 不包含完整 source code
- 保留 harness 與 branch 作為 metadata，而非成果本身

---

## 20. Report Model and Format

### 20.1 Repository Summary

```python
class RepositorySummary(BaseModel):
    repository_id: str
    repository_name: str
    normalized_remote: str | None = None

    summary: str
    completed: list[str] = Field(default_factory=list)
    problems_resolved: list[str] = Field(default_factory=list)
    in_progress: list[str] = Field(default_factory=list)
    key_files: list[str] = Field(default_factory=list)

    harnesses: dict[str, int] = Field(default_factory=dict)
    branches: list[str] = Field(default_factory=list)

    logical_session_count: int = 0
    child_session_count: int = 0
    token_usage: TokenUsage | None = None
```

### 20.2 Markdown Example

```markdown
# Engineering Worklog

**Period:** 2026-07-23 17:45 – 2026-07-29 17:45  
**Timezone:** Asia/Taipei

## Summary

This period focused on designing Agent Worklog and improving Assets Tracker.

## Repositories

### Agent Worklog

Repository: `github.com/mike/agent-worklog`

#### Completed

- Defined a harness-independent session source architecture.
- Designed cross-project OpenCode DB discovery.
- Added Git repository-based session grouping.

#### Problems Resolved

- Removed filesystem paths as the primary project identity.
- Prevented child agent sessions from being double-counted.

#### In Progress

- Implementing the OpenCode schema adapter.
- Adding deterministic evidence extraction.

#### Harness Activity

- OpenCode: 6 logical sessions

#### Branches

- `main`
- `feature/opencode-source`

## Metrics

| Metric | Value |
|---|---:|
| Repositories | 3 |
| Logical sessions | 14 |
| Child sessions | 8 |
| Activities | 438 |
| Commands | 87 |
| Files changed | 32 |
```

### 20.3 JSON Output

```json
{
  "schema_version": "1",
  "generated_at": "2026-07-29T17:45:00+08:00",
  "period": {
    "since": "2026-07-23T17:45:00+08:00",
    "until": "2026-07-29T17:45:00+08:00"
  },
  "repositories": [],
  "metrics": {},
  "warnings": []
}
```

---

## 21. CLI Design

CLI framework：Typer。

### 21.1 Commands

```text
agent-worklog init
agent-worklog doctor
agent-worklog scan
agent-worklog inspect
agent-worklog report
```

### 21.2 Global Options

```text
--config PATH
--verbose
--quiet
--no-color
--version
```

### 21.3 `doctor`

```bash
agent-worklog doctor
```

Checks：

- OpenCode DB path
- File readability
- SQLite connectivity
- Query-only mode
- Detected schema adapter
- Required tables/columns
- Git executable
- LLM config, without printing secrets

### 21.4 `scan`

```bash
agent-worklog scan \
  --harness opencode \
  --days 7
```

Options：

```text
--days INTEGER
--since TEXT
--until TEXT
--harness TEXT
--repository TEXT
--database PATH
--json
```

### 21.5 `inspect`

```bash
agent-worklog inspect <session-id>
```

Options：

```text
--show-activities
--show-evidence
--show-hierarchy
--raw-metadata
--json
```

Raw metadata still passes redaction.

### 21.6 `report`

```bash
agent-worklog report \
  --days 7 \
  --format markdown
```

Options：

```text
--days INTEGER
--since TEXT
--until TEXT
--harness TEXT
--repository TEXT
--format markdown|json
--output PATH
--no-llm
--dry-run
--allow-empty
```

Mutual exclusivity：

- `--days` cannot be combined with `--since`.
- `--until` requires `--since`.
- `--output` with multiple formats requires output directory.

---

## 22. Configuration

```yaml
version: 1

harnesses:
  opencode:
    enabled: true
    source: database

    database:
      path: auto
      read_only: true

report:
  timezone: Asia/Taipei
  default_days: 7
  output_directory: ./reports
  formats:
    - markdown
    - json

repositories:
  grouping_strategy: git_repository

  identity:
    primary: origin_remote
    fallbacks:
      - git_common_dir
      - harness_project_id
      - normalized_path

  mappings:
    git:github.com/mike/assets-tracker:
      name: Assets Tracker

extraction:
  max_activity_chars: 5000
  max_tool_result_chars: 3000
  max_error_chars: 2000

security:
  redact_secrets: true
  exclude_patterns:
    - "*.env"
    - ".env.*"
    - "*credentials*"
    - "*secret*"
    - "*.pem"
    - "*.key"

llm:
  enabled: true
  provider: openai-compatible
  model: gpt-5-mini
  base_url: https://api.openai.com/v1
  api_key_env: OPENAI_API_KEY
  timeout_seconds: 60
```

Configuration precedence：

```text
CLI
    → environment variables
    → project config
    → user config
    → defaults
```

---

## 23. Repository Structure

```text
agent-worklog/
├── src/
│   └── agent_worklog/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── exceptions.py
│       ├── logging.py
│       │
│       ├── harnesses/
│       │   ├── base.py
│       │   ├── capabilities.py
│       │   ├── registry.py
│       │   └── opencode/
│       │       ├── source.py
│       │       ├── db.py
│       │       ├── locator.py
│       │       ├── schema.py
│       │       ├── adapters/
│       │       │   └── current.py
│       │       └── mapper.py
│       │
│       ├── models/
│       │   ├── session.py
│       │   ├── evidence.py
│       │   ├── repository.py
│       │   └── report.py
│       │
│       ├── sessions/
│       │   ├── hierarchy.py
│       │   ├── filtering.py
│       │   └── deduplication.py
│       │
│       ├── repositories/
│       │   ├── resolver.py
│       │   ├── git.py
│       │   └── remote.py
│       │
│       ├── extraction/
│       │   ├── pipeline.py
│       │   ├── goals.py
│       │   ├── commands.py
│       │   ├── files.py
│       │   ├── errors.py
│       │   └── outcomes.py
│       │
│       ├── security/
│       │   └── redactor.py
│       │
│       ├── summarizers/
│       │   ├── base.py
│       │   ├── rule_based.py
│       │   └── openai_compatible.py
│       │
│       ├── renderers/
│       │   ├── base.py
│       │   ├── markdown.py
│       │   └── json.py
│       │
│       ├── services/
│       │   ├── doctor_service.py
│       │   ├── scan_service.py
│       │   ├── inspect_service.py
│       │   └── report_service.py
│       │
│       └── templates/
│           └── worklog.md.j2
│
├── tests/
│   ├── fixtures/
│   │   └── opencode/
│   ├── unit/
│   └── integration/
│
├── docs/
│   └── mvp-design.md
├── pyproject.toml
├── README.md
├── LICENSE
└── CHANGELOG.md
```

---

## 24. Packaging

```toml
[project]
name = "agent-worklog"
version = "0.1.0"
description = "Turn coding-agent sessions into repository-based engineering reports"
requires-python = ">=3.11"

dependencies = [
  "typer>=0.16",
  "pydantic>=2.0",
  "pydantic-settings>=2.0",
  "platformdirs>=4.0",
  "PyYAML>=6.0",
  "Jinja2>=3.1",
  "httpx>=0.28",
  "rich>=14.0",
]

[project.scripts]
agent-worklog = "agent_worklog.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Recommended installation：

```bash
pipx install agent-worklog
```

Development：

```bash
uv sync
uv run agent-worklog doctor
```

---

## 25. Error Handling

### 25.1 Error Types

```python
class AgentWorklogError(Exception):
    pass


class ConfigurationError(AgentWorklogError):
    pass


class HarnessSourceError(AgentWorklogError):
    pass


class UnsupportedSchemaError(HarnessSourceError):
    pass


class SessionParseError(HarnessSourceError):
    pass


class RepositoryResolutionError(AgentWorklogError):
    pass


class SummarizationError(AgentWorklogError):
    pass


class RenderingError(AgentWorklogError):
    pass
```

### 25.2 Exit Codes

```text
0  Success
1  Unexpected error
2  Invalid CLI usage
3  Configuration error
4  No sessions found
5  Harness source error
6  Unsupported harness schema
7  Report generation failed
```

### 25.3 Partial Failure

- 單一 session 失敗：skip + warning
- 單一 repository resolution 失敗：fallback identity
- LLM 失敗：rule-based fallback
- OpenCode schema 不支援：provider fails fast
- 所有 sessions 失敗：command failure
- 部分 sessions 成功：產生 report 並列 warnings

---

## 26. Logging

Default：

```text
Locating OpenCode database...
Querying activities from 2026-07-23 to 2026-07-29...
Found 18 logical sessions across 4 repositories.
Generating repository summaries...
Report written to reports/worklog-2026-07-23_2026-07-29.md
```

Verbose can show：

- DB path
- Schema adapter
- Candidate/session counts
- Skipped sessions
- Repository resolution method
- LLM fallback
- Redaction count

Logs must not show：

- API keys
- Authorization headers
- Full session content
- Full environment
- Credentials embedded in Git remotes

---

## 27. Performance

Target MVP scale：

```text
Sessions:             1,000
Activities:           100,000
Repositories:         100
OpenCode DB size:     5 GB
```

Targets：

- Candidate scan for 100 recent sessions: under 10 seconds
- No-LLM report: under 30 seconds
- Memory target: under 500 MB
- Stream or page DB rows
- Do not load all transcript content before filtering
- Limit tool output size
- Query only required columns
- Avoid N+1 queries where schema supports batch loading

MVP can process sequentially. Parallel parsing is deferred until profiling proves necessary.

---

## 28. Testing Strategy

### 28.1 Unit Tests

- Date range parser
- Timezone handling
- Half-open interval
- Capability model
- OpenCode DB locator
- Schema detection
- Row-to-session mapping
- Parent/child hierarchy
- Activity filtering
- Activity deduplication
- Git remote normalization
- Worktree grouping
- Deleted path fallback
- Goal/command/file/error/outcome extraction
- Secret redaction
- Rule summarizer
- Markdown renderer
- JSON schema

### 28.2 OpenCode DB Fixtures

```text
tests/fixtures/opencode/
├── supported-current.db
├── unsupported-schema.db
├── malformed-session.db
├── multi-project.db
├── parent-child.db
├── old-session-recent-activity.db
├── recent-session-outside-range.db
└── secret-containing.db
```

Fixtures must be synthetic and contain no real company data.

### 28.3 Integration Tests

```text
OpenCode fixture DB
    → discover
    → load
    → hierarchy
    → date filter
    → repository grouping
    → extraction
    → redaction
    → summary
    → rendering
```

### 28.4 Required Scenarios

```text
test_queries_sessions_across_all_projects
test_scan_does_not_depend_on_current_directory
test_includes_old_session_with_recent_activity
test_historical_range_includes_session_updated_later
test_groups_worktrees_by_git_remote
test_does_not_merge_same_repo_name_different_owner
test_child_sessions_are_not_double_counted
test_unknown_sessions_are_not_merged
test_secret_never_reaches_llm_mock
test_unsupported_schema_has_actionable_error
test_llm_failure_falls_back_to_rule_summary
```

### 28.5 LLM Tests

CI must use mocked HTTP transport.

Test：

- Valid structured response
- Invalid JSON
- Timeout
- 429
- 500
- Retry
- Rule fallback
- Redacted input

---

## 29. MVP Acceptance Criteria

### Installation

- `pipx install agent-worklog` installs CLI.
- `agent-worklog --help` succeeds.
- Linux and macOS supported.
- Windows is best effort.

### OpenCode Source

- Auto-locates or accepts explicit OpenCode DB.
- Opens DB read-only.
- Detects supported schema.
- Queries all projects.
- Does not depend on current directory.
- A malformed session does not abort the entire scan.

### Date Filtering

- Supports `--days 7`.
- Supports absolute `--since` and `--until`.
- Uses activity timestamps.
- Includes sessions created before the range.
- Handles sessions updated after historical range end.
- Uses Asia/Taipei by default.

### Session Hierarchy

- Parent and child sessions form one logical session.
- Child evidence is retained.
- Child sessions are not double-counted.
- Orphan children remain reportable.

### Repository Grouping

- Primary identity is normalized Git origin.
- SSH and HTTPS remotes for the same repo merge.
- Worktrees merge.
- Branches do not split projects.
- Same basename with different owner does not merge.
- Missing remote falls back to Git common dir.
- Deleted path falls back to harness identity/path.
- Unknown sessions are not all merged.

### Evidence and Security

- Extracts goals, commands, files, errors, outcomes.
- Redacts common secrets.
- Excluded file contents are not loaded.
- Full transcript is not sent to LLM.
- Logs never print secrets.

### Reports

- Generates Markdown.
- Generates JSON.
- Works with `--no-llm`.
- LLM failure falls back.
- Includes repository sections, completed work, resolved problems, in-progress work, harness counts, branches, and metrics.

### Quality

- Core unit coverage target: at least 80%.
- No live LLM calls in CI.
- Provider fixtures cover cross-project and historical queries.
- Public models have schema versioning.

---

## 30. Implementation Phases

### Phase 1 — Foundation

- Python package
- Typer CLI
- Config
- Domain models
- Exceptions/logging
- `init` and `doctor` shell

Deliverable：

```bash
agent-worklog --help
agent-worklog init
agent-worklog doctor
```

### Phase 2 — OpenCode DB Source

- DB locator
- Read-only connection
- Schema detection
- Current schema adapter
- Candidate discovery
- Session/message/part mapper
- Synthetic fixtures

Deliverable：

```bash
agent-worklog scan --harness opencode --days 7
```

### Phase 3 — Logical Sessions and Time Filtering

- Parent/child hierarchy
- Activity deduplication
- Exact date filtering
- Timezone handling
- Historical range behavior

Deliverable：

```bash
agent-worklog inspect <session-id> --show-hierarchy
```

### Phase 4 — Repository Grouping

- Working directory resolver
- Git origin normalization
- Git common dir fallback
- Worktree support
- Mapping aliases
- Display collision handling

Deliverable：

```bash
agent-worklog scan --days 7 --verbose
```

### Phase 5 — Evidence and Security

- Goal extractor
- Command extractor
- File extractor
- Error extractor
- Outcome extractor
- Noise reduction
- Secret redaction

Deliverable：

```bash
agent-worklog inspect <session-id> --show-evidence
```

### Phase 6 — Report Generation

- Repository aggregation
- Rule summarizer
- Markdown renderer
- JSON renderer
- Metrics/warnings

Deliverable：

```bash
agent-worklog report --days 7 --no-llm
```

### Phase 7 — LLM and Release

- OpenAI-compatible summarizer
- Structured output
- Retry/fallback
- README and examples
- CI
- PyPI workflow
- Release `0.1.0`

Deliverable：

```bash
agent-worklog report --days 7
```

---

## 31. Future Harness Adapters

### 31.1 Codex

Recommended hybrid source：

```text
SQLite metadata/index
    + JSONL rollout scan fallback
    → canonical AgentSession
```

Rationale：

- SQLite can accelerate candidate discovery.
- Transcript JSONL is needed as a recovery/source fallback.
- Adapter must handle index/transcript drift.
- Adapter must deduplicate replayed or forked history.

Proposed modules：

```text
harnesses/codex/
├── source.py
├── sqlite_catalog.py
├── jsonl_catalog.py
├── transcript.py
└── mapper.py
```

### 31.2 Claude Code

Recommended initial source：

```text
Transcript directory scan
    → JSONL parser
    → canonical AgentSession
```

Optional future source：

```text
SessionStart/PostToolUse/Stop/SessionEnd hooks
    → Agent Worklog event index
```

Proposed modules：

```text
harnesses/claude_code/
├── source.py
├── transcript_catalog.py
├── transcript.py
├── hook_index.py
└── mapper.py
```

### 31.3 Common Pipeline

Adding a harness must not require changes to：

- Repository resolver
- Evidence models
- Redaction
- Summarizers
- Renderers
- Report schema

Only provider-specific parsing and capabilities should change.

---

## 32. Future Enhancements

- SQLite cache owned by Agent Worklog
- Incremental scans
- Repository mapping cache for deleted worktrees
- Codex adapter
- Claude Code adapter
- OpenCode API adapter
- HTML report
- Google Docs output
- Git commit and PR correlation
- Azure DevOps Work Item correlation
- Slack/email delivery
- Team aggregation
- Scheduled reports
- Daily/monthly presets
- Report templates
- Multiple languages
- Harness event ingestion hooks

Suggested Agent Worklog cache tables：

```text
source_sessions
logical_sessions
repository_mappings
session_evidence
session_summaries
report_runs
```

Cache key：

```text
harness
+ session_id
+ source_updated_at
+ adapter_version
+ extractor_version
+ prompt_version
+ model
```

---

## 33. Risks and Mitigations

### OpenCode Internal Schema Changes

**Risk:** Direct DB access depends on internal schema.

**Mitigation:**

- Schema adapter
- Runtime schema detection
- Read-only access
- Unsupported-schema error
- Fixture per supported schema
- Optional API adapter later

### Missing or Inaccurate Activity Timestamps

**Risk:** Some records may lack exact timestamp.

**Mitigation:**

- Timestamp fallback hierarchy
- Inferred timestamp marker
- Warnings
- Exclude unresolvable activity from precise range

### Deleted Repositories or Worktrees

**Risk:** Git commands cannot resolve old session paths.

**Mitigation:**

- Harness project ID fallback
- Path fallback
- Future repository mapping cache

### Duplicate History

**Risk:** Forks, subagents, or resumed transcripts may replay prior content.

**Mitigation:**

- Parent/child logical sessions
- Stable activity IDs
- Provider-specific deduplication
- Do not sum usage when source semantics are cumulative

### Sensitive Data Leakage

**Risk:** Session content may include secrets or proprietary code.

**Mitigation:**

- Local-first
- Multi-stage redaction
- Content limits
- Excluded files
- Structured evidence only
- No raw transcript logging

### Misleading Summaries

**Risk:** LLM may overstate completion.

**Mitigation:**

- Evidence-grounded structured input
- Structured output
- Deterministic fallback
- Explicit confidence/unknown handling
- No unsupported inference

---

## 34. Validated External Assumptions

The design intentionally isolates external implementation details behind adapters. The following assumptions were checked against current upstream documentation and source material on 2026-07-29:

1. OpenCode exposes project, session, message, child-session, and diff operations through its server API.
2. Current OpenCode implementations persist shared session/application state in SQLite and allow the DB location to be overridden.
3. OpenCode session records include project/session hierarchy and directory-related metadata in current source schemas.
4. Claude Code hooks provide session ID, transcript path, current working directory, and hook event metadata.
5. Codex local session implementations use both SQLite state/index data and rollout JSONL files; adapters should not assume either source is always complete.

These are provider assumptions, not core domain requirements. Changes upstream should require a provider adapter update rather than changes to the common report pipeline.

---

## 35. Final MVP Definition

Agent Worklog v0.1 is complete when the following flow works reliably:

```text
OpenCode global DB
    → query all sessions with activity in a requested range
    → normalize sessions and child-session hierarchy
    → resolve canonical Git repositories
    → group activity by repository
    → extract and redact evidence
    → generate deterministic or LLM-assisted summaries
    → render Markdown and JSON worklogs
```

The MVP should stay focused on:

```text
One supported harness
One canonical session model
One repository grouping model
One useful worklog pipeline
```

Codex and Claude Code support should be enabled by the architecture, but implemented only after OpenCode v0.1 is stable.
