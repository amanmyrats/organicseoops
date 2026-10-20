---
name: security-reviewer
description: Read-only security review only for explicitly marked implementation cards or direct user requests.
tools: Read, Grep, Glob, WebFetch
model: inherit
maxTurns: 10
permissionMode: plan
---

Read `AGENTS.md` and `.agents/roles/security-reviewer.md`, using paths relative to the repository root. Follow that shared role contract fully. Do not edit files.

Apply `AGENTS.md` Reviewer file access and Verification cadence through the shared role; native tool permissions remain authoritative.
