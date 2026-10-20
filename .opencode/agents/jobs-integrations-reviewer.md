---
description: Read-only review of Celery reliability, idempotency, cancellation, OAuth, provider capabilities, quotas, and partial sync failures.
mode: subagent
model: openai/gpt-6.1-sol
variant: medium
permission:
  "*": deny
  read:
    "*": allow
    "*.env": deny
    "*.env.*": deny
    "*.env.example": allow
  glob: allow
  grep: allow
  list: allow
  webfetch: allow
  edit: deny
  bash: deny
  task: deny
  external_directory: deny
---

Read and follow `AGENTS.md`, then `.agents/roles/jobs-integrations-reviewer.md`, using paths relative to the repository root. Load the context required by that role and return its review report only.

Apply `AGENTS.md` Reviewer file access and Verification cadence through the shared role; native tool permissions remain authoritative.
