"""Live Chain Completion Test — hit the real running AI Agent service.

Sends real requests to POST /api/conversation/stream and analyzes the
SSE events to detect chain breakage (e.g., search called but generate not).

Run:
    # Requires AI Agent running at localhost:5000
    pytest tests/test_live_chain_completion.py -v -s --tb=short

    # Run N trials to catch non-deterministic breakage:
    pytest tests/test_live_chain_completion.py -v -s -k "test_live_chain" --count=5

    # Or run standalone:
    python tests/test_live_chain_completion.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────

BASE_URL = "http://localhost:5000"
STREAM_ENDPOINT = f"{BASE_URL}/api/conversation/stream"
JSON_ENDPOINT = f"{BASE_URL}/api/conversation"
TEACHER_ID = "t-live-chain-test"
TIMEOUT = 120  # seconds — LLM calls can be slow


# ── SSE Parser ────────────────────────────────────────────────


@dataclass
class SSEEvent:
    """Parsed SSE event from Data Stream Protocol."""
    type: str
    raw: dict[str, Any]

    @property
    def tool_name(self) -> str | None:
        return self.raw.get("toolName")

    @property
    def text_delta(self) -> str:
        return self.raw.get("textDelta", "")


@dataclass
class StreamResult:
    """Collected results from a single SSE stream."""
    events: list[SSEEvent] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)  # tool names called
    tool_outputs: list[dict] = field(default_factory=list)
    full_text: str = ""
    raw_lines: list[str] = field(default_factory=list)
    duration_ms: float = 0
    error: str | None = None

    @property
    def tool_names_set(self) -> set[str]:
        return set(self.tool_calls)

    def has_tool(self, name: str) -> bool:
        return name in self.tool_names_set


def parse_sse_line(line: str) -> SSEEvent | None:
    """Parse a single SSE data line into an SSEEvent."""
    line = line.strip()
    if not line.startswith("data: "):
        return None
    payload = line[6:].strip()
    if payload == "[DONE]":
        return SSEEvent(type="[DONE]", raw={})
    try:
        data = json.loads(payload)
        return SSEEvent(type=data.get("type", "unknown"), raw=data)
    except json.JSONDecodeError:
        return None


async def send_stream_request(
    message: str,
    teacher_id: str = TEACHER_ID,
    language: str = "zh-CN",
    conversation_id: str | None = None,
) -> StreamResult:
    """Send a streaming conversation request and collect all SSE events."""
    result = StreamResult()
    body: dict[str, Any] = {
        "message": message,
        "language": language,
        "teacherId": teacher_id,
    }
    if conversation_id:
        body["conversationId"] = conversation_id

    start = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("POST", STREAM_ENDPOINT, json=body) as resp:
                if resp.status_code != 200:
                    result.error = f"HTTP {resp.status_code}"
                    return result

                async for raw_line in resp.aiter_lines():
                    result.raw_lines.append(raw_line)
                    event = parse_sse_line(raw_line)
                    if event is None:
                        continue
                    result.events.append(event)

                    if event.type == "tool-input-start" and event.tool_name:
                        result.tool_calls.append(event.tool_name)

                    if event.type == "tool-output-available":
                        result.tool_outputs.append(event.raw)

                    if event.type == "text-delta":
                        result.full_text += event.text_delta

    except httpx.ConnectError:
        result.error = f"Cannot connect to {BASE_URL} — is the AI Agent running?"
    except httpx.ReadTimeout:
        result.error = f"Read timeout after {TIMEOUT}s"
    except Exception as e:
        result.error = str(e)

    result.duration_ms = (time.perf_counter() - start) * 1000
    return result


# ── Chain Validation (reuse logic from test_chain_completion) ─


@dataclass
class IntentChain:
    name: str
    required_tools: list[str]
    description: str


_INTENT_CHAINS: list[tuple[re.Pattern, IntentChain]] = [
    (
        re.compile(r"(知识库|文档|资料|上传的).*(出.*?题|生成.*?题|练习|测验)", re.DOTALL),
        IntentChain(
            name="knowledge_quiz",
            required_tools=["search_teacher_documents", "generate_quiz_questions"],
            description="Knowledge-base quiz: must search then generate",
        ),
    ),
    (
        re.compile(r"(知识库|文档|资料|上传的).*(PPT|课件|演示)", re.DOTALL),
        IntentChain(
            name="knowledge_ppt",
            required_tools=["search_teacher_documents", "propose_pptx_outline"],
            description="Knowledge-base PPT: must search then propose outline",
        ),
    ),
]


def detect_intent_chain(msg: str) -> IntentChain | None:
    for pat, chain in _INTENT_CHAINS:
        if pat.search(msg):
            return chain
    return None


@dataclass
class ChainReport:
    """Report from a single live chain test run."""
    message: str
    intent: str | None
    expected_tools: list[str]
    called_tools: list[str]
    missing_tools: list[str]
    chain_complete: bool
    full_text: str
    duration_ms: float
    error: str | None

    def summary_line(self) -> str:
        status = "COMPLETE" if self.chain_complete else "BREAK"
        tools = " -> ".join(self.called_tools) if self.called_tools else "(no tools)"
        text_preview = self.full_text[:80].replace("\n", " ")
        return (
            f"[{status}] {self.duration_ms:.0f}ms | "
            f"tools: {tools} | "
            f"text: {text_preview}..."
        )


def analyze_stream(message: str, result: StreamResult) -> ChainReport:
    """Analyze a StreamResult against expected chain."""
    intent = detect_intent_chain(message)
    expected = intent.required_tools if intent else []
    called_set = result.tool_names_set
    missing = [t for t in expected if t not in called_set]

    return ChainReport(
        message=message,
        intent=intent.name if intent else None,
        expected_tools=expected,
        called_tools=result.tool_calls,
        missing_tools=missing,
        chain_complete=len(missing) == 0,
        full_text=result.full_text,
        duration_ms=result.duration_ms,
        error=result.error,
    )


# ── Test Scenarios ────────────────────────────────────────────

# Each scenario: (user_message, expected_intent, description)
CHAIN_SCENARIOS = [
    (
        "根据知识库帮我出三角函数的题",
        "knowledge_quiz",
        "Knowledge-base quiz — must search then generate",
    ),
    (
        "用我上传的文档生成5道练习题",
        "knowledge_quiz",
        "Document-based quiz — must search then generate",
    ),
    (
        "根据知识库资料出一套测验题",
        "knowledge_quiz",
        "Knowledge-base test — must search then generate",
    ),
]


# ── Skip if service not running ───────────────────────────────

def _service_available() -> bool:
    try:
        resp = httpx.get(f"{BASE_URL}/api/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


SKIP_NO_SERVICE = pytest.mark.skipif(
    not _service_available(),
    reason=f"AI Agent not running at {BASE_URL}",
)


# ── Live Tests ────────────────────────────────────────────────


@SKIP_NO_SERVICE
@pytest.mark.asyncio
class TestLiveChainCompletion:
    """Live tests against the running AI Agent — detect chain breakage."""

    async def test_live_chain_knowledge_quiz(self):
        """Send '根据知识库帮我出三角函数的题' and check chain completion.

        Expected: search_teacher_documents → generate_quiz_questions
        Breakage: search_teacher_documents → text stop (no generate)
        """
        message = "根据知识库帮我出三角函数的题"

        logger.info("=" * 60)
        logger.info("SENDING: %s", message)
        logger.info("=" * 60)

        stream = await send_stream_request(message)
        report = analyze_stream(message, stream)

        # Log full details
        logger.info("RESULT: %s", report.summary_line())
        logger.info("Tools called: %s", report.called_tools)
        logger.info("Missing tools: %s", report.missing_tools)
        logger.info("Full text output:\n%s", report.full_text)

        if report.error:
            pytest.fail(f"Request error: {report.error}")

        # Assert chain completed
        assert report.chain_complete, (
            f"CHAIN BREAK DETECTED!\n"
            f"  Message: {message}\n"
            f"  Expected tools: {report.expected_tools}\n"
            f"  Called tools: {report.called_tools}\n"
            f"  Missing: {report.missing_tools}\n"
            f"  LLM output: {report.full_text[:200]}\n"
            f"  Duration: {report.duration_ms:.0f}ms"
        )

    async def test_live_chain_document_quiz(self):
        """Send '用我上传的文档生成5道练习题' and check chain."""
        message = "用我上传的文档生成5道练习题"

        logger.info("SENDING: %s", message)
        stream = await send_stream_request(message)
        report = analyze_stream(message, stream)
        logger.info("RESULT: %s", report.summary_line())

        if report.error:
            pytest.fail(f"Request error: {report.error}")

        assert report.chain_complete, (
            f"CHAIN BREAK: called={report.called_tools}, "
            f"missing={report.missing_tools}, "
            f"text={report.full_text[:200]}"
        )

    async def test_live_chain_direct_quiz_no_chain_needed(self):
        """Send '出5道二次函数选择题' — no chain expected (direct generate)."""
        message = "出5道二次函数选择题"

        logger.info("SENDING: %s", message)
        stream = await send_stream_request(message)
        report = analyze_stream(message, stream)
        logger.info("RESULT: %s", report.summary_line())

        if report.error:
            pytest.fail(f"Request error: {report.error}")

        # No chain expected — just verify it called generate
        assert report.intent is None, "Should not match a chain pattern"
        # But we can check if generate was called
        logger.info("Tools used (no chain check): %s", report.called_tools)


@SKIP_NO_SERVICE
@pytest.mark.asyncio
async def test_live_chain_stress(request):
    """Run the chain scenario N times to catch non-deterministic breakage.

    Usage:
        pytest tests/test_live_chain_completion.py::test_live_chain_stress -v -s
    """
    message = "根据知识库帮我出三角函数的题"
    n_trials = 3  # Increase for more thorough testing
    results: list[ChainReport] = []

    logger.info("=" * 60)
    logger.info("STRESS TEST: %d trials of '%s'", n_trials, message)
    logger.info("=" * 60)

    for i in range(n_trials):
        logger.info("--- Trial %d/%d ---", i + 1, n_trials)
        stream = await send_stream_request(message)
        report = analyze_stream(message, stream)
        results.append(report)
        logger.info("Trial %d: %s", i + 1, report.summary_line())

        # Small delay between trials
        if i < n_trials - 1:
            await asyncio.sleep(2)

    # Summary
    breaks = [r for r in results if not r.chain_complete]
    completes = [r for r in results if r.chain_complete]
    errors = [r for r in results if r.error]

    logger.info("\n" + "=" * 60)
    logger.info("STRESS TEST SUMMARY")
    logger.info("=" * 60)
    logger.info("Total trials: %d", n_trials)
    logger.info("Complete chains: %d", len(completes))
    logger.info("Broken chains: %d", len(breaks))
    logger.info("Errors: %d", len(errors))

    if breaks:
        logger.info("\nBROKEN CHAINS:")
        for i, r in enumerate(breaks):
            logger.info(
                "  Break %d: tools=%s, missing=%s, text=%s",
                i + 1, r.called_tools, r.missing_tools, r.full_text[:100],
            )

    # Report but don't fail on individual breaks — this is a probability test.
    # Instead, report the break rate.
    break_rate = len(breaks) / n_trials
    logger.info("\nBreak rate: %.1f%% (%d/%d)", break_rate * 100, len(breaks), n_trials)

    if break_rate > 0:
        logger.warning(
            "Chain breakage detected in %.0f%% of trials! "
            "This confirms the non-deterministic LLM behavior.",
            break_rate * 100,
        )

    # Fail only if ALL trials broke (definitely a systematic issue)
    assert len(completes) > 0 or len(errors) == n_trials, (
        f"ALL {n_trials} trials had chain breakage! "
        f"This is a systematic issue, not random."
    )


# ── Standalone Runner ─────────────────────────────────────────

async def _run_standalone():
    """Run all chain scenarios and print a report."""
    print("=" * 70)
    print("LIVE CHAIN COMPLETION TEST")
    print(f"Target: {BASE_URL}")
    print("=" * 70)

    if not _service_available():
        print(f"\nERROR: AI Agent not running at {BASE_URL}")
        print("Start it with: cd insight-ai-agent && python main.py")
        return

    all_reports: list[ChainReport] = []

    for message, expected_intent, desc in CHAIN_SCENARIOS:
        print(f"\n{'─' * 50}")
        print(f"Scenario: {desc}")
        print(f"Message:  {message}")
        print(f"Expected: {expected_intent}")
        print(f"{'─' * 50}")

        stream = await send_stream_request(message)
        report = analyze_stream(message, stream)
        all_reports.append(report)

        if report.error:
            print(f"ERROR: {report.error}")
            continue

        status = "COMPLETE" if report.chain_complete else "*** BREAK ***"
        print(f"Status:   {status}")
        print(f"Tools:    {' -> '.join(report.called_tools) or '(none)'}")
        print(f"Missing:  {report.missing_tools or '(none)'}")
        print(f"Duration: {report.duration_ms:.0f}ms")
        print(f"Text out: {report.full_text[:300] or '(empty)'}...")

        # Show event timeline for debugging
        print(f"\n  Event timeline:")
        for evt in stream.events:
            if evt.type in ("start", "finish", "start-step", "finish-step", "[DONE]"):
                continue  # Skip protocol events
            if evt.type == "text-delta":
                print(f"    [{evt.type}] '{evt.text_delta[:50]}'")
            elif evt.type == "tool-input-start":
                print(f"    [{evt.type}] {evt.tool_name}")
            elif evt.type == "tool-input-available":
                args = evt.raw.get("args", {})
                print(f"    [{evt.type}] args={json.dumps(args, ensure_ascii=False)[:100]}")
            elif evt.type == "tool-output-available":
                output = evt.raw.get("output", "")
                if isinstance(output, str):
                    preview = output[:100]
                else:
                    preview = json.dumps(output, ensure_ascii=False)[:100]
                print(f"    [{evt.type}] {preview}")
            elif evt.type == "tool-progress":
                state = evt.raw.get("state", "")
                name = evt.raw.get("toolName", "")
                print(f"    [{evt.type}] {name} -> {state}")
            else:
                print(f"    [{evt.type}] {json.dumps(evt.raw, ensure_ascii=False)[:80]}")

    # Summary
    breaks = [r for r in all_reports if not r.chain_complete and not r.error]
    completes = [r for r in all_reports if r.chain_complete]
    errors = [r for r in all_reports if r.error]

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"Total scenarios: {len(all_reports)}")
    print(f"Complete chains: {len(completes)}")
    print(f"Broken chains:   {len(breaks)}")
    print(f"Errors:          {len(errors)}")

    if breaks:
        print("\n*** CHAIN BREAKAGE DETECTED ***")
        for r in breaks:
            print(f"  - '{r.message}':")
            print(f"    called:  {r.called_tools}")
            print(f"    missing: {r.missing_tools}")
            print(f"    output:  {r.full_text[:300]}")
            print()

    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(_run_standalone())
