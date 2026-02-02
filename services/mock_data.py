"""Centralized mock data for development and testing.

Used by data_tools when Java backend is not available.
"""

TEACHERS = {
    "t-001": {
        "id": "t-001",
        "name": "Ms. Chen",
        "subject": "English",
    },
}

CLASSES = {
    "t-001": [
        {
            "class_id": "class-hk-f1a",
            "name": "Form 1A",
            "grade": "Form 1",
            "subject": "English",
            "student_count": 35,
        },
        {
            "class_id": "class-hk-f1b",
            "name": "Form 1B",
            "grade": "Form 1",
            "subject": "English",
            "student_count": 32,
        },
    ],
}

CLASS_DETAILS = {
    "class-hk-f1a": {
        "class_id": "class-hk-f1a",
        "name": "Form 1A",
        "grade": "Form 1",
        "subject": "English",
        "student_count": 35,
        "students": [
            {"student_id": "s-001", "name": "Wong Ka Ho", "number": 1},
            {"student_id": "s-002", "name": "Li Mei", "number": 2},
            {"student_id": "s-003", "name": "Chan Tai Man", "number": 3},
            {"student_id": "s-004", "name": "Cheung Siu Ming", "number": 4},
            {"student_id": "s-005", "name": "Lam Wai Yin", "number": 5},
        ],
        "assignments": [
            {"assignment_id": "a-001", "title": "Unit 5 Test", "type": "exam", "max_score": 100},
            {"assignment_id": "a-002", "title": "Essay Writing", "type": "homework", "max_score": 50},
        ],
    },
    "class-hk-f1b": {
        "class_id": "class-hk-f1b",
        "name": "Form 1B",
        "grade": "Form 1",
        "subject": "English",
        "student_count": 32,
        "students": [
            {"student_id": "s-010", "name": "Ng Hoi Yin", "number": 1},
            {"student_id": "s-011", "name": "Yip Ka Wai", "number": 2},
        ],
        "assignments": [
            {"assignment_id": "a-003", "title": "Unit 5 Test", "type": "exam", "max_score": 100},
        ],
    },
}

SUBMISSIONS = {
    "a-001": {
        "assignment_id": "a-001",
        "title": "Unit 5 Test",
        "class_id": "class-hk-f1a",
        "max_score": 100,
        "submissions": [
            {"student_id": "s-001", "name": "Wong Ka Ho", "score": 58, "submitted": True},
            {"student_id": "s-002", "name": "Li Mei", "score": 85, "submitted": True},
            {"student_id": "s-003", "name": "Chan Tai Man", "score": 72, "submitted": True},
            {"student_id": "s-004", "name": "Cheung Siu Ming", "score": 91, "submitted": True},
            {"student_id": "s-005", "name": "Lam Wai Yin", "score": 65, "submitted": True},
        ],
        "scores": [58, 85, 72, 91, 65],
    },
    "a-002": {
        "assignment_id": "a-002",
        "title": "Essay Writing",
        "class_id": "class-hk-f1a",
        "max_score": 50,
        "submissions": [
            {"student_id": "s-001", "name": "Wong Ka Ho", "score": 32, "submitted": True},
            {"student_id": "s-002", "name": "Li Mei", "score": 45, "submitted": True},
            {"student_id": "s-003", "name": "Chan Tai Man", "score": 38, "submitted": True},
            {"student_id": "s-004", "name": "Cheung Siu Ming", "score": 47, "submitted": True},
            {"student_id": "s-005", "name": "Lam Wai Yin", "score": 35, "submitted": True},
        ],
        "scores": [32, 45, 38, 47, 35],
    },
}

STUDENT_GRADES = {
    "s-001": {
        "student_id": "s-001",
        "name": "Wong Ka Ho",
        "class_id": "class-hk-f1a",
        "grades": [
            {"assignment_id": "a-001", "title": "Unit 5 Test", "score": 58, "max_score": 100},
            {"assignment_id": "a-002", "title": "Essay Writing", "score": 32, "max_score": 50},
        ],
    },
    "s-002": {
        "student_id": "s-002",
        "name": "Li Mei",
        "class_id": "class-hk-f1a",
        "grades": [
            {"assignment_id": "a-001", "title": "Unit 5 Test", "score": 85, "max_score": 100},
            {"assignment_id": "a-002", "title": "Essay Writing", "score": 45, "max_score": 50},
        ],
    },
}
