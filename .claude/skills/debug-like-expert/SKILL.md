---
name: "debug-like-expert"
description: "Methodical investigation protocol for complex debugging using the scientific method. Enforces evidence-based root cause analysis, eliminates guess-and-check, and requires full verification before declaring a fix."
autoApply: true
---

# Debug Like an Expert

## Core Mindset

**VERIFY, DON'T ASSUME.**

Treat code you wrote with heightened skepticism. Cognitive biases about intended behavior mask actual implementation errors. The code does what it does, not what you think it does. Read it as if someone else wrote it.

---

## Workflow: The Scientific Method for Debugging

### Phase 1: Evidence Gathering

Before forming any hypothesis, collect all available facts. Never skip this phase.

- **Document exact error messages and full stack traces.** Copy them verbatim. Do not paraphrase or summarize error output.
- **Write exact reproduction steps.** Record the precise CLI commands, API calls, user actions, or sequence of events that trigger the issue. If you cannot reproduce it, you cannot verify a fix.
- **Trace the execution path** from the entry point to the error location. Follow the actual call chain, not the one you expect.
- **Check logs, network requests, and application state at the time of failure.** Look at what actually happened, not what should have happened.
- **Read COMPLETE files.** Never scan or skim. Bugs hide in the lines you skip. If a file is relevant, read it in full.

### Phase 2: Root Cause Analysis

Apply structured reasoning to isolate the defect.

1. **Form 2-3 testable hypotheses**, ranked by likelihood based on the evidence gathered in Phase 1.
2. **Test each hypothesis systematically.** Change one variable per test. If you change multiple things, you cannot attribute the result to any single cause.
3. **Eliminate possibilities based on evidence.** Cross off hypotheses that the evidence contradicts. Do not hold onto a hypothesis that the data disproves.
4. **Check recent git changes near the error location.** Use `git log`, `git diff`, and `git blame` to identify what changed and when. Recent changes are statistically more likely to contain the defect.
5. **Look for common bug categories:**
   - Off-by-one errors
   - Null or undefined references
   - Race conditions and timing issues
   - Character encoding and string handling
   - Type coercion and implicit conversions
   - Boundary conditions and edge cases

### Phase 3: Solution Development

Fix the root cause, not the symptom.

1. **Write a failing test that reproduces the bug FIRST.** This test defines the acceptance criteria for the fix. If you cannot write a reproducing test, revisit Phase 1.
2. **Implement minimal, targeted changes.** The fix should be as small as possible while fully addressing the root cause. Avoid unrelated refactoring in the same change.
3. **Verify the fix passes the reproducing test.** The test written in step 1 must now pass.
4. **Run the original reproduction steps** from Phase 1 and confirm the issue is resolved end-to-end.
5. **Check for side effects in related functionality.** Run the full test suite. Manually verify adjacent features that share code paths with the fix.

---

## Domain Expertise Integration

Auto-detect the project type and apply language-specific debugging patterns.

### Python
- Check virtual environment activation and dependency versions (`pip list`, `pip freeze`).
- Verify import paths and module resolution. Watch for circular imports.
- Inspect indentation carefully; mixed tabs and spaces cause silent failures.
- For concurrency issues, consider GIL behavior, thread safety, and async/await correctness.
- Use `pdb`, `breakpoint()`, or strategic `print()` statements to inspect runtime state.
- Check for mutable default arguments, late binding closures, and iterator exhaustion.

### JavaScript / TypeScript
- Understand the event loop. Check for unhandled promise rejections and callback ordering.
- Verify promise chains: missing `await`, unhandled `.catch()`, and swallowed errors.
- Inspect variable scope and closures. Watch for `var` hoisting, stale closures in loops, and `this` binding.
- Check for strict equality issues (`===` vs `==`) and falsy value handling.
- For Node.js: verify `package.json` dependencies, module resolution, and environment variables.
- For browser: check CORS, CSP, DOM timing, and framework lifecycle hooks.

### General (All Languages)
- Verify environment variables are set and accessible.
- Check file paths, permissions, and line endings (CRLF vs LF).
- Confirm database connections, migrations, and schema state.
- Validate API contracts: request/response shapes, status codes, headers.

---

## Critical Success Criteria

ALL of the following must be true before declaring an issue fixed:

- [ ] **Understand WHY the issue occurred.** You can explain the root cause clearly to another developer.
- [ ] **Verify the fix actually resolves the issue.** The reproducing test passes.
- [ ] **Original reproduction steps pass.** End-to-end confirmation, not just unit-level.
- [ ] **Check for side effects.** Related functionality still works correctly.
- [ ] **Solution withstands code review.** The change is clean, minimal, and well-reasoned.
- [ ] **No "drive-by fixes" without explanation.** Every change in the diff is justified and documented.

If any criterion is not met, the issue is NOT fixed. Go back to the appropriate phase.

---

## Anti-Patterns: Never Do These

| Anti-Pattern | Why It Fails |
|---|---|
| **Guess-and-check without understanding** | Random changes waste time and can introduce new bugs. You must understand the system before changing it. |
| **Multiple changes at once** | When something improves, you cannot identify which change was responsible. When something breaks, you cannot isolate the cause. |
| **"It works now" without knowing why** | If you do not know why it works, you do not know if it will keep working. The fix may be coincidental or fragile. |
| **Blaming the environment without proof** | "It works on my machine" is not a diagnosis. Prove the environment is the cause with specific evidence, or keep investigating. |
| **Skipping reproduction steps** | If you cannot reproduce the bug, you cannot verify the fix. A fix without verification is a guess. |

---

## Quick Reference: Debugging Checklist

```
1. STOP. Read the error. Read it again.
2. Reproduce the issue. Document exact steps.
3. Read the relevant code IN FULL. Do not skim.
4. Form hypotheses. Rank them.
5. Test ONE thing at a time.
6. Find the root cause. Not a symptom.
7. Write a failing test.
8. Fix. Verify. Check side effects.
9. Explain WHY it broke and WHY the fix works.
```

---

*Adapted from [glittercowboy/taches-cc-resources](https://github.com/glittercowboy/taches-cc-resources)*
