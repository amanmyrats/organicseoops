---
description: Final-gate read-only security review only for explicitly marked implementation cards or direct user requests; not for routine coding or remediation.
mode: subagent
model: openai/gpt-6-luna
variant: medium
steps: 10
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

Read and follow `AGENTS.md`, then `.agents/roles/security-reviewer.md`, using paths relative to the repository root. For implementation review, first confirm that the supplied card has a `Security review gate` marker or that the user directly requested this reviewer. If neither is true, return `Security review not run: no explicit gate or user request.` without further repository search. Otherwise load only the bounded context required by that role and return its review report only.

Apply `AGENTS.md` Reviewer file access and Verification cadence through the shared role; native tool permissions remain authoritative.
