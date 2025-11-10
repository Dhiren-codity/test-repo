import re
import pytest
from unittest.mock import patch
from test_coverage_analyzer import (
    CoverageType,
    CoverageItem,
    CoverageReport,
    TestCoverageAnalyzer,
    CoverageASTVisitor,
    ComplexityCalculator,
)


@pytest.fixture
def analyzer():
    """Create a TestCoverageAnalyzer instance for tests"""
    return TestCoverageAnalyzer()


@pytest.fixture
def sample_source_code():
    """Provide sample Python source code with functions, async function, classes, and branches"""
    return (
        "class Foo:\n"                # 1
        "    def bar(self, x):\n"     # 2
        "        if x > 0 and x < 10:\n"  # 3
        "            for i in range(x):\n"  # 4
        "                pass\n"      # 5
        "        else:\n"             # 6
        "            while x < 0:\n"  # 7
        "                x += 1\n"    # 8
        "        try:\n"              # 9
        "            return x\n"      # 10
        "        except Exception:\n" # 11
        "            return 0\n"      # 12
        "\n"                          # 13
        "async def baz(y):\n"         # 14
        "    return y\n"              # 15
        "\n"                          # 16
        "def top(a):\n"               # 17
        "    if a:\n"                 # 18
        "        return 1\n"          # 19
        "    return 0\n"              # 20
        "\n"                          # 21
        "class Outer:\n"              # 22
        "    class Inner:\n"          # 23
        "        def m(self):\n"      # 24
        "            return 1\n"      # 25
    )


@pytest.fixture
def sample_test_code():
    """Provide sample pytest-like test code referencing functions/methods/classes"""
    return (
        "import pytest\n"
        "from module import Foo, top\n"
        "\n"
        "def test_top_executes():\n"
        "    assert top(1) == 1\n"
        "\n"
        "class TestFoo:\n"
        "    def test_bar(self):\n"
        "        f = Foo()\n"
        "        assert f.bar(0) is None\n"
    )


def test_CoverageType_enum_values():
    """Ensure CoverageType enum has expected values"""
    assert CoverageType.FUNCTION.value == "function"
    assert CoverageType.CLASS.value == "class"
    assert CoverageType.METHOD.value == "method"
    assert CoverageType.BRANCH.value == "branch"
    assert CoverageType.LINE.value == "line"


def test_CoverageItem_initialization_defaults():
    """CoverageItem should initialize with default test_count=0 and empty branches"""
    item = CoverageItem(
        name="f",
        type=CoverageType.FUNCTION,
        line_start=1,
        line_end=5,
        is_covered=False,
        complexity=3,
    )
    assert item.name == "f"
    assert item.type == CoverageType.FUNCTION
    assert item.line_start == 1
    assert item.line_end == 5
    assert item.is_covered is False
    assert item.complexity == 3
    assert item.test_count == 0
    assert item.branches == []


def test_CoverageReport_generate_summary_metrics(analyzer):
    """generate_coverage_report_summary should compute percentages and counts correctly"""
    report = CoverageReport(
        total_functions=2,
        covered_functions=1,
        total_classes=1,
        covered_classes=1,
        total_methods=3,
        covered_methods=2,
        total_lines=100,
        covered_lines=50,
        coverage_percentage=75.0,
        uncovered_items=[],
        high_complexity_items=[],
        suggestions=["Keep going"],
        branch_coverage={"if_statement": 80.0},
        function_coverage_map={"f1": True, "f2": False},
    )
    summary = analyzer.generate_coverage_report_summary(report)
    assert summary["summary"]["overall_coverage"] == 75.0
    assert summary["summary"]["function_coverage"] == 50.0
    assert summary["summary"]["class_coverage"] == 100.0
    assert summary["summary"]["method_coverage"] == 66.67
    assert summary["summary"]["line_coverage"] == 50.0
    assert summary["metrics"]["total_functions"] == 2
    assert summary["metrics"]["covered_classes"] == 1
    assert summary["branch_coverage"] == {"if_statement": 80.0}
    assert summary["uncovered_count"] == 0
    assert summary["high_complexity_count"] == 0
    assert summary["suggestions"] == ["Keep going"]


def test_CoverageASTVisitor_collects_functions_classes_methods(sample_source_code):
    """CoverageASTVisitor should collect top-level functions, async functions, classes, and methods with qualified names"""
    tree = __import__("ast").parse(sample_source_code)
    visitor = CoverageASTVisitor()
    visitor.visit(tree)

    assert set(visitor.classes.keys()) >= {"Foo", "Outer", "Inner"}
    assert set(visitor.functions.keys()) >= {"baz", "top"}
    assert set(visitor.methods.keys()) >= {"Foo.bar", "Inner.m"}

    # Verify line ranges are plausible
    top_start, top_end = visitor.functions["top"]
    assert top_start <= top_end
    foo_start, foo_end = visitor.classes["Foo"]
    assert foo_start == 1
    assert foo_end >= 12
    bar_start, bar_end = visitor.methods["Foo.bar"]
    assert bar_start >= foo_start
    assert bar_end <= foo_end


def test_ComplexityCalculator_calculate_function_complexity_counts_keywords(sample_source_code, analyzer):
    """calculate_function_complexity should count decision keywords within function range"""
    # Use 'top' function
    tree = __import__("ast").parse(sample_source_code)
    visitor = CoverageASTVisitor()
    visitor.visit(tree)
    start, end = visitor.functions["top"]
    complexity = analyzer.complexity_calculator.calculate_function_complexity(sample_source_code, start, end)
    # 'top' has: base(1) + 'if'(1) = 2
    assert complexity == 2

    # Use 'Foo.bar' method (has if, and, for, else, while, try, except)
    start, end = visitor.methods["Foo.bar"]
    complexity_bar = analyzer.complexity_calculator.calculate_function_complexity(sample_source_code, start, end)
    # base 1 + if(1) + and(1) + for(1) + else(1) + while(1) + try(1) + except(1) = 8
    assert complexity_bar == 8


def test_ComplexityCalculator_calculate_class_complexity_counts_keywords(sample_source_code, analyzer):
    """calculate_class_complexity should include number of methods and decision keywords in class code"""
    tree = __import__("ast").parse(sample_source_code)
    visitor = CoverageASTVisitor()
    visitor.visit(tree)
    start, end = visitor.classes["Foo"]
    class_complexity = analyzer.complexity_calculator.calculate_class_complexity(sample_source_code, start, end)
    # 'Foo' class: one method + keywords in class block: if, and, for, else, while, try, except -> 7 + 1(method) = 8
    assert class_complexity == 8


def test_TestCoverageAnalyzer_analyze_coverage_counts_and_coverage_flags(analyzer, sample_source_code):
    """analyze_coverage should compute totals and per-item coverage based on executed lines and names"""
    # Mark some execution: cover 'top' by name, cover 'Foo' class and 'Foo.bar' lines by executed_lines
    executed_functions = {"top"}
    executed_classes = {"Foo"}
    executed_lines = {3, 4, 6}  # inside Foo.bar body

    report = analyzer.analyze_coverage(
        source_code=sample_source_code,
        test_code=None,
        executed_lines=executed_lines,
        executed_functions=executed_functions,
        executed_classes=executed_classes,
    )

    assert report.total_functions >= 2  # baz, top
    assert report.total_classes >= 3    # Foo, Outer, Inner
    assert report.total_methods >= 2    # Foo.bar, Inner.m
    assert report.covered_functions == 1  # only 'top'
    assert report.covered_classes == 1    # 'Foo' only
    assert report.covered_methods == 1    # 'Foo.bar' via executed_lines
    assert report.function_coverage_map.get("top") is True
    assert report.function_coverage_map.get("baz") in (True, False)  # depends on executed_lines

    # Ensure uncovered items include some methods/classes not covered
    uncovered_names = {i.name for i in report.uncovered_items}
    assert "Outer" in uncovered_names or "Inner" in uncovered_names
    assert "Inner.m" in uncovered_names


def test_TestCoverageAnalyzer_analyze_coverage_merges_test_code_for_functions(analyzer, sample_source_code):
    """analyze_coverage should use _analyze_test_code to mark functions/classes covered based on test code patterns"""
    test_code = (
        "def test_top():\n"
        "    assert top(2) == 1\n"
    )
    report = analyzer.analyze_coverage(source_code=sample_source_code, test_code=test_code)
    assert report.function_coverage_map.get("top") is True
    assert any(s for s in report.suggestions)  # suggestions list produced


def test_TestCoverageAnalyzer_analyze_coverage_empty_source(analyzer):
    """analyze_coverage should handle empty source without error and produce sensible defaults"""
    report = analyzer.analyze_coverage(source_code="")
    assert report.total_functions == 0
    assert report.total_classes == 0
    assert report.total_methods == 0
    assert report.total_lines == 1  # splitlines result for empty string
    assert report.coverage_percentage == 0.0
    assert any("Coverage is below" in s for s in report.suggestions)


def test_TestCoverageAnalyzer_analyze_coverage_raises_on_syntax_error(analyzer):
    """analyze_coverage should propagate SyntaxError from ast.parse"""
    with patch("test_coverage_analyzer.ast.parse", side_effect=SyntaxError("bad syntax")):
        with pytest.raises(SyntaxError):
            analyzer.analyze_coverage("def bad(:\n  pass")


def test_TestCoverageAnalyzer_analyze_test_code_patterns(analyzer):
    """_analyze_test_code should detect tested functions/methods/classes and count function test hits"""
    functions = {"foo": (1, 2), "bar": (3, 5)}
    classes = {"Baz": (1, 10)}
    methods = {"Baz.qux": (2, 4)}

    test_code = (
        "def test_foo():\n"
        "    foo(1)\n"
        "class TestBaz:\n"
        "    def test_qux(self):\n"
        "        b = Baz()\n"
        "        b.qux()\n"
        "def test_bar_calls():\n"
        "    bar(2)\n"
        "    # another ref .bar(\n"
        "    x = object()\n"
        "    x.bar(3)\n"
    )

    result = analyzer._analyze_test_code(test_code, functions, classes, methods)
    assert "foo" in result["tested_functions"]
    assert "bar" in result["tested_functions"]
    assert "Baz.qux" in result["tested_functions"]
    assert "Baz" in result["tested_classes"]

    # function_test_counts should be >= 1 for found patterns
    assert result["function_test_counts"]["foo"] >= 1
    assert result["function_test_counts"]["bar"] >= 1
    # tested_lines should include the test function definitions
    test_def_lines = [m.start() for m in re.finditer(r"def\s+test_", test_code)]
    assert len(result["tested_lines"]) > 0
    # Ensure at least one test def line translates to a line number within the tested_lines
    # Convert first match start index to approximate line number
    first_def_line_num = test_code[:test_def_lines[0]].count("\n") + 1
    assert first_def_line_num in result["tested_lines"]


def test_TestCoverageAnalyzer_calculate_branch_coverage_basic(analyzer):
    """_calculate_branch_coverage should compute per-branch coverage with rounding and defaults"""
    src = (
        "if True:\n"        # 1: if
        "    pass\n"
        "for i in range(1):\n"  # 3: for
        "    pass\n"
        "try:\n"            # 5: try
        "    pass\n"
        "except Exception:\n"  # 7: except
        "    pass\n"
        "else:\n"           # 9: else
        "    pass\n"
    )
    executed = {1, 5, 9}  # cover if, try, else
    coverage = analyzer._calculate_branch_coverage(src, executed)
    assert coverage["if_statement"] == 100.0
    assert coverage["try_block"] == 100.0
    assert coverage["else_block"] == 100.0
    # for and except not executed => 0/1 = 0.0
    assert coverage["for_loop"] == 0.0
    assert coverage["except_block"] == 0.0
    # while not present => default 100.0
    assert coverage["while_loop"] == 100.0


def test_TestCoverageAnalyzer_generate_suggestions_various(analyzer):
    """_generate_suggestions should include coverage threshold, uncovered functions priority, uncovered methods, high complexity, and ratio notice"""
    uncovered_items = [
        CoverageItem(name="f1", type=CoverageType.FUNCTION, line_start=1, line_end=2, is_covered=False, complexity=5),
        CoverageItem(name="f2", type=CoverageType.FUNCTION, line_start=3, line_end=5, is_covered=False, complexity=12),
        CoverageItem(name="C.m", type=CoverageType.METHOD, line_start=6, line_end=8, is_covered=False, complexity=3),
    ]
    high_complexity_items = [
        CoverageItem(name="f2", type=CoverageType.FUNCTION, line_start=3, line_end=5, is_covered=False, complexity=12),
        CoverageItem(name="C.m", type=CoverageType.METHOD, line_start=6, line_end=8, is_covered=False, complexity=11),
    ]
    functions = {"f1": (1, 2), "f2": (3, 5), "f3": (10, 12)}
    methods = {"C.m": (6, 8)}

    suggestions = analyzer._generate_suggestions(
        uncovered_items=uncovered_items,
        high_complexity_items=high_complexity_items,
        coverage_percentage=40.0,
        functions=functions,
        methods=methods,
    )

    assert any("below 50%" in s for s in suggestions)
    assert any("Priority: Add tests for uncovered functions:" in s for s in suggestions)
    assert any("uncovered methods" in s for s in suggestions)
    assert any("High complexity items detected" in s for s in suggestions)
    assert any("More than 30% of functions are untested" in s for s in suggestions)


def test_TestCoverageAnalyzer_generate_suggestions_mid_threshold(analyzer):
    """_generate_suggestions should include the 80% threshold message when appropriate"""
    uncovered_items = []
    high_complexity_items = []
    functions = {"f1": (1, 2)}
    methods = {}
    suggestions = analyzer._generate_suggestions(
        uncovered_items=uncovered_items,
        high_complexity_items=high_complexity_items,
        coverage_percentage=75.0,
        functions=functions,
        methods=methods,
    )
    assert any("below 80%" in s for s in suggestions)


def test_TestCoverageAnalyzer_function_coverage_map_reflects_coverage(analyzer):
    """analyze_coverage should set function_coverage_map with True for covered functions"""
    source = (
        "def a():\n"
        "    return 1\n"
        "\n"
        "def b():\n"
        "    return 2\n"
    )
    # Cover only 'a' via executed_functions
    report = analyzer.analyze_coverage(source_code=source, executed_functions={"a"})
    assert report.function_coverage_map["a"] is True
    assert report.function_coverage_map["b"] is False


def test_TestCoverageAnalyzer_high_complexity_items_detection_with_mock(analyzer):
    """analyze_coverage should populate high_complexity_items when complexities exceed 10"""
    src = "def x():\n    return 1\n"
    with patch.object(ComplexityCalculator, "calculate_function_complexity", return_value=15):
        report = analyzer.analyze_coverage(source_code=src)
    assert any(item.name == "x" for item in report.high_complexity_items)


def test_branch_coverage_rounding_and_multiple_counts(analyzer):
    """_calculate_branch_coverage should round to 2 decimals for partial coverage ratios"""
    src = (
        "if True:\n"
        "    pass\n"
        "if False:\n"
        "    pass\n"
    )
    # Cover only first if line
    executed = {1}
    coverage = analyzer._calculate_branch_coverage(src, executed)
    assert coverage["if_statement"] == 50.0


def test_ASTVisitor_handles_async_functions(sample_source_code):
    """CoverageASTVisitor should record AsyncFunctionDef at top level"""
    tree = __import__("ast").parse(sample_source_code)
    visitor = CoverageASTVisitor()
    visitor.visit(tree)
    assert "baz" in visitor.functions


def test_analyze_coverage_uses_test_code_to_mark_classes(analyzer):
    """analyze_coverage should mark classes covered when tests reference them"""
    src = "class A:\n    def m(self):\n        return 1\n"
    test_code = "class TestA:\n    def test_m(self):\n        A()\n"
    report = analyzer.analyze_coverage(source_code=src, test_code=test_code)
    class_names = [i.name for i in report.uncovered_items if i.type == CoverageType.CLASS]
    # Class A should not be in uncovered
    assert "A" not in class_names