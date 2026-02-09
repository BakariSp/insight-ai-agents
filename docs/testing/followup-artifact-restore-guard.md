# Follow-up Artifact Restore Guard

Updated: 2026-02-08

## Background

`/api/conversation/stream` previously restored `artifact_type` from session whenever request payload omitted it.  
That behavior could route unrelated new-topic messages into artifact follow-up mode.

## Changes

- Added `_should_restore_artifact_type(message, artifact_type)` guard in `api/conversation.py`.
- Session `artifact_type` is now restored only when the message looks like an artifact follow-up (referential + follow-up intent).
- Router still receives artifact summary when restore is accepted.
- Added unit tests in `tests/test_conversation_stream.py` for positive and negative cases.

## Expected Result

- Follow-up messages like "把这个页面改成蓝色" still use artifact follow-up flow.
- Unrelated messages like "给我推荐三个课堂破冰游戏" no longer get forced into follow-up routing.
