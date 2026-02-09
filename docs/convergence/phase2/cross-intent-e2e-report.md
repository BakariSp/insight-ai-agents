# Phase2 Cross-Intent E2E Report

This report closes the Phase2 acceptance item:
- cross-scenario E2E switching (`quiz -> ppt -> interactive`)

## Data Sources

- Raw live data: `docs/testing/phase2-cross-intent-switch-live.json`
- Human-readable live summary: `docs/testing/phase2-cross-intent-switch-live.md`
- Memory-chain live data (single natural conversation): `docs/testing/phase2-memory-chain-live.json`
- Memory-chain live summary: `docs/testing/phase2-memory-chain-live.md`
- Content quality report: `docs/testing/phase2-live-content-quality-report.json`
- End-to-end integration results: `docs/testing/live-integration-results.json`

## Result

- Pass: Yes
- Conversation mode: single conversation id, multi-turn switching
- Sequence verified:
1. quiz turn -> `data-quiz-complete`
2. ppt turn -> `data-pptx-outline`
3. interactive turn -> `data-interactive-content`

## Key Metrics (latest run)

- Total runtime: `254571.48 ms`
- Turn 1 (quiz): `50863.96 ms`, events `25`
- Turn 2 (ppt): `50993.41 ms`, events `18`
- Turn 3 (interactive): `152709.89 ms`, events `1764`

## Memory-Chain Run (latest)

- Conversation ID: `phase2-memory-chain-004`
- Total runtime: `240647.52 ms`
- Sequence:
1. quiz turn -> `data-quiz-complete` (`53,683.99 ms`)
2. ppt turn (based on quiz) -> `data-pptx-outline` (`37,358.57 ms`)
3. interactive turn (based on PPT key points) -> `data-interactive-content` (`149,601.73 ms`)

## Notes

- Build workflow path remains independent and was not merged into unified agent loop (as designed for Phase2).
- Some environment warnings (`list_classes` empty) appeared during run, but did not block artifact generation or route switching.
- This report covers the non-clarify main chain (`quiz -> ppt -> interactive`).  
  Clarify continuity is tracked separately in `docs/convergence/phase2/clarify-fix-plan.md`, and is not yet marked as stable acceptance.
