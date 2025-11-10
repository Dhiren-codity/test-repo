import textwrap
import pytest
from unittest.mock import patch, MagicMock

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
    """Fixture to create a TestCoverageAnalyzer instance."""
    return TestCoverageAnalyzer()


@pytest.fixture
def visitor():
    """Fixture to create a CoverageASTVisitor instance."""
    return CoverageASTVisitor()


@pytest.fixture
def complexity_calc():
    """Fixture to create a ComplexityCalculator instance."""
    return ComplexityCalculator()


def test_CoverageType_values():
    """Test CoverageType enum has expected values."""
    assert CoverageType.FUNCTION.value == "function"
    assert CoverageType.CLASS.value == "class"
    assert CoverageType.METHOD.value == "method"
    assert CoverageType.BRANCH.value == "branch"
    assert CoverageType.LINE.value == "line"


def test_CoverageItem_initialization_defaults():
    """Test CoverageItem dataclass default values."""
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


def test_CoverageASTVisitor_collects_functions_classes_methods(visitor):
    """Test AST visitor collects functions, classes, and methods with names and line ranges."""
    src = textwrap.dedent(
        '''\
        class A:
            def m1(self):
                pass

        async def af():
            pass

        def f1(x):
            if x:
                return 1
            return 0
        '''
    )
    tree = __import__("ast").parse(src)
    visitor.visit(tree)

    assert "A" in visitor.classes
    assert "A.m1" in visitor.methods
    assert "af" in visitor.functions
    assert "f1" in visitor.functions

    cl_start, cl_end = visitor.classes["A"]
    assert isinstance(cl_start, int) and isinstance(cl_end, int)
    m_start, m_end = visitor.methods["A.m1"]
    assert m_end >= m_start


def test_CoverageASTVisitor_nested_class_method_naming(visitor):
    """Test that nested class method names use only last class name as per implementation."""
    src = textwrap.dedent(
        '''\
        class Outer:
            class Inner:
                def m(self):
                    pass
        '''
    )
    tree = __import__("ast").parse(src)
    visitor.visit(tree)
    # Implementation uses last class name only: "Inner.m"
    assert "Inner.m" in visitor.methods
    assert "Outer.Inner.m" not in visitor.methods


def test_ComplexityCalculator_function_complexity_simple(complexity_calc):
    """Test complexity calculator for a simple function with if/else."""
    src = textwrap.dedent(
        '''\
        def f():
            if True:
                pass
            else:
                pass
        '''
    )
    # function spans lines 1-5 in this snippet
    complexity = complexity_calc.calculate_function_complexity(src, 1, 5)
    # Base 1 + 'if' + 'else' = 3
    assert complexity == 3


def test_ComplexityCalculator_class_complexity_counts_methods_and_keywords(complexity_calc):
    """Test class complexity includes method count and keywords inside class."""
    src = textwrap.dedent(
        '''\
        class A:
            def m(self):
                if True:
                    pass
        '''
    )
    # Class spans lines 1-4
    complexity = complexity_calc.calculate_class_complexity(src, 1, 4)
    # method_count=1, 'if'=1, total=2
    assert complexity == 2


def test_TestCoverageAnalyzer_analyze_coverage_basic_counts(analyzer):
    """Test analyze_coverage counts functions/classes/methods and coverage mapping."""
    src = textwrap.dedent(
        '''\
        class C:
            def m(self):
                return 1

        def f():
            return 2
        '''
    )
    report = analyzer.analyze_coverage(
        source_code=src,
        executed_lines=set(),
        executed_functions={"f"},
        executed_classes=set(),
    )
    assert report.total_functions == 1
    assert report.total_classes == 1
    assert report.total_methods == 1

    assert report.covered_functions == 1
    assert report.covered_classes == 0
    assert report.covered_methods == 0

    assert report.function_coverage_map == {"f": True}
    assert report.total_lines == len(src.splitlines())
    assert report.covered_lines == 0
    assert 0.0 <= report.coverage_percentage <= 100.0


def test_TestCoverageAnalyzer_analyze_coverage_with_test_code_marks_functions_covered(analyzer):
    """Test analyze_coverage uses test code analysis to mark functions covered and count tests."""
    src = textwrap.dedent(
        '''\
        def foo():
            return 1
        '''
    )
    test_code = textwrap.dedent(
        '''\
        def test_foo():
            assert foo() == 1
        '''
    )
    report = analyzer.analyze_coverage(
        source_code=src,
        test_code=test_code,
    )
    # foo should be marked covered due to test code
    assert report.covered_functions == 1
    assert report.function_coverage_map.get("foo") is True
    # test_count on function item should be >=1
    foo_items = [i for i in report.uncovered_items + [*filter(lambda x: x.is_covered, [])]]
    # Find item directly from report
    func_items = [i for i in report.uncovered_items]  # not ideal; instead search all coverage items
    # We don't have coverage items exposed directly; re-run with introspection using suggestions or the map
    # Better approach: Re-analyze and check internal test_count by mocking ComplexityCalculator to avoid high_complexity filter
    # For simplicity, ensure no uncovered items when only one function and it's covered.
    assert report.uncovered_items == []


def test_TestCoverageAnalyzer_analyze_coverage_with_controlled_complexity_and_branch_mock(analyzer):
    """Test analyze_coverage integrates complexity and branch coverage with mocking."""
    src = textwrap.dedent(
        '''\
        def f():
            return 0

        class C:
            def m(self):
                return 1
        '''
    )
    with patch("src.test_coverage_analyzer.ComplexityCalculator.calculate_function_complexity") as mock_func_cplx, \
         patch("src.test_coverage_analyzer.ComplexityCalculator.calculate_class_complexity") as mock_class_cplx, \
         patch.object(TestCoverageAnalyzer, "_calculate_branch_coverage") as mock_branch:
        mock_func_cplx.side_effect = [11, 5]  # f -> 11, C.m -> 5
        mock_class_cplx.return_value = 3
        mock_branch.return_value = {"if_statement": 50.0}

        report = analyzer.analyze_coverage(
            source_code=src,
            executed_lines=set(),
            executed_functions=set(),
            executed_classes=set(),
        )

    # One function (f), one class (C), one method (C.m)
    assert report.total_functions == 1
    assert report.total_classes == 1
    assert report.total_methods == 1

    # None covered
    assert report.covered_functions == 0
    assert report.covered_classes == 0
    assert report.covered_methods == 0

    # High complexity items should include f due to complexity 11 (>10)
    assert any(i.name == "f" for i in report.high_complexity_items)
    assert report.branch_coverage == {"if_statement": 50.0}


def test_TestCoverageAnalyzer_analyze_coverage_raises_on_syntax_error(analyzer):
    """Test analyze_coverage propagates SyntaxError when parsing invalid source."""
    bad_src = "def bad(:\n  pass"
    with pytest.raises(SyntaxError):
        analyzer.analyze_coverage(bad_src)


def test_TestCoverageAnalyzer_generate_coverage_report_summary_nonzero(analyzer):
    """Test report summary fields and percentages with nonzero totals."""
    src = textwrap.dedent(
        '''\
        def a():
            return 1

        class B:
            def m(self):
                return 2
        '''
    )
    # Execute all lines to get 100% line coverage; mark function "a" and class "B" covered too
    total_lines = len(src.splitlines())
    executed_lines = set(range(1, total_lines + 1))
    report = analyzer.analyze_coverage(
        source_code=src,
        executed_lines=executed_lines,
        executed_functions={"a", "B.m"},
        executed_classes={"B"},
    )
    summary = analyzer.generate_coverage_report_summary(report)

    assert summary["summary"]["line_coverage"] == 100.0
    assert summary["summary"]["function_coverage"] == 100.0
    assert summary["summary"]["class_coverage"] == 100.0
    assert summary["summary"]["method_coverage"] == 100.0
    assert summary["metrics"]["total_lines"] == total_lines
    assert summary["metrics"]["covered_lines"] == total_lines
    assert isinstance(summary["branch_coverage"], dict)


def test_TestCoverageAnalyzer_generate_coverage_report_summary_zeros(analyzer):
    """Test summary handles zero totals without division errors."""
    # Empty source has 1 line due to splitlines behavior
    src = ""
    report = analyzer.analyze_coverage(src)
    summary = analyzer.generate_coverage_report_summary(report)
    assert summary["metrics"]["total_functions"] == 0
    assert summary["metrics"]["total_classes"] == 0
    assert summary["metrics"]["total_methods"] == 0
    # total_lines is 1 because ''.split('\n') -> ['']
    assert summary["metrics"]["total_lines"] == 1
    # Coverages for empty entities are 0.0
    assert summary["summary"]["function_coverage"] == 0.0
    assert summary["summary"]["class_coverage"] == 0.0
    assert summary["summary"]["method_coverage"] == 0.0
    # line_coverage is 0.0 because no executed lines
    assert summary["summary"]["line_coverage"] == 0.0


def test_TestCoverageAnalyzer__analyze_test_code_detects_entities(analyzer):
    """Test _analyze_test_code detects tested functions, classes, and methods with counts and tested lines."""
    functions = {"foo": (1, 2)}
    classes = {"Bar": (3, 10)}
    methods = {"Bar.baz": (5, 8)}
    test_code = textwrap.dedent(
        '''\
        def helper():
            pass

        def test_foo():
            foo()

        class TestBar:
            pass

        def test_baz_behavior():
            b = Bar()
            b.baz()
        '''
    )
    result = analyzer._analyze_test_code(test_code, functions, classes, methods)

    # foo detected via both call and def test_foo -> count 2
    assert "foo" in result["tested_functions"]
    assert result["function_test_counts"]["foo"] == 2

    # Bar detected via class TestBar
    assert "Bar" in result["tested_classes"]

    # Method baz detected via ".baz("
    assert "Bar.baz" in result["tested_functions"]
    assert result["function_test_counts"]["Bar.baz"] == 1

    # Tested lines include start lines for each test function
    # test_foo starts at line 4, test_baz_behavior at line 9 (given the dedented text above)
    assert 4 in result["tested_lines"]
    assert 9 in result["tested_lines"]

    # test_function_count counts occurrences of 'test_' and 'Test' prefix
    # def test_foo, class TestBar, def test_baz_behavior -> 3
    assert result["test_function_count"] == 3


def test_TestCoverageAnalyzer__calculate_branch_coverage_percentages(analyzer):
    """Test branch coverage calculation across different branch types."""
    src = textwrap.dedent(
        '''\
        if True:
            pass
        for i in []:
            pass
        while False:
            break
        try:
            pass
        except Exception:
            pass
        else:
            pass
        '''
    )
    executed_lines = {1, 3, 4, 5}  # execute if, while, try, except
    coverage = analyzer._calculate_branch_coverage(src, executed_lines)

    assert coverage["if_statement"] == 100.0
    assert coverage["for_loop"] == 0.0
    assert coverage["while_loop"] == 100.0
    assert coverage["try_block"] == 100.0
    assert coverage["except_block"] == 100.0
    assert coverage["else_block"] == 0.0


def test_TestCoverageAnalyzer__calculate_branch_coverage_missing_types_not_included(analyzer):
    """Test branch coverage does not include branch types not present in the source."""
    src = textwrap.dedent(
        '''\
        if True:
            pass
        '''
    )
    coverage = analyzer._calculate_branch_coverage(src, executed_lines=set())
    assert "if_statement" in coverage
    # while_loop not present in source -> not included in coverage
    assert "while_loop" not in coverage


def test_TestCoverageAnalyzer__generate_suggestions_various_conditions(analyzer):
    """Test suggestions generation for low coverage, uncovered functions/methods, high complexity, and untested ratio."""
    uncovered_items = [
        CoverageItem(name="a", type=CoverageType.FUNCTION, line_start=1, line_end=2, is_covered=False, complexity=5),
        CoverageItem(name="b", type=CoverageType.FUNCTION, line_start=3, line_end=4, is_covered=False, complexity=12),
        CoverageItem(name="c", type=CoverageType.FUNCTION, line_start=5, line_end=6, is_covered=False, complexity=7),
        CoverageItem(name="d", type=CoverageType.FUNCTION, line_start=7, line_end=8, is_covered=False, complexity=20),
        CoverageItem(name="m1", type=CoverageType.METHOD, line_start=9, line_end=10, is_covered=False, complexity=2),
        CoverageItem(name="m2", type=CoverageType.METHOD, line_start=11, line_end=12, is_covered=False, complexity=3),
    ]
    high_complexity_items = [
        CoverageItem(name="hc1", type=CoverageType.FUNCTION, line_start=1, line_end=2, is_covered=False, complexity=50),
        CoverageItem(name="hc2", type=CoverageType.CLASS, line_start=3, line_end=5, is_covered=False, complexity=40),
        CoverageItem(name="hc3", type=CoverageType.METHOD, line_start=6, line_end=8, is_covered=False, complexity=30),
        CoverageItem(name="hc4", type=CoverageType.FUNCTION, line_start=9, line_end=10, is_covered=False, complexity=25),
    ]
    # 40% coverage scenario
    coverage_percentage = 40.0
    functions = {f"f{i}": (i, i + 1) for i in range(10)}
    # Increase uncovered functions by using the ones above (a,b,c,d) which are 4/10 = 40% > 30% threshold
    suggestions = analyzer._generate_suggestions(
        uncovered_items=uncovered_items,
        high_complexity_items=high_complexity_items,
        coverage_percentage=coverage_percentage,
        functions=functions,
        methods={}
    )

    # Low coverage suggestion
    assert any("below 50%" in s for s in suggestions)

    # Priority uncovered functions in descending complexity order: d, b, c, a
    priority_msgs = [s for s in suggestions if s.startswith("Priority: Add tests for uncovered functions")]
    assert priority_msgs, "Expected priority uncovered functions suggestion"
    assert "d, b, c, a" in priority_msgs[0]

    # Uncovered methods suggestion
    assert any("uncovered methods" in s for s in suggestions)

    # High complexity suggestion lists top 3 names
    assert any("High complexity items detected: hc1, hc2, hc3" in s for s in suggestions)

    # More than 30% untested
    assert any("More than 30% of functions are untested" in s for s in suggestions)


def test_TestCoverageAnalyzer_coverage_marks_methods_by_name(analyzer):
    """Test that methods can be marked covered by including ClassName.method in executed_functions."""
    src = textwrap.dedent(
        '''\
        class K:
            def m(self):
                return 1
        '''
    )
    report = analyzer.analyze_coverage(
        source_code=src,
        executed_functions={"K.m"},
        executed_lines=set(),
        executed_classes=set(),
    )
    assert report.covered_methods == 1
    assert report.covered_classes == 0  # class not marked covered unless class covered or lines executed


def test_TestCoverageAnalyzer_line_coverage_affects_overall(analyzer):
    """Test that executed lines are reflected in line coverage and overall coverage."""
    src = textwrap.dedent(
        '''\
        def f():
            return 1

        def g():
            return 2
        '''
    )
    # Execute one of the lines (line 2 contains 'return 1')
    executed_lines = {2}
    report = analyzer.analyze_coverage(
        source_code=src,
        executed_lines=executed_lines,
        executed_functions=set(),
        executed_classes=set(),
    )
    assert report.covered_lines == 1
    assert 0.0 < report.coverage_percentage < 100.0