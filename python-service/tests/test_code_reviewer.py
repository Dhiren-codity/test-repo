import pytest
from src.code_reviewer import CodeReviewer, CodeIssue


class TestCodeReviewer:
    def setup_method(self):
        self.reviewer = CodeReviewer()

    def test_review_simple_code(self):
        code = """def hello():
    print("Hello, World!")
"""
        result = self.reviewer.review_code(code)
        assert result.score >= 0
        assert result.score <= 100
        assert isinstance(result.issues, list)

    def test_detect_long_line(self):
        code = "x = " + "a" * 150
        result = self.reviewer.review_code(code)
        assert len(result.issues) > 0
        assert any(
            issue.message == "Line exceeds 120 characters" for issue in result.issues
        )

    def test_detect_todo(self):
        code = """def test():
    # TODO: implement this
    pass
"""
        result = self.reviewer.review_code(code)
        assert any("TODO" in issue.message for issue in result.issues)

    def test_detect_hardcoded_password(self):
        code = 'password = "secret123"'
        result = self.reviewer.review_code(code)
        assert any("password" in issue.message.lower() for issue in result.issues)

    def test_calculate_complexity(self):
        code = """def complex_function():
    if True:
        for i in range(10):
            while False:
                try:
                    pass
                except:
                    pass
"""
        result = self.reviewer.review_code(code)
        assert result.complexity_score > 0

    def test_review_function_too_many_params(self):
        code = "def test(a, b, c, d, e, f, g): pass"
        result = self.reviewer.review_function(code)
        assert "warning" in result

    def test_review_function_ok(self):
        code = """def simple(a, b):
    return a + b
"""
        result = self.reviewer.review_function(code)
        assert result.get("status") == "ok"
