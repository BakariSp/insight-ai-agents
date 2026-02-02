---
name: executing-plans
description: Execute implementation plans in controlled batches with checkpoints, verification, and user feedback between each batch.
autoApply: true
---

# Executing Plans

**Announce at start:** "I'm using the executing-plans skill to implement this plan."

## Purpose

Execute an existing implementation plan methodically -- in batches, with verification at every step, and with explicit user checkpoints between batches.

## Branch Safety

**Never start implementation on `main` or `master` without explicit user consent.** If the current branch is `main` or `master`, ask the user to confirm or specify a feature branch before proceeding.

## Execution Protocol

### Step 1: Load and Review Plan

1. **Read the plan** in its entirety.
2. **Identify concerns** before writing any code:
   - Are there ambiguous steps?
   - Are there missing dependencies or prerequisites?
   - Are there tasks that conflict with the current codebase?
   - Are file paths still accurate?
3. **Raise issues** with the user before starting. Do not silently work around gaps.

If the plan is sound, confirm: "Plan reviewed. No blocking issues found. Beginning execution."

### Step 2: Execute Batch

Execute tasks in batches. Default batch size is **3 tasks** unless the user specifies otherwise.

For each task in the batch:

1. **Mark the task as `in_progress`** in the todo list.
2. **Follow the plan steps exactly.** Do not improvise, skip steps, or reorder.
3. **Run all verification commands** specified in the plan.
4. **Mark the task as `completed`** only when verification passes.

If a task's verification fails:

- Stop the batch.
- Report the failure with full output.
- Wait for user guidance.

### Step 3: Report

After each batch, present a checkpoint report:

```
## Batch Report

### Completed
- Task 1: <description> -- PASSED
- Task 2: <description> -- PASSED
- Task 3: <description> -- PASSED

### Verification Output
<paste relevant test output, build output, or command results>

### Issues Encountered
<any warnings, deviations, or concerns>
```

End every report with: **"Ready for feedback."**

Wait for the user to respond before continuing.

### Step 4: Continue

1. **Apply any feedback** the user provides (code changes, plan adjustments, re-ordering).
2. **Execute the next batch** following the same protocol.
3. **Repeat** until all tasks are complete.

### Step 5: Complete Development

When all tasks are done:

1. **Run the full test suite** and report results.
2. **Run linters and formatters** if configured.
3. **Present final options:**
   - Create a pull request
   - Run additional integration tests
   - Continue with the next plan

## Mandatory Stop Conditions

**STOP executing immediately** when any of these occur:

- **Hit a blocker** -- a dependency is missing, a service is down, or a required file does not exist.
- **Plan has critical gaps** -- a step is too vague to execute without guessing.
- **Instruction is unclear** -- you are unsure what the plan intends.
- **Verification fails repeatedly** -- the same test fails after two honest attempts.
- **Scope creep** -- a task requires changes far beyond what the plan describes.

When stopped, explain why and ask for guidance. Do not attempt workarounds without user approval.

## Principles

- **Fidelity to the plan.** The plan is the source of truth. If the plan is wrong, fix the plan first.
- **Transparency.** Show verification output. Never summarize away failures.
- **User control.** The user decides when to continue, pivot, or stop.
- **Small batches.** Frequent checkpoints catch problems early.

---

*Adapted from [obra/superpowers](https://github.com/obra/superpowers)*
