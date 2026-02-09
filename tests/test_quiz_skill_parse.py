"""Tests for quiz_skill JSON parsing — LaTeX escape handling.

Covers _fix_invalid_json_escapes and _try_extract_question with real
LLM-produced content containing LaTeX math notation.
"""

import json
import pytest

from skills.quiz_skill import _fix_invalid_json_escapes, _try_extract_question


# ── _fix_invalid_json_escapes ──────────────────────────────────


class TestFixInvalidJsonEscapes:
    """Verify LaTeX backslash → valid JSON escape conversion."""

    def test_simple_latex_commands(self):
        # \sqrt, \int, \lim — not valid JSON escapes
        raw = r'{"q": "$\sqrt{x}$ and $\int$ and $\lim$"}'
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        assert "\\sqrt" in obj["q"]

    def test_begin_end_pmatrix(self):
        """The exact pattern from the user's dropped JSON block."""
        raw = r'{"q": "$A = \begin{pmatrix} 2 & 3 \\ 4 & 5 \end{pmatrix}$"}'
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        assert "\\begin{pmatrix}" in obj["q"]
        assert "\\end{pmatrix}" in obj["q"]

    def test_frac_command(self):
        raw = r'{"q": "$\frac{1}{2}$"}'
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        assert "\\frac" in obj["q"]

    def test_double_backslash_preserved(self):
        r"""Ensure \\ (LaTeX line break / literal backslash) survives."""
        raw = r'{"q": "line1 \\ line2"}'
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        # JSON \\ → literal single backslash in value
        assert "\\" in obj["q"]

    def test_double_backslash_before_number(self):
        r"""\\ followed by a digit (matrix row break) must stay valid."""
        raw = r'{"q": "3 \\ 4"}'
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        assert "\\ 4" in obj["q"] or "\\4" in obj["q"]

    def test_double_backslash_before_minus(self):
        r"""\\ followed by -c (matrix element)."""
        raw = r'{"q": "3 \\ -c"}'
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        assert "\\" in obj["q"]

    def test_mixed_latex_and_double_backslash(self):
        """Full matrix expression: \\begin + \\\\ + \\end."""
        raw = (
            r'{"q": "$\begin{pmatrix} d & -b \\ -c & a \end{pmatrix}$",'
            r' "a": "ok"}'
        )
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        assert "\\begin" in obj["q"]
        assert "\\end" in obj["q"]
        assert obj["a"] == "ok"

    def test_text_and_theta(self):
        raw = r'{"q": "$\text{if } \theta > 0$"}'
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        assert "\\text" in obj["q"]
        assert "\\theta" in obj["q"]

    def test_standalone_json_escapes_untouched(self):
        r"""Standalone \n \t (followed by non-alpha) remain valid JSON escapes."""
        raw = '{"q": "line1\\n line2\\t 3"}'
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        assert obj["q"] == "line1\n line2\t 3"

    def test_n_plus_letters_treated_as_latex(self):
        r"""\n followed by 2+ letters is treated as LaTeX (e.g. \nabla)."""
        raw = r'{"q": "$\nabla f$"}'
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        assert "\\nabla" in obj["q"]

    def test_real_dropped_block(self):
        """Reproduce the exact dropped block from the user's log."""
        raw = (
            '{\n'
            '    "questionType": "FILL_IN_BLANK",\n'
            '    "question": "若 $A = \\begin{pmatrix} 2 & 3 '
            '\\\\ 4 & 5 \\end{pmatrix}$，则 $A^{-1} = '
            '\\begin{pmatrix} ____ & ____ \\\\ ____ & ____ '
            '\\end{pmatrix}$。",\n'
            '    "correctAnswer": "-5 3 4 -2",\n'
            '    "explanation": "矩阵 $A$ 的逆矩阵 $A^{-1} = '
            '\\frac{1}{ad-bc} \\begin{pmatrix} d & -b \\\\ -c & a '
            '\\end{pmatrix}$，其中 $a=2, b=3, c=4, d=5$。计算得 '
            '$A^{-1} = \\begin{pmatrix} -5 & 3 \\\\ 4 & -2 '
            '\\end{pmatrix}$。",\n'
            '    "difficulty": "hard",\n'
            '    "knowledgePoint": "线性代数",\n'
            '    "points": 1\n'
            '  }'
        )
        fixed = _fix_invalid_json_escapes(raw)
        obj = json.loads(fixed)
        assert obj["questionType"] == "FILL_IN_BLANK"
        assert obj["knowledgePoint"] == "线性代数"
        assert "\\begin{pmatrix}" in obj["question"]
        assert "\\frac" in obj["explanation"]


# ── _try_extract_question ──────────────────────────────────────


class TestTryExtractQuestion:
    """Verify streaming JSON extraction from buffer."""

    def test_extract_simple(self):
        buf = '[{"questionType": "SINGLE_CHOICE", "question": "1+1=?"}]'
        obj, remaining = _try_extract_question(buf)
        assert obj is not None
        assert obj["questionType"] == "SINGLE_CHOICE"

    def test_extract_with_latex(self):
        buf = r'{"question": "$\frac{1}{2}$", "questionType": "FILL_IN_BLANK"}'
        obj, remaining = _try_extract_question(buf)
        assert obj is not None
        assert obj["questionType"] == "FILL_IN_BLANK"

    def test_incomplete_json(self):
        buf = '{"question": "incom'
        obj, remaining = _try_extract_question(buf)
        assert obj is None

    def test_extract_with_matrix_latex(self):
        """The exact pattern that was being dropped."""
        buf = (
            '{"questionType": "FILL_IN_BLANK", '
            '"question": "$\\begin{pmatrix} 1 \\\\ 2 \\end{pmatrix}$", '
            '"correctAnswer": "ok"}'
        )
        obj, remaining = _try_extract_question(buf)
        assert obj is not None
        assert obj["correctAnswer"] == "ok"
