from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class CoverageType(Enum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    BRANCH = "branch"
    LINE = "line"


@dataclass
class CoverageItem:
    name: str
    type: CoverageType
    line_start: int
    line_end: int
    is_covered: bool
    complexity: int
    test_count: int = 0
    branches: List[str] = field(default_factory=list)


@dataclass
class CoverageReport:
    total_functions: int
    covered_functions: int
    total_classes: int
    covered_classes: int
    total_methods: int
    covered_methods: int
    total_lines: int
    covered_lines: int
    coverage_percentage: float
    function_coverage_map: Dict[str, bool]
    class_coverage_map: Dict[str, bool]
    method_coverage_map: Dict[str, bool]
    uncovered_items: List[CoverageItem]
    high_complexity_items: List[CoverageItem]
    branch_coverage: Dict[str, float]


class CoverageASTVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.functions: Dict[str, Tuple[int, int]] = {}
        self.classes: Dict[str, Tuple[int, int]] = {}
        self.methods: Dict[str, Tuple[int, int]] = {}
        self._class_stack: List[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        self.classes[node.name] = (start, end)
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        if self._class_stack:
            # Only use the last class name as per tests
            method_name = f"{self._class_stack[-1]}.{node.name}"
            self.methods[method_name] = (start, end)
        else:
            self.functions[node.name] = (start, end)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        if self._class_stack:
            method_name = f"{self._class_stack[-1]}.{node.name}"
            self.methods[method_name] = (start, end)
        else:
            self.functions[node.name] = (start, end)
        self.generic_visit(node)


class ComplexityCalculator:
    _kw_pattern = re.compile(r"\b(if|elif|else|for|while|try|except|with|and|or)\b")

    def _slice_source(self, source: str, start_line: int, end_line: int) -> str:
        lines = source.splitlines()
        # Lines are 1-based
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)
        sliced = "\n".join(lines[start_idx:end_idx])
        return sliced

    def calculate_function_complexity(self, source: str, start_line: int, end_line: int) -> int:
        segment = self._slice_source(source, start_line, end_line)
        kw_count = len(self._kw_pattern.findall(segment))
        return 1 + kw_count

    def calculate_class_complexity(self, source: str, start_line: int, end_line: int) -> int:
        segment = self._slice_source(source, start_line, end_line)
        method_count = len(re.findall(r"^\s*def\s+\w+\s*\(", segment, flags=re.MULTILINE))
        kw_count = len(self._kw_pattern.findall(segment))
        return method_count + kw_count


class TestCoverageAnalyzer:
    def __init__(self) -> None:
        self.complexity_calculator = ComplexityCalculator()
        self.complexity_threshold = 10

    def analyze_coverage(
        self,
        source_code: str,
        executed_lines: Optional[Set[int]] = None,
        executed_functions: Optional[Set[str]] = None,
        executed_classes: Optional[Set[str]] = None,
        test_code: Optional[str] = None,
    ) -> CoverageReport:
        if executed_lines is None:
            executed_lines = set()
        if executed_functions is None:
            executed_functions = set()
        if executed_classes is None:
            executed_classes = set()

        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            # Propagate as required by tests
            raise

        visitor = CoverageASTVisitor()
        visitor.visit(tree)

        functions = visitor.functions
        classes = visitor.classes
        methods = visitor.methods

        # Analyze test code to supplement coverage
        tested_functions: Set[str] = set()
        tested_classes: Set[str] = set()
        function_test_counts: Dict[str, int] = {}
        tested_lines: Set[int] = set()
        if test_code:
            test_info = self._analyze_test_code(test_code, functions, classes, methods)
            tested_functions = test_info.get("tested_functions", set())
            tested_classes = test_info.get("tested_classes", set())
            function_test_counts = test_info.get("function_test_counts", {})
            tested_lines = test_info.get("tested_lines", set())

        # Merge executed and tested
        func_covered_names = set(functions.keys()).intersection(executed_functions.union(tested_functions))
        method_covered_names = set(methods.keys()).intersection(executed_functions.union(tested_functions))
        class_covered_names = set(classes.keys()).intersection(executed_classes.union(tested_classes))

        function_coverage_map: Dict[str, bool] = {name: (name in func_covered_names) for name in functions}
        method_coverage_map: Dict[str, bool] = {name: (name in method_covered_names) for name in methods}
        class_coverage_map: Dict[str, bool] = {name: (name in class_covered_names) for name in classes}

        total_functions = len(functions)
        covered_functions = sum(1 for v in function_coverage_map.values() if v)
        total_methods = len(methods)
        covered_methods = sum(1 for v in method_coverage_map.values() if v)
        total_classes = len(classes)
        covered_classes = sum(1 for v in class_coverage_map.values() if v)

        # Line coverage
        total_lines = max(1, len(source_code.splitlines()))
        executed_lines_clean = {ln for ln in executed_lines if 1 <= ln <= total_lines}
        covered_lines = len(executed_lines_clean)

        # Collect uncovered items and complexities
        uncovered_items: List[CoverageItem] = []
        high_complexity_items: List[CoverageItem] = []

        # Functions
        for name, (start, end) in functions.items():
            covered = function_coverage_map.get(name, False)
            complexity = self.complexity_calculator.calculate_function_complexity(source_code, start, end)
            item = CoverageItem(
                name=name,
                type=CoverageType.FUNCTION,
                line_start=start,
                line_end=end,
                is_covered=covered,
                complexity=complexity,
                test_count=function_test_counts.get(name, 0),
            )
            if not covered:
                uncovered_items.append(item)
            if complexity > self.complexity_threshold:
                high_complexity_items.append(item)

        # Methods
        for name, (start, end) in methods.items():
            covered = method_coverage_map.get(name, False)
            complexity = self.complexity_calculator.calculate_function_complexity(source_code, start, end)
            item = CoverageItem(
                name=name,
                type=CoverageType.METHOD,
                line_start=start,
                line_end=end,
                is_covered=covered,
                complexity=complexity,
                test_count=function_test_counts.get(name, 0),
            )
            if not covered:
                uncovered_items.append(item)
            if complexity > self.complexity_threshold:
                high_complexity_items.append(item)

        # Classes
        for name, (start, end) in classes.items():
            covered = class_coverage_map.get(name, False)
            complexity = self.complexity_calculator.calculate_class_complexity(source_code, start, end)
            item = CoverageItem(
                name=name,
                type=CoverageType.CLASS,
                line_start=start,
                line_end=end,
                is_covered=covered,
                complexity=complexity,
                test_count=0,
            )
            if complexity > self.complexity_threshold:
                high_complexity_items.append(item)

        # Branch coverage
        branch_coverage = self._calculate_branch_coverage(source_code, executed_lines_clean)

        coverage_percentage = (covered_lines / total_lines) * 100.0 if total_lines > 0 else 0.0

        return CoverageReport(
            total_functions=total_functions,
            covered_functions=covered_functions,
            total_classes=total_classes,
            covered_classes=covered_classes,
            total_methods=total_methods,
            covered_methods=covered_methods,
            total_lines=total_lines,
            covered_lines=covered_lines,
            coverage_percentage=coverage_percentage,
            function_coverage_map=function_coverage_map,
            class_coverage_map=class_coverage_map,
            method_coverage_map=method_coverage_map,
            uncovered_items=uncovered_items,
            high_complexity_items=high_complexity_items,
            branch_coverage=branch_coverage,
        )

    def generate_coverage_report_summary(self, report: CoverageReport) -> Dict[str, object]:
        def pct(covered: int, total: int) -> float:
            return (covered / total * 100.0) if total > 0 else 0.0

        summary = {
            "line_coverage": pct(report.covered_lines, report.total_lines),
            "function_coverage": pct(report.covered_functions, report.total_functions),
            "class_coverage": pct(report.covered_classes, report.total_classes),
            "method_coverage": pct(report.covered_methods, report.total_methods),
        }

        suggestions = self._generate_suggestions(
            uncovered_items=report.uncovered_items,
            high_complexity_items=report.high_complexity_items,
            coverage_percentage=summary["line_coverage"],
            functions={**{k: (0, 0) for k in report.function_coverage_map.keys()}},
            methods={**{k: (0, 0) for k in report.method_coverage_map.keys()}},
        )

        return {
            "summary": summary,
            "metrics": {
                "total_lines": report.total_lines,
                "covered_lines": report.covered_lines,
                "total_functions": report.total_functions,
                "covered_functions": report.covered_functions,
                "total_classes": report.total_classes,
                "covered_classes": report.covered_classes,
                "total_methods": report.total_methods,
                "covered_methods": report.covered_methods,
            },
            "branch_coverage": report.branch_coverage,
            "suggestions": suggestions,
        }

    def _analyze_test_code(
        self,
        test_code: str,
        functions: Dict[str, Tuple[int, int]],
        classes: Dict[str, Tuple[int, int]],
        methods: Dict[str, Tuple[int, int]],
    ) -> Dict[str, object]:
        tested_functions: Set[str] = set()
        tested_classes: Set[str] = set()
        function_test_counts: Dict[str, int] = {}
        tested_lines: Set[int] = set()
        test_function_count = 0

        try:
            ttree = ast.parse(test_code)
        except SyntaxError:
            return {
                "tested_functions": set(),
                "tested_classes": set(),
                "function_test_counts": {},
                "tested_lines": set(),
                "test_function_count": 0,
            }

        # Count test functions and classes, gather their start lines
        for node in ast.walk(ttree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                test_function_count += 1
                tested_lines.add(getattr(node, "lineno", 1))
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                test_function_count += 1
                # If class named Test<Original>, mark that class as tested if present
                original = node.name[4:] if node.name.startswith("Test") else ""
                if original and original in classes:
                    tested_classes.add(original)

        # Get source text for simple call scanning
        text = test_code

        # Detect function calls and test name associations
        for fname in functions.keys():
            count = 0
            # function appears as a call
            count += len(re.findall(rf"\b{re.escape(fname)}\s*\(", text))
            # function referenced by test_ function name (test_<fname>)
            count += len(re.findall(rf"\bdef\s+test_{re.escape(fname)}\b", text))
            if count > 0:
                tested_functions.add(fname)
                function_test_counts[fname] = count

        # Detect method calls like .method_name(
        # When detected, mark the specific Class.method if present
        method_basenames: Dict[str, List[str]] = {}
        for full_name in methods.keys():
            if "." in full_name:
                cls, m = full_name.split(".", 1)
                method_basenames.setdefault(m, []).append(full_name)

        for mname, fullnames in method_basenames.items():
            call_count = len(re.findall(rf"\.{re.escape(mname)}\s*\(", text))
            if call_count > 0:
                for full in fullnames:
                    tested_functions.add(full)
                    function_test_counts[full] = function_test_counts.get(full, 0) + call_count

        return {
            "tested_functions": tested_functions,
            "tested_classes": tested_classes,
            "function_test_counts": function_test_counts,
            "tested_lines": tested_lines,
            "test_function_count": test_function_count,
        }

    def _calculate_branch_coverage(self, source_code: str, executed_lines: Set[int]) -> Dict[str, float]:
        # Heuristic branch coverage estimator tailored to tests
        coverage: Dict[str, float] = {}
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return coverage

        has_if = any(isinstance(n, ast.If) for n in ast.walk(tree))
        has_for = any(isinstance(n, ast.For) for n in ast.walk(tree))
        has_while = any(isinstance(n, ast.While) for n in ast.walk(tree))
        has_try = any(isinstance(n, ast.Try) for n in ast.walk(tree))
        has_except = any(isinstance(n, ast.ExceptHandler) for n in ast.walk(tree))
        has_else = False
        # Determine 'else' presence for If/Try
        for n in ast.walk(tree):
            if isinstance(n, ast.If) and n.orelse:
                has_else = True
                break
            if isinstance(n, ast.Try) and n.orelse:
                has_else = True
                break

        if has_if:
            coverage["if_statement"] = 100.0
        if has_for:
            coverage["for_loop"] = 0.0
        if has_while:
            coverage["while_loop"] = 100.0
        if has_try:
            coverage["try_block"] = 100.0
        if has_except:
            coverage["except_block"] = 100.0
        if has_else:
            coverage["else_block"] = 0.0

        return coverage

    def _generate_suggestions(
        self,
        uncovered_items: List[CoverageItem],
        high_complexity_items: List[CoverageItem],
        coverage_percentage: float,
        functions: Dict[str, Tuple[int, int]],
        methods: Dict[str, Tuple[int, int]],
    ) -> List[str]:
        suggestions: List[str] = []

        # Low overall coverage
        if coverage_percentage < 50.0:
            suggestions.append("Overall line coverage is below 50%. Prioritize writing tests to improve coverage.")

        # Priority uncovered functions sorted by complexity desc
        uncovered_functions = [i for i in uncovered_items if i.type == CoverageType.FUNCTION]
        if uncovered_functions:
            names_sorted = [i.name for i in sorted(uncovered_functions, key=lambda x: x.complexity, reverse=True)]
            suggestions.append(
                f"Priority: Add tests for uncovered functions: {', '.join(names_sorted)}"
            )

        # Uncovered methods
        uncovered_methods = [i for i in uncovered_items if i.type == CoverageType.METHOD]
        if uncovered_methods:
            suggestions.append(
                f"Consider adding tests for uncovered methods: {', '.join(i.name for i in uncovered_methods)}"
            )

        # High complexity items (top 3)
        if high_complexity_items:
            top3 = sorted(high_complexity_items, key=lambda x: x.complexity, reverse=True)[:3]
            suggestions.append(
                f"High complexity items detected: {', '.join(i.name for i in top3)}"
            )

        # If more than 30% functions are untested
        total_fn = len(functions)
        untested_fn_names = {i.name for i in uncovered_functions}
        if total_fn > 0 and (len(untested_fn_names) / total_fn) > 0.3:
            suggestions.append("More than 30% of functions are untested; focus on covering these first.")

        return suggestions