---
name: test-driven-development
description: Enforce strict Test-Driven Development methodology. No production code is written without a failing test first. Red-Green-Refactor is the only allowed workflow.
autoApply: true
---

# Test-Driven Development

## The Iron Law

**NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.**

There are no exceptions. There are no shortcuts. If production code exists without a corresponding test that failed before the code was written, delete the code and start over.

## The Red-Green-Refactor Cycle

Every unit of work follows this exact sequence:

### RED: Write One Failing Test

- Write **one** minimal test for **one** behavior.
- The test must be specific: it tests a single input-output pair, a single side effect, or a single error condition.
- The test must **fail** when you run it. If it passes immediately, something is wrong.

```bash
# Run the test
pytest tests/test_feature.py::test_specific_behavior -x
# Expected: FAIL
```

### Verify RED (MANDATORY)

**You must run the test and confirm it fails for the expected reason.**

This step is not optional. Do not skip it. Do not assume it fails. Run it and read the output.

- Confirm the failure is because the feature is **not yet implemented**, not because of a syntax error, import error, or misconfigured test.
- If the test fails for the wrong reason, fix the test first.

### GREEN: Write the Simplest Code to Pass

- Write the **minimum** production code required to make the failing test pass.
- Do not add extra logic, future-proofing, or "while I'm here" improvements.
- Do not refactor yet.

```bash
# Run the test again
pytest tests/test_feature.py::test_specific_behavior -x
# Expected: PASS
```

### Verify GREEN (MANDATORY)

**You must run the test and confirm it passes.**

Then confirm that **all other existing tests still pass**:

```bash
# Run the full suite
pytest
# Expected: ALL PASS
```

If any test broke, fix it before moving on. Never leave the suite red.

### REFACTOR: Clean Up (Green Only)

- Only refactor when the test suite is fully green.
- Improve code structure, naming, duplication -- without changing behavior.
- Run the full test suite after every refactoring change.
- If any test fails during refactoring, **undo immediately** and try a smaller refactor.

## What Makes a Good Test

- **Minimal** -- Tests one thing. No setup beyond what is strictly necessary.
- **Clear** -- The test name and body explain the expected behavior without comments.
- **Shows intent** -- Reading the test tells you what the code is supposed to do, not how it does it.

```python
# Good: clear, minimal, intent-revealing
def test_empty_cart_has_zero_total():
    cart = Cart()
    assert cart.total() == 0

# Bad: tests multiple things, unclear intent
def test_cart():
    cart = Cart()
    cart.add(Item("A", 10))
    cart.add(Item("B", 20))
    assert cart.total() == 30
    cart.remove("A")
    assert cart.total() == 20
    assert len(cart.items) == 1
```

## Red Flags -- Start Over When You See These

- **Code before test.** You wrote production code first. Delete it. Write the test.
- **Test passes immediately.** The behavior already exists or the test is wrong. Investigate before proceeding.
- **"Just this once" rationalization.** There is no "just this once." The discipline is the value.
- **Multiple behaviors in one test.** Split it into separate tests.
- **Test depends on implementation details.** Test behavior, not internals.

## Bug Fix Pattern

When fixing a bug, follow this sequence:

1. **Write a failing test** that reproduces the bug exactly.
2. **Verify RED** -- confirm the test fails and demonstrates the bug.
3. **Fix the bug** with the minimum code change.
4. **Verify GREEN** -- confirm the test passes and the bug is fixed.
5. **Run the full suite** -- confirm nothing else broke.

## Verification Checklist Before Marking Complete

Before claiming any task is done:

- [ ] A failing test was written **before** the production code.
- [ ] The test was run and confirmed to fail for the expected reason.
- [ ] The production code was written to make the test pass.
- [ ] The test was run and confirmed to pass.
- [ ] The full test suite was run and all tests pass.
- [ ] Any refactoring was done only while green, with tests run after each change.

---

*Adapted from [obra/superpowers](https://github.com/obra/superpowers)*
