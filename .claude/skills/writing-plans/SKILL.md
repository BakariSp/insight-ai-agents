---
name: writing-plans
description: Write detailed, step-by-step implementation plans before writing any code. Plans are saved to docs/plans/ and break work into bite-sized TDD tasks.
autoApply: true
---

# Writing Plans

**Announce at start:** "I'm using the writing-plans skill to create the implementation plan."

## Purpose

Create a comprehensive, step-by-step implementation plan **before** any code is written. The plan serves as a contract: every task is small, testable, and independently verifiable.

## Plan File Location

Save every plan to:

```
docs/plans/YYYY-MM-DD-<feature-name>.md
```

Use today's date and a short kebab-case feature name (e.g., `2026-02-02-user-auth.md`).

## Mandatory Plan Header

Every plan starts with this metadata block:

```markdown
# Plan: <Feature Name>

**Goal:** One-sentence description of what this plan delivers.
**Architecture:** How this feature fits into the existing system (components, services, data flow).
**Tech Stack:** Languages, frameworks, libraries, and tools involved.
**Date:** YYYY-MM-DD
```

## Plan Structure

### 1. Context and Constraints

- Summarize the current state of relevant code.
- List hard constraints (backwards compatibility, performance budgets, API contracts).
- Identify risks and unknowns.

### 2. Task Breakdown

Break the implementation into **bite-sized tasks**. Each task should take **2-5 minutes** to complete.

For every task, provide:

- **Description** -- what the task accomplishes in one sentence.
- **Exact file paths** -- every file that will be created or modified.
- **Complete code snippets** -- no pseudocode, no "add something like this."
- **Precise commands** -- exact test commands, build commands, migration commands.
- **Verification step** -- how to confirm the task is done correctly.

### 3. TDD Cycle Per Task

Each task follows this strict cycle:

1. **Write a failing test** -- one minimal test targeting one behavior.
2. **Verify the test fails** -- run it and confirm the failure reason.
3. **Implement the minimal code** -- only enough to make the test pass.
4. **Verify the test passes** -- run it and confirm green.
5. **Commit** -- atomic commit with a clear message.

### 4. Dependency Order

Order tasks so that each builds on the last. No task should require code from a later task. Mark explicit dependencies between tasks.

## Guiding Principles

- **DRY** -- Don't Repeat Yourself. If you see duplication in the plan, refactor the tasks.
- **YAGNI** -- You Aren't Gonna Need It. Only plan what is required to meet the goal.
- **TDD** -- Every production line is justified by a test.
- **Specificity over vagueness** -- If a step says "update the config," specify which config, which key, and what value.

## After Plan Completion

Once the plan is written and reviewed, offer the user two execution strategies:

1. **Subagent-Driven** -- A fresh subagent is spawned for each task. Best for isolation and clean context.
2. **Parallel Session** -- Multiple tasks are executed concurrently where dependencies allow. Best for speed.

Ask the user which approach they prefer before proceeding.

## Quality Checklist

Before presenting the plan:

- [ ] Every task has exact file paths.
- [ ] Every task has complete code snippets (no placeholders).
- [ ] Every task has a precise verification command.
- [ ] Tasks are ordered by dependency.
- [ ] Each task is completable in 2-5 minutes.
- [ ] The plan follows DRY, YAGNI, and TDD.
- [ ] The mandatory header is filled out completely.

---

*Adapted from [obra/superpowers](https://github.com/obra/superpowers)*
