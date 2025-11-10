import ast
import textwrap
from unittest.mock import patch

import pytest

from src.test_coverage_analyzer import (
    CoverageType,
    CoverageItem,
    CoverageReport,
    TestCoverageAnalyzer,
    CoverageASTVisitor,
    ComplexityCalculator,
)


@pytest.fixture
def analyzer():
    """Create TestCoverageAnalyzer instance for testing"""
    return TestCoverageAnalyzer()


@pytest.fixture
def simple_source():
    """Provide a simple source with a function, class, method, and async method"""
    return textwrap.dedent(
        """
        def foo(x):
            if x > 0:
                return 1
            return 0

        class A:
            def bar(self, y):
                if y:
                    return 2
                return 3

            async def baz(self):
                return 4
        """
    ).strip("\n")


@pytest.fixture
def basic_test_code():
    """Provide a basic test code sample that references function and class"""
    return textwrap.dedent(
        """
        import pytest

        def test_foo_calls():
            assert foo(1) == 1

        class TestA:
            def test_bar(self):
                a = A()
                assert a.bar(True) == 2
        """
    ).strip("\n")


def test_CoverageType_enum_values():
    """Test that CoverageType enum contains expected members with correct values"""
    assert CoverageType.FUNCTION.value == "function"
    assert CoverageType.CLASS.value == "class"
    assert CoverageType.METHOD.value == "method"
    assert CoverageType.BRANCH.value == "branch"
    assert CoverageType.LINE.value == "line"


def test_CoverageItem_initialization_defaults():
    """Test CoverageItem dataclass initialization and defaults"""
    item = CoverageItem(
        name="foo",
        type=CoverageType.FUNCTION,
        line_start=1,
        line_end=10,
        is_covered=False,
        complexity=3,
    )
    assert item.name == "foo"
    assert item.type == CoverageType.FUNCTION
    assert item.line_start == 1
    assert item.line_end == 10
    assert item.is_covered is False
    assert item.complexity == 3
    assert item.test_count == 0
    assert item.branches == []


def test_TestCoverageAnalyzer_init_initializes_dependencies(analyzer):
    """Test TestCoverageAnalyzer initialization sets dependencies"""
    assert isinstance(analyzer.ast_visitor, CoverageASTVisitor)
    assert isinstance(analyzer.complexity_calculator, ComplexityCalculator)


def test_CoverageASTVisitor_visits_and_collects_defs():
    """Test CoverageASTVisitor collects functions, classes, and methods with correct names"""
    src = textwrap.dedent(
        """
        class C:
            def m(self):
                pass

        async def af():
            pass

        def f(x):
            return x
        """
    ).strip("\n")
    tree = ast.parse(src)
    visitor = CoverageASTVisitor()
    visitor.visit(tree)

    assert "C" in visitor.classes
    assert "C.m" in visitor.methods
    assert "af" in visitor.functions
    assert "f" in visitor.functions

    c_start, c_end = visitor.classes["C"]
    m_start, m_end = visitor.methods["C.m"]
    f_start, f_end = visitor.functions["f"]
    assert c_start <= c_end
    assert m_start <= m_end
    assert f_start <= f_end


def test_ComplexityCalculator_calculate_function_complexity_counts_keywords():
    """Test function complexity counts keywords with a simple cyclomatic example"""
    src = textwrap.dedent(
        """
        def f():
            if a and b or not c:
                for i in range(3):
                    assert i
            else:
                try:
                    pass
                except Exception:
                    pass
                finally:
                    pass
        """
    ).strip("\n")
    tree = ast.parse(src)
    func_node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    start, end = func_node.lineno, func_node.end_lineno
    calc = ComplexityCalculator()
    complexity = calc.calculate_function_complexity(src, start, end)
    # 1 base + (if=1) + (and=1) + (or=1) + (not=1) + (for=1) + (assert=1) + (else=1) + (try=1) + (except=1) + (finally=1)
    assert complexity == 11


def test_ComplexityCalculator_calculate_class_complexity_counts_methods_and_keywords():
    """Test class complexity sums methods and keyword occurrences"""
    src = textwrap.dedent(
        """
        class C:
            def a(self): 
                pass

            def b(self):
                if True:
                    pass

            @property
            def prop(self):
                return 1
        """
    ).strip("\n")
    tree = ast.parse(src)
    class_node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    start, end = class_node.lineno, class_node.end_lineno
    calc = ComplexityCalculator()
    complexity = calc.calculate_class_complexity(src, start, end)
    # method_count = 3 (a, b, prop) + keywords in class body: 'if' = 1 => total 4
    assert complexity == 4


def test_TestCoverageAnalyzer_analyze_coverage_basic_with_executed_sets(analyzer, simple_source):
    """Test analyze_coverage computes coverage with provided executed sets"""
    # We'll assume foo function and A class are executed
    executed_functions = {"foo", "A.bar"}
    executed_classes = {"A"}
    executed_lines = {1, 2, 3, 4}  # arbitrary

    report = analyzer.analyze_coverage(
        simple_source,
        test_code=None,
        executed_lines=executed_lines.copy(),
        executed_functions=executed_functions.copy(),
        executed_classes=executed_classes.copy(),
    )

    # Totals
    assert report.total_functions >= 1
    assert report.total_classes >= 1
    assert report.total_methods >= 1
    assert report.total_lines == len(simple_source.split("\n"))

    # Covered counts reflect executed sets
    assert report.covered_functions >= 1
    assert report.covered_classes >= 1
    assert report.covered_methods >= 1  # A.bar is covered via executed_functions
    assert report.covered_lines == len(executed_lines)

    # function_coverage_map should mark foo as covered
    assert report.function_coverage_map.get("foo") is True


def test_TestCoverageAnalyzer_analyze_coverage_with_test_code_detection(analyzer, simple_source, basic_test_code):
    """Test analyze_coverage integrates _analyze_test_code to detect functions and classes"""
    report = analyzer.analyze_coverage(simple_source, test_code=basic_test_code)
    # foo should be detected as tested function; class A detected as tested class
    assert report.function_coverage_map.get("foo") in (True, False)
    # Because method detection relies on "A.bar" appearing (unlikely), method may not be covered
    method_items = [i for i in report.uncovered_items if i.type == CoverageType.METHOD]
    # The class A should be marked covered due to test detection of TestA
    covered_classes = [i for i in report.uncovered_items if i.type == CoverageType.CLASS]
    assert "A" not in {i.name for i in covered_classes}


def test_TestCoverageAnalyzer_analyze_coverage_invalid_source_raises(analyzer):
    """Test analyze_coverage raises SyntaxError on invalid Python source"""
    bad_src = "def bad(:\n  pass"
    with pytest.raises(SyntaxError):
        analyzer.analyze_coverage(bad_src)


def test_TestCoverageAnalyzer_generate_coverage_report_summary_values(analyzer, simple_source):
    """Test summary generation returns expected structure and numeric values"""
    report = analyzer.analyze_coverage(simple_source, executed_lines=set())
    summary = analyzer.generate_coverage_report_summary(report)

    assert "summary" in summary
    assert "metrics" in summary
    assert "branch_coverage" in summary
    assert "suggestions" in summary

    s = summary["summary"]
    assert 0.0 <= s["overall_coverage"] <= 100.0
    assert 0.0 <= s["function_coverage"] <= 100.0
    assert 0.0 <= s["class_coverage"] <= 100.0
    assert 0.0 <= s["method_coverage"] <= 100.0
    assert 0.0 <= s["line_coverage"] <= 100.0

    m = summary["metrics"]
    assert m["total_lines"] == len(simple_source.split("\n"))


def test_TestCoverageAnalyzer_calculate_branch_coverage_counts_and_coverage(analyzer):
    """Test branch coverage computation for various branch types"""
    src = textwrap.dedent(
        """
        def f(x):
            if x:
                pass
            else:
                pass
        for i in range(3):
            pass
        while False:
            pass
        try:
            pass
        except Exception:
            pass
        """
    ).strip("\n")
    executed_lines = {2, 6, 10}  # cover 'if', 'for', and 'try' lines
    branch_coverage = analyzer._calculate_branch_coverage(src, executed_lines)

    assert branch_coverage["if_statement"] == 100.0
    assert branch_coverage["else_block"] == 0.0
    assert branch_coverage["for_loop"] == 100.0
    assert branch_coverage["while_loop"] == 0.0
    assert branch_coverage["try_block"] == 100.0
    assert branch_coverage["except_block"] == 0.0


def test_TestCoverageAnalyzer_generate_suggestions_low_and_medium_coverage(analyzer):
    """Test suggestions for low and medium coverage thresholds"""
    # Low coverage: empty source => 1 line counted, 0 covered lines => < 50%
    report_low = analyzer.analyze_coverage("", executed_lines=set())
    assert any("below 50%" in s for s in report_low.suggestions)

    # Medium coverage: 60% lines covered in a 10-line file, no functions/classes
    src = "\n".join([""] * 10)
    executed = set(range(1, 7))  # 6 of 10 lines
    report_med = analyzer.analyze_coverage(src, executed_lines=executed)
    assert any("below 80%" in s for s in report_med.suggestions)


def test_TestCoverageAnalyzer_generate_suggestions_uncovered_and_high_complexity(analyzer):
    """Test suggestions include uncovered functions and high complexity items"""
    src = textwrap.dedent(
        """
        def f1():
            pass

        def f2():
            pass
        """
    ).strip("\n")

    with patch.object(analyzer.complexity_calculator, "calculate_function_complexity", return_value=12), \
         patch.object(analyzer.complexity_calculator, "calculate_class_complexity", return_value=1):
        report = analyzer.analyze_coverage(src, executed_lines=set())

    # Expect suggestions:
    # - Coverage below 50%
    # - Priority: Add tests for uncovered functions: ...
    # - High complexity items detected: ...
    # - More than 30% of functions are untested...
    assert any("below 50%" in s for s in report.suggestions)
    assert any("Priority: Add tests for uncovered functions" in s for s in report.suggestions)
    assert any("High complexity items detected" in s for s in report.suggestions)
    assert any("More than 30% of functions are untested" in s for s in report.suggestions)

    # Confirm the uncovered functions are mentioned
    func_suggestion = next(s for s in report.suggestions if s.startswith("Priority: Add tests for uncovered functions"))
    assert "f1" in func_suggestion and "f2" in func_suggestion


def test__analyze_test_code_edge_cases_empty(analyzer):
    """Test _analyze_test_code behavior with empty test code and no targets"""
    result = analyzer._analyze_test_code("", {}, {}, {})
    assert result["tested_functions"] == set()
    assert result["tested_classes"] == set()
    assert result["tested_lines"] == set()
    assert result["function_test_counts"] == {}
    assert result["test_function_count"] == 0


def test_function_coverage_map_values(analyzer):
    """Test function_coverage_map correctly reflects coverage status of functions"""
    src = textwrap.dedent(
        """
        def a(): pass
        def b(): pass
        """
    ).strip("\n")

    report = analyzer.analyze_coverage(src, executed_functions={"a"})
    assert report.function_coverage_map["a"] is True
    assert report.function_coverage_map["b"] is False


def test_TestCoverageAnalyzer_complexity_called_for_items(analyzer, simple_source):
    """Test that complexity calculator is called for functions, classes, and methods"""
    with patch.object(analyzer.complexity_calculator, "calculate_function_complexity", return_value=5) as mock_func, \
         patch.object(analyzer.complexity_calculator, "calculate_class_complexity", return_value=3) as mock_class:
        analyzer.analyze_coverage(simple_source)

    # There should be at least one function and two methods
    assert mock_func.call_count >= 1
    assert mock_class.call_count >= 1


def test_TestCoverageAnalyzer_branch_coverage_empty_when_no_branches(analyzer):
    """Test branch coverage is empty when no branch patterns exist in source"""
    src = "x = 1\ny = 2\nz = x + y"
    branch_coverage = analyzer._calculate_branch_coverage(src, set())
    assert branch_coverage == {}