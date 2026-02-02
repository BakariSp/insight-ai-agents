---
name: systematic-debugging
description: Systematic debugging methodology that requires root cause investigation before any fix is attempted. Follows a four-phase protocol of investigation, pattern analysis, hypothesis testing, and verified implementation.
autoApply: true
---

# Systematic Debugging

## Core Mandate

**NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.**

Do not propose a fix until you understand **why** the bug exists. Guessing is not debugging. Changing code until tests pass is not debugging. Debugging is a disciplined investigation.

## Phase 1: Root Cause Investigation

Before touching any code, complete these steps:

### 1. Read the Error

- Read the **full** error message, stack trace, and log output.
- Do not skim. Do not jump to conclusions from the error type alone.
- Note the exact file, line number, and error description.

### 2. Reproduce Reliably

- Run the failing test or trigger the error condition.
- Confirm you can reproduce the failure **consistently**.
- If it is intermittent, identify what conditions trigger it (timing, data, concurrency).

```bash
# Reproduce the failure
pytest tests/test_module.py::test_failing_case -x -v
```

### 3. Review Recent Changes

- Check `git log` and `git diff` for recent changes to the affected area.
- Ask: "What changed since this last worked?"
- Narrow the window: use `git bisect` if the introduction point is unclear.

### 4. Gather Diagnostics

- Add targeted logging or print statements at key decision points.
- Inspect variable values at the point of failure.
- Check configuration, environment variables, and external dependencies.

### 5. Trace Data Flow Backward

- Start at the error location and trace **backward** through the code.
- Follow the data: where did the bad value come from?
- Identify the **first** point where the data diverges from the expected path.

## Phase 2: Pattern Analysis

### 1. Find Working Examples

- Identify similar functionality in the codebase that **works correctly**.
- Look for existing tests that cover analogous behavior.

### 2. Study Reference Implementations

- Read the documentation for the library, framework, or API involved.
- Look at official examples or well-known open-source usage of the same pattern.

### 3. Compare Differences

- Diff the broken code against the working examples.
- Focus on structural differences, not cosmetic ones.
- Ask: "What does the working code do that the broken code does not?"

### 4. Understand Dependencies

- Map the dependency chain of the broken component.
- Check for version mismatches, missing configurations, or incorrect initialization order.
- Verify that all assumptions the code makes about its dependencies are still true.

## Phase 3: Hypothesis and Testing

### 1. Form Explicit Hypotheses

State your hypothesis clearly before changing anything:

> "The failure occurs because `X` returns `None` when `Y` is empty, and the caller does not handle `None`."

Do not write vague hypotheses like "something is wrong with the data."

### 2. Make Minimal Changes

- Test **one hypothesis at a time**.
- Make the **smallest possible change** to verify or falsify the hypothesis.
- Do not combine multiple fixes into one change.

### 3. Verify Results

- Run the failing test after each change.
- If the hypothesis was wrong, **revert the change** before trying the next hypothesis.
- Keep a log of what you tried and what happened.

## Phase 4: Implementation

Once the root cause is confirmed:

### 1. Create a Failing Test

Write a test that **reproduces the bug**. This test must fail before the fix and pass after.

### 2. Implement a Single Fix

- Fix the **root cause**, not the symptom.
- One fix, one commit, one clear explanation.

### 3. Verify Completely

- The new test passes.
- All existing tests pass.
- The original error no longer occurs.

## Escalation: Question the Architecture

**If 3 or more fix attempts have failed**, stop patching and ask bigger questions:

- Is the component designed correctly for this use case?
- Is there a fundamental assumption that is wrong?
- Should this be rewritten rather than patched?
- Is the test itself testing the wrong thing?

Raise these questions with the user before continuing.

## Red Flags

Stop and reassess if you catch yourself doing any of these:

- **Proposing a fix without investigation.** You have not earned a fix yet. Investigate first.
- **Making multiple simultaneous changes.** One change at a time. Otherwise you cannot know what fixed it.
- **Skipping test creation.** Every bug fix must produce a regression test.
- **Saying "try this and see if it works."** That is guessing, not debugging.
- **Changing code you do not understand.** Read it until you understand it, then change it.

---

*Adapted from [obra/superpowers](https://github.com/obra/superpowers)*
