"""Tests for adapters/ — Java API response → internal model mapping."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from models.data import ClassInfo, ClassDetail, AssignmentInfo, SubmissionData, GradeData


# ---------------------------------------------------------------------------
# Sample Java API responses (from OpenAPI spec)
# ---------------------------------------------------------------------------

JAVA_CLASSROOM = {
    "id": 42,
    "uid": "cls-uuid-001",
    "name": "Form 1A",
    "subject": "English",
    "grade": "Form 1",
    "description": "English class for Form 1A",
    "teacherId": 7,
    "schoolId": 1,
    "semesterLabel": "2025-2026 Semester 1",
    "studentCount": 35,
    "assignmentCount": 5,
    "createdAt": "2025-09-01T00:00:00Z",
    "updatedAt": "2025-12-01T00:00:00Z",
}

JAVA_CLASSROOM_B = {
    "id": 43,
    "uid": "cls-uuid-002",
    "name": "Form 1B",
    "subject": "English",
    "grade": "Form 1",
    "description": "",
    "studentCount": 32,
    "assignmentCount": 3,
}

JAVA_CLASS_ASSIGNMENT = {
    "assignmentId": "asgn-uuid-001",
    "title": "Unit 5 Test",
    "due_date": "2025-11-15T23:59:00Z",
    "submission_count": 30,
    "total_students": 35,
    "average_score": 72.5,
    "total_points": 100,
    "status": "CLOSED",
    "assignmentType": "exam",
    "teacherId": 7,
    "teacherName": "Ms. Chen",
    "canEdit": True,
}

JAVA_SUBMISSION = {
    "uid": "sub-uuid-001",
    "assignmentUid": "asgn-uuid-001",
    "assignmentTitle": "Unit 5 Test",
    "studentId": 101,
    "studentName": "Wong Ka Ho",
    "score": 58.0,
    "status": "GRADED",
    "feedback": "Needs improvement on grammar section",
    "submittedAt": "2025-11-14T10:30:00Z",
    "gradedAt": "2025-11-16T09:00:00Z",
}

JAVA_SUBMISSION_B = {
    "uid": "sub-uuid-002",
    "assignmentUid": "asgn-uuid-001",
    "assignmentTitle": "Unit 5 Test",
    "studentId": 102,
    "studentName": "Li Mei",
    "score": 85.0,
    "status": "GRADED",
    "feedback": "",
    "submittedAt": "2025-11-14T11:00:00Z",
}

JAVA_GRADE_HISTORY = {
    "averageScore": 71.5,
    "highestScore": 85.0,
    "totalGraded": 2,
    "gradeHistory": [
        {
            "gradedDate": "2025-11-16T09:00:00Z",
            "score": 58.0,
            "totalScore": 100,
            "percentage": 58.0,
            "assignmentId": "asgn-uuid-001",
            "assignmentName": "Unit 5 Test",
        },
        {
            "gradedDate": "2025-11-20T09:00:00Z",
            "score": 85.0,
            "totalScore": 100,
            "percentage": 85.0,
            "assignmentId": "asgn-uuid-002",
            "assignmentName": "Essay Writing",
        },
    ],
}


# ---------------------------------------------------------------------------
# Helper: fake JavaClient
# ---------------------------------------------------------------------------

def _mock_client(get_return=None):
    client = MagicMock()
    client.get = AsyncMock(return_value=get_return)
    return client


# =========================================================================
# class_adapter tests
# =========================================================================

class TestClassAdapter:

    @pytest.mark.asyncio
    async def test_list_classes(self):
        from adapters.class_adapter import list_classes

        client = _mock_client({"code": 200, "data": [JAVA_CLASSROOM, JAVA_CLASSROOM_B]})
        result = await list_classes(client, "teacher-uuid-001")

        assert len(result) == 2
        assert isinstance(result[0], ClassInfo)
        assert result[0].class_id == "cls-uuid-001"
        assert result[0].name == "Form 1A"
        assert result[0].student_count == 35
        assert result[0].subject == "English"
        assert result[1].class_id == "cls-uuid-002"

    @pytest.mark.asyncio
    async def test_list_classes_empty(self):
        from adapters.class_adapter import list_classes

        client = _mock_client({"code": 200, "data": []})
        result = await list_classes(client, "teacher-uuid-001")
        assert result == []

    @pytest.mark.asyncio
    async def test_list_classes_null_data_raises(self):
        """When Java returns data=null, adapter must raise ValueError (not silently return []).

        This triggers PydanticAI's max_retries for automatic retry instead of
        telling the LLM "teacher has 0 classes" when the backend is flaky.
        """
        from adapters.class_adapter import list_classes

        client = _mock_client({"code": 200, "data": None})
        with pytest.raises(ValueError, match="null data"):
            await list_classes(client, "teacher-uuid-001")

    @pytest.mark.asyncio
    async def test_get_detail_null_data_raises(self):
        """get_detail must raise on null data."""
        from adapters.class_adapter import get_detail

        client = _mock_client({"code": 200, "data": None})
        with pytest.raises(ValueError, match="null data"):
            await get_detail(client, "teacher-uuid-001", "cls-001")

    @pytest.mark.asyncio
    async def test_get_detail(self):
        from adapters.class_adapter import get_detail

        client = _mock_client({"code": 200, "data": JAVA_CLASSROOM})
        result = await get_detail(client, "teacher-uuid-001", "cls-uuid-001")

        assert isinstance(result, ClassDetail)
        assert result.class_id == "cls-uuid-001"
        assert result.name == "Form 1A"
        assert result.student_count == 35

    @pytest.mark.asyncio
    async def test_list_assignments(self):
        from adapters.class_adapter import list_assignments

        client = _mock_client({
            "code": 200,
            "data": {
                "data": [JAVA_CLASS_ASSIGNMENT],
                "pagination": {"page": 1, "limit": 10, "total": 1},
            },
        })
        result = await list_assignments(client, "teacher-uuid-001", "cls-uuid-001")

        assert len(result) == 1
        assert isinstance(result[0], AssignmentInfo)
        assert result[0].assignment_id == "asgn-uuid-001"
        assert result[0].title == "Unit 5 Test"
        assert result[0].max_score == 100
        assert result[0].type == "exam"

    @pytest.mark.asyncio
    async def test_parse_classroom_uses_uid_over_id(self):
        from adapters.class_adapter import _parse_classroom

        info = _parse_classroom({"uid": "uuid-123", "id": 42, "name": "Test"})
        assert info.class_id == "uuid-123"

    @pytest.mark.asyncio
    async def test_parse_classroom_fallback_to_id(self):
        from adapters.class_adapter import _parse_classroom

        info = _parse_classroom({"id": 42, "name": "Test"})
        assert info.class_id == "42"

    @pytest.mark.asyncio
    async def test_parse_classroom_null_description(self):
        from adapters.class_adapter import _parse_classroom

        info = _parse_classroom({"id": 42, "name": "Test", "description": None})
        assert info.description == ""


# =========================================================================
# submission_adapter tests
# =========================================================================

class TestSubmissionAdapter:

    @pytest.mark.asyncio
    async def test_get_submissions(self):
        from adapters.submission_adapter import get_submissions

        client = _mock_client({
            "code": 200,
            "data": [JAVA_SUBMISSION, JAVA_SUBMISSION_B],
        })
        result = await get_submissions(client, "teacher-uuid-001", "asgn-uuid-001")

        assert isinstance(result, SubmissionData)
        assert result.assignment_id == "asgn-uuid-001"
        assert result.title == "Unit 5 Test"
        assert len(result.submissions) == 2
        assert result.submissions[0].student_id == "sub-uuid-001"
        assert result.submissions[0].name == "Wong Ka Ho"
        assert result.submissions[0].score == 58.0
        assert result.scores == [58.0, 85.0]

    @pytest.mark.asyncio
    async def test_get_submissions_empty(self):
        from adapters.submission_adapter import get_submissions

        client = _mock_client({"code": 200, "data": []})
        result = await get_submissions(client, "t-001", "bad-id")

        assert result.submissions == []
        assert result.scores == []

    @pytest.mark.asyncio
    async def test_get_submissions_null_data_raises(self):
        """get_submissions must raise on null data."""
        from adapters.submission_adapter import get_submissions

        client = _mock_client({"code": 200, "data": None})
        with pytest.raises(ValueError, match="null data"):
            await get_submissions(client, "t-001", "asgn-001")

    @pytest.mark.asyncio
    async def test_submission_status_mapping(self):
        from adapters.submission_adapter import _parse_submission

        graded = _parse_submission({"status": "GRADED", "studentName": "A", "score": 80})
        assert graded.submitted is True

        not_submitted = _parse_submission({"status": "NOT_SUBMITTED", "studentName": "B"})
        assert not_submitted.submitted is False


# =========================================================================
# grade_adapter tests
# =========================================================================

class TestGradeAdapter:

    @pytest.mark.asyncio
    async def test_get_student_submissions(self):
        from adapters.grade_adapter import get_student_submissions

        client = _mock_client({
            "code": 200,
            "data": [JAVA_SUBMISSION, JAVA_SUBMISSION_B],
        })
        result = await get_student_submissions(client, "teacher-uuid-001", "student-uuid-001")

        assert isinstance(result, GradeData)
        assert result.student_id == "student-uuid-001"
        assert result.total_graded == 2
        assert len(result.grades) == 2
        assert result.grades[0].assignment_id == "asgn-uuid-001"
        assert result.grades[0].score == 58.0
        assert result.average_score is not None
        assert result.highest_score == 85.0

    @pytest.mark.asyncio
    async def test_get_course_grades(self):
        from adapters.grade_adapter import get_course_grades

        client = _mock_client({"code": 200, "data": JAVA_GRADE_HISTORY})
        result = await get_course_grades(client, "student-uuid-001", "course-uuid-001")

        assert isinstance(result, GradeData)
        assert result.average_score == 71.5
        assert result.highest_score == 85.0
        assert result.total_graded == 2
        assert len(result.grades) == 2
        assert result.grades[0].title == "Unit 5 Test"
        assert result.grades[1].title == "Essay Writing"

    @pytest.mark.asyncio
    async def test_get_student_submissions_empty(self):
        from adapters.grade_adapter import get_student_submissions

        client = _mock_client({"code": 200, "data": []})
        result = await get_student_submissions(client, "t-001", "s-bad")

        assert result.grades == []
        assert result.total_graded == 0
        assert result.average_score is None

    @pytest.mark.asyncio
    async def test_get_student_submissions_null_data_raises(self):
        """get_student_submissions must raise on null data."""
        from adapters.grade_adapter import get_student_submissions

        client = _mock_client({"code": 200, "data": None})
        with pytest.raises(ValueError, match="null data"):
            await get_student_submissions(client, "t-001", "s-001")


# =========================================================================
# Internal model tests
# =========================================================================

class TestInternalModels:

    def test_class_info_defaults(self):
        info = ClassInfo(class_id="c-1", name="Test")
        assert info.student_count == 0
        assert info.grade == ""

    def test_submission_data_scores(self):
        data = SubmissionData(
            assignment_id="a-1",
            submissions=[],
            scores=[90, 80, 70],
        )
        assert len(data.scores) == 3

    def test_grade_data_model(self):
        g = GradeData(student_id="s-1", total_graded=1, grades=[
            GradeRecord(assignment_id="a-1", score=85, max_score=100),
        ])
        assert g.grades[0].score == 85


# Need to import GradeRecord for the test above
from models.data import GradeRecord
