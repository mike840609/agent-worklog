# Releasing Agent Worklog

Agent Worklog publishes wheels and source distributions to PyPI through GitHub Actions and PyPI Trusted Publishing. No long-lived PyPI API token is stored in GitHub.

The repository's default and release branch is `main`.

## One-time PyPI setup

Create a Pending Trusted Publisher on PyPI with these exact values:

| Field | Value |
|---|---|
| PyPI project name | `agent-worklog` |
| GitHub owner | `mike840609` |
| Repository | `agent-worklog` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

Then create a GitHub repository environment named `pypi` under **Settings → Environments**. Adding required reviewers is recommended so production releases require explicit approval.

## Verify a release without publishing

Run the `Release` workflow manually from GitHub Actions. A manual run builds and validates the distributions, but the publish job is skipped.

The build job runs:

```bash
uv sync --locked --extra dev
uv run pytest --cov=agent_worklog --cov-fail-under=80
uv run ruff check .
uv run pyright
uv build
uv tool run twine check dist/*
```

## Publish a version

1. Update `[project].version` in `pyproject.toml`.
2. Regenerate and commit `uv.lock` with `uv lock`.
3. Merge the version change into `main`.
4. Create an annotated tag that exactly matches the package version.
5. Push the tag.

For version `0.1.0`:

```bash
git checkout main
git pull --ff-only
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

The workflow verifies that `v0.1.0` matches `version = "0.1.0"`, builds the package, publishes it through OIDC, and creates a GitHub Release containing the distributions.

PyPI versions are immutable. A corrected release must use a new version such as `0.1.1`; an existing file or version cannot be overwritten.

## Install after publication

```bash
pip install agent-worklog
```

For the CLI, isolated installation is preferred:

```bash
pipx install agent-worklog
# or
uv tool install agent-worklog
```
