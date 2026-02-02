"""Live conversation test script — sends real requests to the running server.

Captures full request/response pairs for documentation purposes.
"""

import asyncio
import io
import json
import sys
import time

import httpx

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_URL = "http://localhost:5000"
OUTPUT_FILE = "docs/phase4-7-conversation-log.md"

# Sample blueprint for follow-up mode tests (must match Blueprint model schema)
SAMPLE_BLUEPRINT = {
    "id": "bp-live-test",
    "name": "Form 1A English Performance",
    "description": "Analyze English scores for Form 1A class",
    "capabilityLevel": 1,
    "sourcePrompt": "分析 1A 班英语成绩",
    "dataContract": {
        "inputs": [
            {
                "id": "class",
                "type": "class",
                "label": "Class",
                "required": True,
            },
            {
                "id": "assignment",
                "type": "assignment",
                "label": "Assignment",
                "required": True,
                "dependsOn": "class",
            },
        ],
        "bindings": [
            {
                "id": "submissions",
                "sourceType": "tool",
                "toolName": "get_assignment_submissions",
                "paramMapping": {
                    "teacher_id": "$context.teacherId",
                    "assignment_id": "$input.assignment",
                },
                "description": "Fetch all student submissions",
            }
        ],
    },
    "computeGraph": {
        "nodes": [
            {
                "id": "stats",
                "type": "tool",
                "toolName": "calculate_stats",
                "toolArgs": {
                    "data": "$data.submissions.scores",
                    "metrics": ["mean", "median", "min", "max", "stddev"],
                },
            }
        ]
    },
    "uiComposition": {
        "layout": "single",
        "tabs": [
            {
                "id": "overview",
                "label": "Overview",
                "slots": [
                    {
                        "id": "kpi",
                        "componentType": "kpi_grid",
                        "dataBinding": "$compute.stats",
                    }
                ],
            }
        ],
    },
}


log_lines: list[str] = []


def log(text: str = ""):
    print(text)
    log_lines.append(text)


def truncate_blueprint(data: dict) -> dict:
    """Return a shallow copy with blueprint truncated for readability."""
    if not data:
        return data
    out = dict(data)
    bp = out.get("blueprint")
    if bp and isinstance(bp, dict):
        out["blueprint"] = f"<Blueprint id={bp.get('id')} name={bp.get('name')!r} ...>"
    return out


async def send_request(
    client: httpx.AsyncClient,
    label: str,
    payload: dict,
    truncate_bp_in_request: bool = False,
) -> tuple[dict, float, int]:
    """Send a POST /api/conversation request and return (response_data, elapsed, status)."""
    log(f"\n### {label}")
    log()

    # Show request
    display_payload = payload
    if truncate_bp_in_request and "blueprint" in payload:
        display_payload = dict(payload)
        display_payload["blueprint"] = "<SAMPLE_BLUEPRINT -- see above>"

    log("**Request** `POST /api/conversation`")
    log("```json")
    log(json.dumps(display_payload, ensure_ascii=False, indent=2))
    log("```")

    start = time.time()
    resp = await client.post("/api/conversation", json=payload)
    elapsed = time.time() - start

    log(f"\n**Response** `{resp.status_code}` ({elapsed:.2f}s)")
    try:
        data = resp.json()
        # For display: truncate large blueprint in response
        display_data = truncate_blueprint(data)
        log("```json")
        log(json.dumps(display_data, ensure_ascii=False, indent=2))
        log("```")
    except Exception:
        log(f"```\n{resp.text}\n```")
        data = {}

    return data, elapsed, resp.status_code


async def main():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        # Health check
        health = await client.get("/api/health")
        log(f"Health check: `{json.dumps(health.json())}`")

        results = []

        log("\n---\n")
        log("## A. Initial Mode (no blueprint)")

        # ── 1. chat_smalltalk ──
        r1, t1, s1 = await send_request(client, "Test 1: Smalltalk (chat_smalltalk)", {
            "message": "你好",
            "language": "zh-CN",
        })
        results.append(("chat_smalltalk", r1, t1, s1))

        # ── 2. chat_qa ──
        r2, t2, s2 = await send_request(client, "Test 2: Knowledge QA (chat_qa)", {
            "message": "KPI是什么意思？",
            "language": "zh-CN",
        })
        results.append(("chat_qa", r2, t2, s2))

        # ── 3. clarify ──
        r3, t3, s3 = await send_request(client, "Test 3: Vague Request (clarify)", {
            "message": "分析英语表现",
            "language": "zh-CN",
            "teacherId": "t-001",
            "conversationId": "conv-live-001",
        })
        results.append(("clarify", r3, t3, s3))

        # ── 4. build_workflow ──
        r4, t4, s4 = await send_request(client, "Test 4: Clear Request (build_workflow)", {
            "message": "分析 Form 1A 班英语 Unit 5 考试成绩，需要包含平均分、中位数、分数分布图和学生成绩表格",
            "language": "zh-CN",
            "teacherId": "t-001",
        })
        results.append(("build_workflow", r4, t4, s4))

        log("\n---\n")
        log("## B. Follow-up Mode (with blueprint)")
        log()
        log("All follow-up tests use this blueprint context:")
        log("```json")
        log(json.dumps({"id": SAMPLE_BLUEPRINT["id"], "name": SAMPLE_BLUEPRINT["name"], "description": SAMPLE_BLUEPRINT["description"]}, ensure_ascii=False, indent=2))
        log("```")

        # ── 5. followup chat ──
        r5, t5, s5 = await send_request(
            client,
            "Test 5: Follow-up Chat (chat)",
            {
                "message": "哪些学生的成绩需要重点关注？",
                "language": "zh-CN",
                "blueprint": SAMPLE_BLUEPRINT,
                "pageContext": {
                    "mean": 74.2,
                    "median": 72.0,
                    "min": 58,
                    "max": 95,
                    "lowestStudent": "Wong Ka Ho (58)",
                },
            },
            truncate_bp_in_request=True,
        )
        results.append(("followup_chat", r5, t5, s5))

        # ── 6. refine ──
        r6, t6, s6 = await send_request(
            client,
            "Test 6: Refine (refine)",
            {
                "message": "只显示不及格的学生（低于60分）",
                "language": "zh-CN",
                "blueprint": SAMPLE_BLUEPRINT,
            },
            truncate_bp_in_request=True,
        )
        results.append(("refine", r6, t6, s6))

        # ── 7. rebuild ──
        r7, t7, s7 = await send_request(
            client,
            "Test 7: Rebuild (rebuild)",
            {
                "message": "加一个语法分析模块，分析学生在语法题上的错误类型分布",
                "language": "zh-CN",
                "blueprint": SAMPLE_BLUEPRINT,
            },
            truncate_bp_in_request=True,
        )
        results.append(("rebuild", r7, t7, s7))

        # ── Summary table ──
        log("\n---\n")
        log("## C. Summary")
        log()
        log("| # | Test | Status | Action | Time | Blueprint | ChatResponse | ClarifyOptions |")
        log("|---|------|--------|--------|------|-----------|-------------|----------------|")
        for i, (label, data, elapsed, status_code) in enumerate(results, 1):
            action = data.get("action", "ERROR")
            ok = "PASS" if status_code == 200 else f"FAIL ({status_code})"
            has_bp = "Yes" if data.get("blueprint") else "No"
            has_chat = "Yes" if data.get("chatResponse") else "No"
            has_clarify = "Yes" if data.get("clarifyOptions") else "No"
            log(f"| {i} | {label} | {ok} | `{action}` | {elapsed:.2f}s | {has_bp} | {has_chat} | {has_clarify} |")

        # Write markdown file
        header = [
            "# Phase 4.7 — AI Router Live Conversation Log",
            "",
            f"> Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"> Server: {BASE_URL}",
            f"> Model: dashscope/qwen-max",
            "",
        ]
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(header + log_lines))

        print(f"\n[Written to {OUTPUT_FILE}]")


if __name__ == "__main__":
    asyncio.run(main())
