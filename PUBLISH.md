# Publishing `lfx-keenable` to PyPI

This package publishes via **Trusted Publishing (OIDC)** — GitHub Actions mints
a short-lived identity token and PyPI trusts it, so **no API tokens or passwords
are stored**. The workflow is [`.github/workflows/publish.yml`](.github/workflows/publish.yml);
it runs when a GitHub **Release** is published. Same setup as `langchain-keenable`.

## One-time setup (PyPI account owner, once)

PyPI account needs a **verified email** + **2FA** first. Then at
**https://pypi.org/manage/account/publishing/** add a *pending publisher* with
exactly these values (a mismatch — usually the environment name — is the #1
cause of a silent "not a trusted publisher" failure):

| Field | Value |
|---|---|
| PyPI Project Name | `lfx-keenable` |
| Owner | `keenableai` |
| Repository name | `lfx-keenable` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

Then in the repo: **Settings → Environments → New environment → `pypi`**, and
add required reviewers so a release needs human approval before it publishes. No
GitHub secrets are needed.

## Cut a release

```bash
# in keenableai/lfx-keenable, on main:
# 1) bump `version` in pyproject.toml AND extension.json (keep them in sync)
git tag v0.1.0 && git push origin v0.1.0      # tag must match pyproject version
gh release create v0.1.0 --title v0.1.0 --notes "Initial release"
```

Publishing the Release triggers the workflow (build → `twine check` → OIDC
publish). Approve the `pypi` environment when prompted; on success the package
is live at https://pypi.org/project/lfx-keenable/.

## Pre-release checks (local)

```bash
rm -rf dist && uv build && uvx twine check dist/*
uv venv && . .venv/bin/activate
uv pip install "lfx>=1.10.0,<2.0.0" pytest -e .
pytest                                                # 35 passing, offline
lfx extension validate src/lfx_keenable --execute-imports   # validate: ok
```

## If it goes silent

- No signup verification email → Spam; resend from account settings; the link
  expires; try a personal email if `@keenable.ai` filters it.
- 2FA not enabled → you can't publish or make tokens; enable a TOTP app.
- Workflow runs but PyPI says "not a trusted publisher" → the pending-publisher
  fields don't match (env name `pypi` / workflow `publish.yml`).
- Same version re-upload → bump the version (and `extension.json`).

Manual token fallback (only if Actions is unavailable): create a token at
https://pypi.org/manage/account/token/ then `UV_PUBLISH_TOKEN=pypi-XXXX uv publish`
(user is `__token__`). Prefer the OIDC workflow.
