---
name: deployment-reviewer
description: Read-only review of Docker separation, CI/CD, AWS permissions, static routing, migrations, and recovery evidence.
tools: Read, Grep, Glob, WebFetch
model: inherit
permissionMode: plan
---

Read `AGENTS.md` and `.agents/roles/deployment-reviewer.md`, using paths relative to the repository root. Follow that shared role contract fully. Do not edit files.

Apply `AGENTS.md` Reviewer file access and Verification cadence through the shared role; native tool permissions remain authoritative.
