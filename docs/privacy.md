# Privacy and security

Agent Worklog is local-first, but coding-agent transcripts are sensitive inputs. This
document defines what the MVP protects and what remains the operator's responsibility.

## Data flow

1. Agent Worklog queries candidate session metadata with `opencode db`.
2. It requests each transcript with `opencode export <session-id> --sanitize`.
3. Transcript JSON is parsed in memory and filtered to the requested activity range.
4. Structured evidence is recursively redacted.
5. The redacted evidence is rendered locally or optionally sent to an OpenAI-compatible
   endpoint.
6. Markdown is written with an atomic replacement and owner-only `0600` permissions on
   POSIX systems.

Agent Worklog does not persist raw OpenCode exports. The secure writer may create a
short-lived sibling file during atomic report replacement; it is removed after completion
or failure.

## Redaction boundary

The redactor covers common patterns including:

- bearer and basic authorization values;
- OpenAI-style provider keys;
- GitHub tokens;
- AWS access keys and secret assignments;
- password, token, secret, and API-key assignments;
- credentials embedded in URLs and `curl -u` arguments;
- JWT-like tokens;
- private-key blocks.

Redaction is applied recursively to evidence metadata, before rendering, before verbose
warnings are written to reports, and before optional LLM requests.

Pattern-based redaction is not a proof that every secret has been removed. New credential
formats, arbitrary customer identifiers, source code, internal hostnames, filenames, and
business-sensitive descriptions may remain.

## OpenCode sanitization

Every transcript request includes `--sanitize`. This is a defense-in-depth input boundary,
not a replacement for Agent Worklog redaction. A command fails the acceptance suite if an
OpenCode export is invoked without that flag.

## Optional LLM use

An HTTP client is constructed only when LLM support is enabled, `--no-llm` is absent, and
the configured API-key environment variable exists. The payload contains canonical,
redacted evidence rather than raw transcripts or raw metadata.

The endpoint operator may retain requests according to its own policies. Use
`--no-llm` or set `AGENT_WORKLOG_LLM__ENABLED=false` when external processing is not
permitted.

## Reports remain sensitive

A generated report can still reveal proprietary information, including:

- project and repository names;
- user goals and feature descriptions;
- commands and test names;
- filenames and branch names;
- errors and unresolved work;
- the fact that particular repositories were active.

Treat reports as internal engineering records. Review them before posting to chat systems,
issue trackers, shared drives, or public repositories.

## Logs and partial failures

The CLI does not intentionally print raw transcripts, environment values, authorization
headers, or credentials embedded in remotes. Partial export failures are reported using
session IDs and redacted error text.

## Operator responsibilities

- Keep the OpenCode storage and generated reports protected by appropriate filesystem
  permissions.
- Do not enable an external LLM endpoint unless company policy permits it.
- Review generated content before distribution.
- Rotate any credential that appears unredacted and report the pattern so the redactor can
  be extended.
