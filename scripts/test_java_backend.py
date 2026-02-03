#!/usr/bin/env python
"""Test script to fetch real data from Java backend and record responses.

Usage:
    python scripts/test_java_backend.py

This script tests Phase 5 Java backend integration by fetching real data
for the specified teacher and recording the responses.
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_settings
from services.java_client import get_java_client, JavaClientError, CircuitOpenError


# Test user credentials
# User specified teacher (userId=3)
TEACHER_ID = "2fe869fb-4a2d-4aa1-a173-c263235dc62b"
USER_ID = 3

# DIFY account credentials (for auth)
DIFY_UID = "aced47cd-8534-492b-9ceb-4ea488ac2d8e"

# Output file for recording results
OUTPUT_FILE = Path(__file__).parent.parent / "docs" / "testing" / "java_backend_responses.json"


async def test_list_classes(client) -> dict:
    """Test GET /dify/teacher/{teacherId}/classes/me"""
    print(f"\n{'='*60}")
    print(f"TEST: List Classes for Teacher")
    print(f"  teacher_id: {TEACHER_ID}")
    print(f"  endpoint: GET /dify/teacher/{TEACHER_ID}/classes/me")
    print(f"{'='*60}")

    try:
        response = await client.get(f"/dify/teacher/{TEACHER_ID}/classes/me")
        print(f"[OK] Success! Response:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
        return {"status": "success", "data": response}
    except JavaClientError as e:
        print(f"[ERROR] {e}")
        return {"status": "error", "code": e.status_code, "detail": e.detail}
    except CircuitOpenError as e:
        print(f"[CIRCUIT OPEN] {e}")
        return {"status": "circuit_open", "detail": str(e)}
    except Exception as e:
        print(f"[EXCEPTION] {e}")
        return {"status": "exception", "detail": str(e)}


async def test_class_detail(client, class_id: str) -> dict:
    """Test GET /dify/teacher/{teacherId}/classes/{classId}"""
    print(f"\n{'='*60}")
    print(f"TEST: Get Class Detail")
    print(f"  teacher_id: {TEACHER_ID}")
    print(f"  class_id: {class_id}")
    print(f"  endpoint: GET /dify/teacher/{TEACHER_ID}/classes/{class_id}")
    print(f"{'='*60}")

    try:
        response = await client.get(f"/dify/teacher/{TEACHER_ID}/classes/{class_id}")
        print(f"[OK] Success! Response:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
        return {"status": "success", "data": response}
    except JavaClientError as e:
        print(f"[ERROR] Error: {e}")
        return {"status": "error", "code": e.status_code, "detail": e.detail}
    except Exception as e:
        print(f"[ERROR] Exception: {e}")
        return {"status": "exception", "detail": str(e)}


async def test_list_assignments(client, class_id: str) -> dict:
    """Test GET /dify/teacher/{teacherId}/classes/{classId}/assignments"""
    print(f"\n{'='*60}")
    print(f"TEST: List Assignments for Class")
    print(f"  teacher_id: {TEACHER_ID}")
    print(f"  class_id: {class_id}")
    print(f"  endpoint: GET /dify/teacher/{TEACHER_ID}/classes/{class_id}/assignments")
    print(f"{'='*60}")

    try:
        response = await client.get(f"/dify/teacher/{TEACHER_ID}/classes/{class_id}/assignments")
        print(f"[OK] Success! Response:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
        return {"status": "success", "data": response}
    except JavaClientError as e:
        print(f"[ERROR] Error: {e}")
        return {"status": "error", "code": e.status_code, "detail": e.detail}
    except Exception as e:
        print(f"[ERROR] Exception: {e}")
        return {"status": "exception", "detail": str(e)}


async def test_assignment_submissions(client, assignment_id: str) -> dict:
    """Test GET /dify/teacher/{teacherId}/submissions/assignments/{assignmentId}"""
    print(f"\n{'='*60}")
    print(f"TEST: Get Assignment Submissions")
    print(f"  teacher_id: {TEACHER_ID}")
    print(f"  assignment_id: {assignment_id}")
    print(f"  endpoint: GET /dify/teacher/{TEACHER_ID}/submissions/assignments/{assignment_id}")
    print(f"{'='*60}")

    try:
        response = await client.get(f"/dify/teacher/{TEACHER_ID}/submissions/assignments/{assignment_id}")
        print(f"[OK] Success! Response:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
        return {"status": "success", "data": response}
    except JavaClientError as e:
        print(f"[ERROR] Error: {e}")
        return {"status": "error", "code": e.status_code, "detail": e.detail}
    except Exception as e:
        print(f"[ERROR] Exception: {e}")
        return {"status": "exception", "detail": str(e)}


async def test_student_grades(client, student_id: str) -> dict:
    """Test GET /dify/teacher/{teacherId}/submissions/students/{studentId}"""
    print(f"\n{'='*60}")
    print(f"TEST: Get Student Grades")
    print(f"  teacher_id: {TEACHER_ID}")
    print(f"  student_id: {student_id}")
    print(f"  endpoint: GET /dify/teacher/{TEACHER_ID}/submissions/students/{student_id}")
    print(f"{'='*60}")

    try:
        response = await client.get(f"/dify/teacher/{TEACHER_ID}/submissions/students/{student_id}")
        print(f"[OK] Success! Response:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
        return {"status": "success", "data": response}
    except JavaClientError as e:
        print(f"[ERROR] Error: {e}")
        return {"status": "error", "code": e.status_code, "detail": e.detail}
    except Exception as e:
        print(f"[ERROR] Exception: {e}")
        return {"status": "exception", "detail": str(e)}


async def main():
    """Run all Java backend tests and record results."""
    settings = get_settings()
    print("=" * 60)
    print("JAVA BACKEND DATA FETCH TEST")
    print("=" * 60)
    print(f"Base URL: {settings.spring_boot_base_url}{settings.spring_boot_api_prefix}")
    print(f"Teacher ID (UUID): {TEACHER_ID}")
    print(f"User ID (numeric): {USER_ID}")
    print(f"Use Mock Data: {settings.use_mock_data}")
    print(f"Timeout: {settings.spring_boot_timeout}s")
    print(f"Access Token: {settings.spring_boot_access_token[:50]}..." if settings.spring_boot_access_token else "Access Token: (not set)")

    results = {
        "test_time": datetime.now().isoformat(),
        "config": {
            "base_url": settings.spring_boot_base_url,
            "api_prefix": settings.spring_boot_api_prefix,
            "teacher_id": TEACHER_ID,
            "user_id": USER_ID,
            "use_mock_data": settings.use_mock_data,
        },
        "tests": {}
    }

    # Get Java client
    client = get_java_client()
    await client.start()

    try:
        # Test 1: List classes
        classes_result = await test_list_classes(client)
        results["tests"]["list_classes"] = classes_result

        # Extract class IDs for further testing
        class_ids = []
        if classes_result["status"] == "success":
            data = classes_result["data"]
            # Handle Result<T> wrapper: {code, message, data}
            if isinstance(data, dict) and "data" in data:
                items = data["data"]
            else:
                items = data

            if isinstance(items, list):
                for cls in items:
                    cls_id = cls.get("uid") or cls.get("id")
                    if cls_id:
                        class_ids.append(str(cls_id))

        print(f"\n>>> Found {len(class_ids)} classes: {class_ids[:5]}...")

        # Test 2: Get detail for first class
        if class_ids:
            first_class_id = class_ids[0]
            detail_result = await test_class_detail(client, first_class_id)
            results["tests"]["class_detail"] = detail_result

            # Test 3: List assignments for first class
            assignments_result = await test_list_assignments(client, first_class_id)
            results["tests"]["list_assignments"] = assignments_result

            # Extract assignment IDs
            assignment_ids = []
            if assignments_result["status"] == "success":
                data = assignments_result["data"]
                if isinstance(data, dict) and "data" in data:
                    # PageResponseDTO: {data: [...], pagination: {...}}
                    inner = data["data"]
                    if isinstance(inner, dict) and "data" in inner:
                        items = inner["data"]
                    elif isinstance(inner, list):
                        items = inner
                    else:
                        items = []
                elif isinstance(data, list):
                    items = data
                else:
                    items = []

                for asn in items:
                    asn_id = asn.get("assignmentId") or asn.get("uid") or asn.get("id")
                    if asn_id:
                        assignment_ids.append(str(asn_id))

            print(f"\n>>> Found {len(assignment_ids)} assignments: {assignment_ids[:5]}...")

            # Test 4: Get submissions for first assignment
            if assignment_ids:
                first_assignment_id = assignment_ids[0]
                submissions_result = await test_assignment_submissions(client, first_assignment_id)
                results["tests"]["assignment_submissions"] = submissions_result

                # Extract student IDs from submissions
                student_ids = []
                if submissions_result["status"] == "success":
                    data = submissions_result["data"]
                    if isinstance(data, dict) and "data" in data:
                        items = data["data"]
                    elif isinstance(data, list):
                        items = data
                    else:
                        items = []

                    for sub in items:
                        stu_id = sub.get("uid") or sub.get("studentId")
                        if stu_id:
                            student_ids.append(str(stu_id))

                print(f"\n>>> Found {len(student_ids)} students with submissions: {student_ids[:5]}...")

                # Test 5: Get grades for first student
                if student_ids:
                    first_student_id = student_ids[0]
                    grades_result = await test_student_grades(client, first_student_id)
                    results["tests"]["student_grades"] = grades_result

        # Save results
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\n{'='*60}")
        print(f"RESULTS SAVED TO: {OUTPUT_FILE}")
        print(f"{'='*60}")

    finally:
        await client.close()

    return results


if __name__ == "__main__":
    asyncio.run(main())
