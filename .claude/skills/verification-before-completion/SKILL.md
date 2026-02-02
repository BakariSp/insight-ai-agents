---
name: verification-before-completion
description: Verification protocol that prohibits any success or completion claims without fresh, concrete evidence. Every claim must be backed by actual command output from the current session.
autoApply: true
---

# Verification Before Completion

## Core Mandate

**NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE.**

Never say "done," "complete," "passing," or "working" without running the verification commands **in this session** and showing the output. Memory of a previous run does not count. Assumptions do not count. Only fresh evidence counts.

## The Five-Step Gate

Every completion claim must pass through all five steps in order:

### 1. Identify

Determine **exactly** what needs to be verified:

- Which tests must pass?
- Which build commands must succeed?
- Which linters or formatters must report clean?
- Which endpoints must respond correctly?
- Which acceptance criteria must be met?

Write the list down before running anything.

### 2. Run

Execute every verification command. Do not skip any.

```bash
# Example verification sequence
pytest tests/ -v              # unit and integration tests
python -m mypy src/           # type checking
python -m flake8 src/         # linting
python -m build               # build succeeds
```

Run them **now**, in this session. Do not rely on earlier runs.

### 3. Read

Read the **full output** of every command. Do not scan for "PASSED" and move on.

- Check for warnings that indicate hidden problems.
- Check for skipped tests that should have run.
- Check for deprecation notices that may cause future failures.
- Check that the number of tests matches expectations.

### 4. Verify

Confirm that every item on the identification list from Step 1 is satisfied:

- All specified tests pass.
- Build completes without errors.
- Linters report clean (or only known/accepted warnings).
- All acceptance criteria are met.

If **any** item fails, do not proceed to Step 5. Fix the issue and restart from Step 2.

### 5. Claim

Only now may you claim completion. When you do:

- **State what was verified**, not just "it works."
- **Include the evidence** -- paste command output or key excerpts.
- **Be specific** -- "All 47 tests pass" not "tests pass."

## Rules

### Evidence Before Claims, Always

The order is always: run command, read output, then make claim. Never the reverse.

### Never Claim Tests Pass Without Running Them

"The tests should pass" is not verification. Run them.

### Never Assume Linter Success Means Build Success

They check different things. Run both.

### Never Use Hedging Language

These phrases are banned in completion claims:

- "should work"
- "probably passes"
- "I believe this is correct"
- "this looks good"
- "I think we're done"

Replace them with evidence-backed statements:

- "All 47 tests pass (output above)."
- "Build completed successfully with exit code 0."
- "Linter reports 0 errors, 0 warnings."

### Applies to ALL Success Claims

This protocol applies every time you claim something is:

- Complete
- Fixed
- Working
- Passing
- Ready for review
- Done

No matter how small the change, no matter how confident you are, run the verification.

### No Shortcuts

- "I just ran it a minute ago" -- Run it again.
- "It's a trivial change" -- Verify it.
- "The test already existed" -- Run it to confirm it still passes.
- "Nothing else could have broken" -- Prove it.

## Verification Report Template

When reporting completion, use this structure:

```
## Verification Report

### Commands Run
1. `pytest tests/ -v` -- 47 passed, 0 failed, 0 skipped
2. `flake8 src/` -- 0 errors, 0 warnings
3. `python -m build` -- exit code 0

### Evidence
<paste key output sections>

### Conclusion
All verification checks passed. Implementation is complete.
```

---

*Adapted from [obra/superpowers](https://github.com/obra/superpowers)*
