"""Detailed E2E Test — Full chain with comprehensive output.

Runs a complete flow: Teacher Request → Blueprint → Page
with detailed JSON output for analysis.

Usage:
    python scripts/detailed_e2e_test.py
"""

import asyncio
import json
import sys
import io
from datetime import datetime
from pathlib import Path

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure data source - set before any imports
# Set to "true" for mock data (guaranteed data), "false" for real Java backend
import os
os.environ.setdefault("USE_MOCK_DATA", "true")  # Default to mock for reliable testing


async def run_detailed_e2e_test():
    """Run a detailed E2E test and save complete outputs."""
    from agents.planner import generate_blueprint
    from agents.executor import ExecutorAgent
    from services.java_client import get_java_client

    print("=" * 80)
    print("DETAILED E2E TEST — Complete Chain Analysis")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 80)

    # Start Java client
    java_client = get_java_client()
    await java_client.start()

    results = {
        "timestamp": datetime.now().isoformat(),
        "test_case": "detailed_e2e",
        "steps": [],
    }

    try:
        # ══════════════════════════════════════════════════════════
        # STEP 1: Generate Blueprint from Teacher Request
        # ══════════════════════════════════════════════════════════
        print("\n" + "─" * 80)
        print("STEP 1: Generate Blueprint")
        print("─" * 80)

        # Simple prompt with explicit assignment selection requirement
        user_prompt = "分析某个班级某次作业的成绩：显示平均分、最高分、最低分、成绩分布图表，给出分析总结和教学建议。让我先选择班级，再选择作业。"

        print(f"\n📝 User Prompt:\n{user_prompt}\n")

        blueprint, model_name = await generate_blueprint(
            user_prompt=user_prompt,
            language="zh-CN",
        )

        # Convert to dict for full inspection
        blueprint_dict = blueprint.model_dump(by_alias=True, mode="json")

        print(f"✅ Blueprint Generated: {blueprint.name}")
        print(f"   ID: {blueprint.id}")
        print(f"   Model: {model_name}")
        print(f"   Capability Level: {blueprint.capability_level}")

        # Data Contract details
        print(f"\n📊 Data Contract:")
        print(f"   Inputs: {len(blueprint.data_contract.inputs)}")
        for inp in blueprint.data_contract.inputs:
            print(f"      - {inp.id}: {inp.type} ({inp.label})")
        print(f"   Bindings: {len(blueprint.data_contract.bindings)}")
        for bind in blueprint.data_contract.bindings:
            print(f"      - {bind.id}: {bind.tool_name}")

        # Compute Graph details
        print(f"\n🔧 Compute Graph:")
        print(f"   Nodes: {len(blueprint.compute_graph.nodes)}")
        for node in blueprint.compute_graph.nodes:
            print(f"      - {node.id}: {node.type} → {node.output_key}")

        # UI Composition details
        print(f"\n🎨 UI Composition:")
        print(f"   Layout: {blueprint.ui_composition.layout}")
        print(f"   Tabs: {len(blueprint.ui_composition.tabs)}")
        for tab in blueprint.ui_composition.tabs:
            print(f"      - {tab.label}: {len(tab.slots)} blocks")
            for slot in tab.slots:
                ai_marker = " [AI]" if slot.ai_content_slot else ""
                print(f"         • {slot.component_type.value}{ai_marker}")

        results["steps"].append({
            "step": "1_blueprint_generation",
            "input": {"user_prompt": user_prompt, "language": "zh-CN"},
            "output": {
                "model": model_name,
                "blueprint": blueprint_dict,
            },
        })

        # ══════════════════════════════════════════════════════════
        # STEP 2: Execute Blueprint → Generate Page
        # ══════════════════════════════════════════════════════════
        print("\n" + "─" * 80)
        print("STEP 2: Execute Blueprint → Generate Page")
        print("─" * 80)

        # Context with mock data IDs for testing with data
        # When USE_MOCK_DATA=true, use mock IDs; otherwise use real Java IDs
        import os
        use_mock = os.getenv("USE_MOCK_DATA", "false").lower() == "true"

        if use_mock:
            context = {
                "teacherId": "t-001",
                "classId": "class-hk-f1a",
                "assignmentId": "a-001",  # Mock: Unit 5 Test with 5 students
            }
        else:
            context = {
                "teacherId": "2fe869fb-4a2d-4aa1-a173-c263235dc62b",
                "classId": "1e4fd110-0d58-4daa-a048-ee691fc7bef4",
                "assignmentId": "assign-87174785-e2a9-462b-97e1-008554ea1f5c",
            }

        print(f"\n📋 Execution Context:")
        print(f"   Teacher ID: {context['teacherId']}")
        print(f"   Class ID: {context['classId']}")
        print(f"   Assignment ID: {context['assignmentId']}")

        executor = ExecutorAgent()

        all_events = []
        final_page = None
        final_result = None

        print("\n⏳ Executing Blueprint...")
        print("─" * 40)

        async for event in executor.execute_blueprint_stream(blueprint, context):
            all_events.append(event)
            event_type = event.get("type")

            if event_type == "PHASE":
                print(f"   📌 Phase: {event.get('phase')} - {event.get('message')}")
            elif event_type == "TOOL_CALL":
                print(f"   🔧 Tool Call: {event.get('tool')} ({event.get('args', {})})")
            elif event_type == "TOOL_RESULT":
                status = event.get("status")
                print(f"   📦 Tool Result: {event.get('tool')} → {status}")
            elif event_type == "BLOCK_START":
                print(f"   🎯 Block Start: {event.get('blockId')} ({event.get('componentType')})")
            elif event_type == "SLOT_DELTA":
                delta = event.get("deltaText", "")
                preview = delta[:100] + "..." if len(delta) > 100 else delta
                print(f"   📝 Slot Delta: {preview}")
            elif event_type == "BLOCK_COMPLETE":
                print(f"   ✅ Block Complete: {event.get('blockId')}")
            elif event_type == "COMPLETE":
                status = event.get("message")
                print(f"   🏁 Complete: {status}")
                final_result = event.get("result", {})
                final_page = final_result.get("page")
            elif event_type == "ERROR" or event_type == "DATA_ERROR":
                print(f"   ❌ Error: {event.get('message')}")

        print("─" * 40)

        results["steps"].append({
            "step": "2_page_generation",
            "input": {"context": context},
            "output": {
                "event_count": len(all_events),
                "event_types": list(set(e.get("type") for e in all_events)),
                "final_status": final_result.get("chatResponse") if final_result else None,
                "page": final_page,
                "all_events": all_events,
            },
        })

        # ══════════════════════════════════════════════════════════
        # STEP 3: Output Summary
        # ══════════════════════════════════════════════════════════
        print("\n" + "─" * 80)
        print("STEP 3: Output Summary")
        print("─" * 80)

        if final_page:
            print(f"\n📄 Generated Page:")
            print(f"   Title: {final_page.get('meta', {}).get('pageTitle')}")
            print(f"   Layout: {final_page.get('layout')}")
            print(f"   Tabs: {len(final_page.get('tabs', []))}")

            for tab in final_page.get("tabs", []):
                print(f"\n   Tab: {tab.get('label')}")
                for i, block in enumerate(tab.get("blocks", [])):
                    block_type = block.get("type")
                    print(f"      Block {i+1}: {block_type}")

                    if block_type == "kpi_grid":
                        data = block.get("data", [])
                        print(f"         KPI Items: {len(data)}")
                        for item in data:
                            print(f"            • {item.get('label')}: {item.get('value')}")

                    elif block_type == "chart":
                        print(f"         Title: {block.get('title')}")
                        print(f"         Variant: {block.get('variant')}")
                        print(f"         X-Axis: {block.get('xAxis', [])}")

                    elif block_type == "table":
                        print(f"         Title: {block.get('title')}")
                        print(f"         Headers: {block.get('headers', [])}")
                        print(f"         Rows: {len(block.get('rows', []))}")

                    elif block_type == "markdown":
                        content = block.get("content", "")
                        preview = content[:200] + "..." if len(content) > 200 else content
                        print(f"         Content Preview: {preview}")

                    elif block_type == "suggestion_list":
                        items = block.get("items", [])
                        print(f"         Suggestions: {len(items)}")
                        for item in items[:3]:
                            print(f"            • {item.get('title')}")

        else:
            print("\n⚠️ No page generated!")
            if final_result:
                print(f"   Error: {final_result.get('chatResponse')}")

        # ══════════════════════════════════════════════════════════
        # Save complete results to file
        # ══════════════════════════════════════════════════════════
        output_dir = Path("docs/testing")
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / "detailed-e2e-results.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n📁 Full results saved to: {output_file}")

        # Also save formatted Blueprint
        blueprint_file = output_dir / "sample-blueprint.json"
        with open(blueprint_file, "w", encoding="utf-8") as f:
            json.dump(blueprint_dict, f, indent=2, ensure_ascii=False)
        print(f"📁 Blueprint saved to: {blueprint_file}")

        # Save formatted Page
        if final_page:
            page_file = output_dir / "sample-page.json"
            with open(page_file, "w", encoding="utf-8") as f:
                json.dump(final_page, f, indent=2, ensure_ascii=False)
            print(f"📁 Page saved to: {page_file}")

    finally:
        await java_client.close()

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_detailed_e2e_test())
