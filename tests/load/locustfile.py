"""Locust load test suite for Insight AI Agent service.

Usage:
    # Install dependencies first:
    pip install locust sseclient-py

    # Web UI mode (recommended for interactive testing):
    cd insight-ai-agent
    locust -f tests/load/locustfile.py --host http://localhost:5000

    # Headless mode (for CI/CD):
    locust -f tests/load/locustfile.py --host http://localhost:5000 \
        --headless -u 10 -r 2 --run-time 5m \
        --html tests/load/report.html

    # Run specific user class only:
    locust -f tests/load/locustfile.py ChatUser --host http://localhost:5000

Metrics recorded per endpoint:
    - Response time (p50, p95, p99)
    - TTFE (Time to First Event) for SSE endpoints
    - Stream duration for SSE endpoints
    - Error rate
    - Requests per second
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from locust import HttpUser, between, events, tag, task

logger = logging.getLogger(__name__)

# ─── Test data ──────────────────────────────────────────────────

# Simulated teacher IDs for testing
TEACHER_IDS = [
    "test-teacher-001",
    "test-teacher-002",
    "test-teacher-003",
]

# Chat messages (lightweight — single LLM call)
CHAT_MESSAGES = [
    "Hello, how are you?",
    "What can you help me with?",
    "你好，你能做什么？",
    "Tell me about your features",
]

# Build workflow prompts (heavy — multi-step pipeline)
BUILD_PROMPTS = [
    "Show me grade analysis for my class",
    "分析一下班级的作业完成情况",
    "Generate a performance report for all students",
    "Compare scores across different assignments",
]

# Quiz generation prompts (medium — streaming questions)
QUIZ_PROMPTS = [
    "Generate 5 math quiz questions about fractions for grade 6",
    "出10道关于二次方程的选择题",
    "Create a science quiz about photosynthesis",
]

# Content creation prompts (agent path — tool-use loop)
CONTENT_PROMPTS = [
    "Create a lesson plan about World War II",
    "Generate a worksheet on basic algebra",
    "帮我写一份关于光合作用的教案",
]


# ─── Custom metrics ─────────────────────────────────────────────

@events.init.add_listener
def on_locust_init(environment, **kwargs):
    """Register custom SSE metrics."""
    logger.info("Insight AI Agent load test initialized")


# ─── SSE helper ─────────────────────────────────────────────────

def consume_sse_stream(response) -> dict[str, Any]:
    """Consume an SSE stream and collect metrics.

    Returns dict with:
        - ttfe: Time to first event (seconds)
        - duration: Total stream duration (seconds)
        - event_count: Number of SSE events received
        - has_error: Whether an error event was received
        - last_event_type: Type of the last event
    """
    start = time.monotonic()
    ttfe = None
    event_count = 0
    has_error = False
    last_event_type = ""

    buffer = ""
    for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
        if chunk:
            buffer += chunk
            # Parse SSE lines
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                event_count += 1
                if ttfe is None:
                    ttfe = time.monotonic() - start

                # Try to detect event type from SSE data
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    try:
                        data = json.loads(data_str)
                        if isinstance(data, dict):
                            last_event_type = data.get("type", data.get("event", ""))
                            if last_event_type == "ERROR" or data.get("error"):
                                has_error = True
                    except (json.JSONDecodeError, TypeError):
                        pass

    duration = time.monotonic() - start
    return {
        "ttfe": ttfe or duration,
        "duration": duration,
        "event_count": event_count,
        "has_error": has_error,
        "last_event_type": last_event_type,
    }


# ═══════════════════════════════════════════════════════════════
# User classes — simulate different usage patterns
# ═══════════════════════════════════════════════════════════════


class HealthCheckUser(HttpUser):
    """Lightweight user that only hits the health endpoint.

    Use for baseline server capacity testing.
    Weight: 1 (low frequency)
    """

    weight = 1
    wait_time = between(1, 3)

    @tag("health", "baseline")
    @task
    def health_check(self):
        with self.client.get(
            "/api/health",
            name="GET /api/health",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") != "healthy":
                    resp.failure(f"Unhealthy: {data}")
            else:
                resp.failure(f"Status {resp.status_code}")


class ChatUser(HttpUser):
    """Simulates teachers doing casual chat interactions.

    This is the lightest AI workload — single LLM call via RouterAgent + ChatAgent.
    Expected latency: 2-8s per request.
    Weight: 5 (most common interaction)
    """

    weight = 5
    wait_time = between(10, 30)  # Teachers think between messages

    def on_start(self):
        self.teacher_id = TEACHER_IDS[self.environment.runner.user_count % len(TEACHER_IDS)]
        self.conversation_id = None

    @tag("chat", "lightweight")
    @task(3)
    def chat_json(self):
        """Test the JSON conversation endpoint (legacy)."""
        import random

        payload = {
            "message": random.choice(CHAT_MESSAGES),
            "language": "en",
            "teacherId": self.teacher_id,
        }
        if self.conversation_id:
            payload["conversationId"] = self.conversation_id

        with self.client.post(
            "/api/conversation",
            json=payload,
            name="POST /api/conversation (chat)",
            catch_response=True,
            timeout=30,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                self.conversation_id = data.get("conversationId")
                if not data.get("chatResponse"):
                    resp.failure("Empty chat response")
            else:
                resp.failure(f"Status {resp.status_code}: {resp.text[:200]}")

    @tag("chat", "sse", "stream")
    @task(2)
    def chat_stream(self):
        """Test the SSE conversation stream endpoint."""
        import random

        payload = {
            "message": random.choice(CHAT_MESSAGES),
            "language": "en",
            "teacherId": self.teacher_id,
        }
        if self.conversation_id:
            payload["conversationId"] = self.conversation_id

        with self.client.post(
            "/api/conversation/stream",
            json=payload,
            name="SSE /api/conversation/stream (chat)",
            catch_response=True,
            stream=True,
            timeout=60,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Status {resp.status_code}")
                return

            metrics = consume_sse_stream(resp)
            if metrics["has_error"]:
                resp.failure(f"SSE stream error after {metrics['event_count']} events")
            elif metrics["event_count"] == 0:
                resp.failure("Empty SSE stream")
            else:
                logger.info(
                    "Chat stream: TTFE=%.2fs, Duration=%.2fs, Events=%d",
                    metrics["ttfe"],
                    metrics["duration"],
                    metrics["event_count"],
                )


class WorkflowUser(HttpUser):
    """Simulates teachers generating Blueprint workflows.

    Medium workload — single PlannerAgent LLM call with structured output.
    Expected latency: 5-15s per request.
    Weight: 3
    """

    weight = 3
    wait_time = between(30, 60)  # Less frequent than chat

    @tag("workflow", "blueprint", "medium")
    @task
    def generate_workflow(self):
        """Test Blueprint generation endpoint."""
        import random

        payload = {
            "userPrompt": random.choice(BUILD_PROMPTS),
            "language": "en",
            "teacherId": TEACHER_IDS[0],
        }

        with self.client.post(
            "/api/workflow/generate",
            json=payload,
            name="POST /api/workflow/generate",
            catch_response=True,
            timeout=60,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if not data.get("blueprint"):
                    resp.failure("Missing blueprint in response")
            elif resp.status_code == 502:
                resp.failure(f"Blueprint generation failed: {resp.text[:200]}")
            else:
                resp.failure(f"Status {resp.status_code}")


class BuildUser(HttpUser):
    """Simulates the full build pipeline: conversation/stream → build_workflow intent.

    Heavy workload — RouterAgent + PlannerAgent + ExecutorAgent (3 phases).
    Expected latency: 30-120s per request.
    Weight: 2
    """

    weight = 2
    wait_time = between(60, 120)  # Infrequent — heavy operation

    @tag("build", "heavy", "sse", "e2e")
    @task
    def build_full_pipeline(self):
        """Test the full build pipeline via conversation/stream."""
        import random

        payload = {
            "message": random.choice(BUILD_PROMPTS),
            "language": "en",
            "teacherId": TEACHER_IDS[0],
            "context": {
                "teacherId": TEACHER_IDS[0],
                "classId": "test-class-001",
            },
        }

        with self.client.post(
            "/api/conversation/stream",
            json=payload,
            name="SSE /api/conversation/stream (build)",
            catch_response=True,
            stream=True,
            timeout=180,  # Build can take up to 3 minutes
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Status {resp.status_code}")
                return

            metrics = consume_sse_stream(resp)
            if metrics["has_error"]:
                resp.failure(
                    f"Build stream error after {metrics['duration']:.1f}s, "
                    f"{metrics['event_count']} events"
                )
            elif metrics["event_count"] < 3:
                resp.failure(
                    f"Too few events ({metrics['event_count']}) — "
                    f"expected at least intent+blueprint+completion"
                )
            else:
                logger.info(
                    "Build stream: TTFE=%.2fs, Duration=%.2fs, Events=%d",
                    metrics["ttfe"],
                    metrics["duration"],
                    metrics["event_count"],
                )


class QuizUser(HttpUser):
    """Simulates quiz generation via conversation/stream.

    Medium-heavy workload — RouterAgent + QuizSkill streaming.
    Expected latency: 10-30s per request.
    Weight: 2
    """

    weight = 2
    wait_time = between(45, 90)

    @tag("quiz", "sse", "skill")
    @task
    def generate_quiz(self):
        """Test quiz generation via conversation stream."""
        import random

        payload = {
            "message": random.choice(QUIZ_PROMPTS),
            "language": "en",
            "teacherId": TEACHER_IDS[0],
        }

        with self.client.post(
            "/api/conversation/stream",
            json=payload,
            name="SSE /api/conversation/stream (quiz)",
            catch_response=True,
            stream=True,
            timeout=120,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Status {resp.status_code}")
                return

            metrics = consume_sse_stream(resp)
            if metrics["has_error"]:
                resp.failure(f"Quiz stream error: {metrics['event_count']} events")
            else:
                logger.info(
                    "Quiz stream: TTFE=%.2fs, Duration=%.2fs, Events=%d",
                    metrics["ttfe"],
                    metrics["duration"],
                    metrics["event_count"],
                )


class MixedUser(HttpUser):
    """Realistic mixed workload simulating a typical teacher session.

    Follows a realistic usage pattern:
    1. Health check on load
    2. Multiple chat messages
    3. Occasionally generate a workflow
    4. Rarely do a full build

    Weight: 10 (primary user type for realistic simulation)
    """

    weight = 10
    wait_time = between(5, 20)

    def on_start(self):
        self.teacher_id = TEACHER_IDS[0]
        self.conversation_id = None
        # Initial health check
        self.client.get("/api/health")

    @tag("mixed", "chat")
    @task(6)
    def chat(self):
        """Most common action — casual chat."""
        import random

        payload = {
            "message": random.choice(CHAT_MESSAGES),
            "language": "en",
            "teacherId": self.teacher_id,
        }
        if self.conversation_id:
            payload["conversationId"] = self.conversation_id

        with self.client.post(
            "/api/conversation/stream",
            json=payload,
            name="SSE /api/conversation/stream (mixed-chat)",
            catch_response=True,
            stream=True,
            timeout=30,
        ) as resp:
            if resp.status_code == 200:
                metrics = consume_sse_stream(resp)
                if metrics["has_error"]:
                    resp.failure("Stream error")
            else:
                resp.failure(f"Status {resp.status_code}")

    @tag("mixed", "workflow")
    @task(2)
    def workflow(self):
        """Less common — generate a Blueprint."""
        import random

        payload = {
            "userPrompt": random.choice(BUILD_PROMPTS),
            "language": "en",
            "teacherId": self.teacher_id,
        }

        with self.client.post(
            "/api/workflow/generate",
            json=payload,
            name="POST /api/workflow/generate (mixed)",
            catch_response=True,
            timeout=60,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Status {resp.status_code}")

    @tag("mixed", "build")
    @task(1)
    def build(self):
        """Rare — full build pipeline."""
        import random

        payload = {
            "message": random.choice(BUILD_PROMPTS),
            "language": "en",
            "teacherId": self.teacher_id,
            "context": {
                "teacherId": self.teacher_id,
                "classId": "test-class-001",
            },
        }

        with self.client.post(
            "/api/conversation/stream",
            json=payload,
            name="SSE /api/conversation/stream (mixed-build)",
            catch_response=True,
            stream=True,
            timeout=180,
        ) as resp:
            if resp.status_code == 200:
                metrics = consume_sse_stream(resp)
                if metrics["has_error"]:
                    resp.failure("Build stream error")
            else:
                resp.failure(f"Status {resp.status_code}")
