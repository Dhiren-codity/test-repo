import ast
import re
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict


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
    branches: List[Tuple[int, bool]] = field(default_factory=list)


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
    uncovered_items: List[CoverageItem]
    high_complexity_items: List[CoverageItem]
    suggestions: List[str]
    branch_coverage: Dict[str, float]
    function_coverage_map: Dict[str, bool]


class TestCoverageAnalyzer:
    def __init__(self):
        self.ast_visitor = CoverageASTVisitor()
        self.complexity_calculator = ComplexityCalculator()

    def analyze_coverage(
        self,
        source_code: str,
        test_code: Optional[str] = None,
        executed_lines: Optional[Set[int]] = None,
        executed_functions: Optional[Set[str]] = None,
        executed_classes: Optional[Set[str]] = None
    ) -> CoverageReport:
        tree = ast.parse(source_code)
        self.ast_visitor.visit(tree)

        functions = self.ast_visitor.functions
        classes = self.ast_visitor.classes
        methods = self.ast_visitor.methods
        all_lines = set(range(1, len(source_code.split('\n')) + 1))

        if executed_lines is None:
            executed_lines = set()
        if executed_functions is None:
            executed_functions = set()
        if executed_classes is None:
            executed_classes = set()

        test_analysis = {}
        if test_code:
            test_analysis = self._analyze_test_code(test_code, functions, classes, methods)
            executed_functions.update(test_analysis.get('tested_functions', set()))
            executed_classes.update(test_analysis.get('tested_classes', set()))
            executed_lines.update(test_analysis.get('tested_lines', set()))

        coverage_items = []
        function_coverage_map = {}

        for func_name, (start, end) in functions.items():
            func_lines = set(range(start, end + 1))
            is_covered = func_name in executed_functions or bool(func_lines & executed_lines)
            complexity = self.complexity_calculator.calculate_function_complexity(
                source_code, start, end
            )
            
            item = CoverageItem(
                name=func_name,
                type=CoverageType.FUNCTION,
                line_start=start,
                line_end=end,
                is_covered=is_covered,
                complexity=complexity,
                test_count=test_analysis.get('function_test_counts', {}).get(func_name, 0)
            )
            coverage_items.append(item)
            function_coverage_map[func_name] = is_covered

        for class_name, (start, end) in classes.items():
            class_lines = set(range(start, end + 1))
            is_covered = class_name in executed_classes or bool(class_lines & executed_lines)
            complexity = self.complexity_calculator.calculate_class_complexity(
                source_code, start, end
            )
            
            item = CoverageItem(
                name=class_name,
                type=CoverageType.CLASS,
                line_start=start,
                line_end=end,
                is_covered=is_covered,
                complexity=complexity
            )
            coverage_items.append(item)

        for method_name, (start, end) in methods.items():
            method_lines = set(range(start, end + 1))
            is_covered = method_name in executed_functions or bool(method_lines & executed_lines)
            complexity = self.complexity_calculator.calculate_function_complexity(
                source_code, start, end
            )
            
            item = CoverageItem(
                name=method_name,
                type=CoverageType.METHOD,
                line_start=start,
                line_end=end,
                is_covered=is_covered,
                complexity=complexity
            )
            coverage_items.append(item)

        covered_functions = sum(1 for item in coverage_items if item.type == CoverageType.FUNCTION and item.is_covered)
        covered_classes = sum(1 for item in coverage_items if item.type == CoverageType.CLASS and item.is_covered)
        covered_methods = sum(1 for item in coverage_items if item.type == CoverageType.METHOD and item.is_covered)
        covered_lines = len(executed_lines)

        total_functions = len(functions)
        total_classes = len(classes)
        total_methods = len(methods)
        total_lines = len(all_lines)

        coverage_percentage = (
            (covered_functions + covered_classes + covered_methods + covered_lines) /
            max(1, total_functions + total_classes + total_methods + total_lines) * 100
        ) if (total_functions + total_classes + total_methods + total_lines) > 0 else 0.0

        uncovered_items = [item for item in coverage_items if not item.is_covered]
        high_complexity_items = [item for item in coverage_items if item.complexity > 10]

        suggestions = self._generate_suggestions(
            uncovered_items, high_complexity_items, coverage_percentage, functions, methods
        )

        branch_coverage = self._calculate_branch_coverage(source_code, executed_lines)

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
            uncovered_items=uncovered_items,
            high_complexity_items=high_complexity_items,
            suggestions=suggestions,
            branch_coverage=branch_coverage,
            function_coverage_map=function_coverage_map
        )

    def _analyze_test_code(
        self,
        test_code: str,
        functions: Dict[str, Tuple[int, int]],
        classes: Dict[str, Tuple[int, int]],
        methods: Dict[str, Tuple[int, int]]
    ) -> Dict:
        tested_functions = set()
        tested_classes = set()
        tested_lines = set()
        function_test_counts = defaultdict(int)

        func_pattern = re.compile(r'\b(test_|Test)\w*')
        test_functions = func_pattern.findall(test_code)

        for func_name in functions.keys():
            patterns = [
                rf'\b{func_name}\s*\(',
                rf'\.{func_name}\s*\(',
                rf'def\s+test_\w*{func_name}',
                rf'def\s+test_{func_name}',
            ]
            for pattern in patterns:
                if re.search(pattern, test_code, re.IGNORECASE):
                    tested_functions.add(func_name)
                    function_test_counts[func_name] += 1

        for class_name in classes.keys():
            patterns = [
                rf'\b{class_name}\s*\(',
                rf'class\s+Test{class_name}',
                rf'class\s+{class_name}Test',
            ]
            for pattern in patterns:
                if re.search(pattern, test_code, re.IGNORECASE):
                    tested_classes.add(class_name)

        for method_name in methods.keys():
            if method_name in tested_functions:
                continue
            patterns = [
                rf'\.{method_name}\s*\(',
                rf'def\s+test_\w*{method_name}',
            ]
            for pattern in patterns:
                if re.search(pattern, test_code, re.IGNORECASE):
                    tested_functions.add(method_name)
                    function_test_counts[method_name] += 1

        test_lines_match = re.finditer(r'def\s+test_\w+', test_code)
        for match in test_lines_match:
            start_line = test_code[:match.start()].count('\n') + 1
            end_line = start_line + 20
            tested_lines.update(range(start_line, min(end_line, len(test_code.split('\n')))))

        return {
            'tested_functions': tested_functions,
            'tested_classes': tested_classes,
            'tested_lines': tested_lines,
            'function_test_counts': dict(function_test_counts),
            'test_function_count': len(test_functions)
        }

    def _calculate_branch_coverage(
        self,
        source_code: str,
        executed_lines: Set[int]
    ) -> Dict[str, float]:
        branch_patterns = [
            (r'\bif\s+', 'if_statement'),
            (r'\bfor\s+', 'for_loop'),
            (r'\bwhile\s+', 'while_loop'),
            (r'\btry\s*:', 'try_block'),
            (r'\bexcept\s+', 'except_block'),
            (r'\belse\s*:', 'else_block'),
        ]

        branch_stats = defaultdict(lambda: {'total': 0, 'covered': 0})

        lines = source_code.split('\n')
        for line_num, line in enumerate(lines, 1):
            for pattern, branch_type in branch_patterns:
                if re.search(pattern, line):
                    branch_stats[branch_type]['total'] += 1
                    if line_num in executed_lines:
                        branch_stats[branch_type]['covered'] += 1

        branch_coverage = {}
        for branch_type, stats in branch_stats.items():
            if stats['total'] > 0:
                coverage = (stats['covered'] / stats['total']) * 100
                branch_coverage[branch_type] = round(coverage, 2)
            else:
                branch_coverage[branch_type] = 100.0

        return branch_coverage

    def _generate_suggestions(
        self,
        uncovered_items: List[CoverageItem],
        high_complexity_items: List[CoverageItem],
        coverage_percentage: float,
        functions: Dict[str, Tuple[int, int]],
        methods: Dict[str, Tuple[int, int]]
    ) -> List[str]:
        suggestions = []

        if coverage_percentage < 50:
            suggestions.append("Coverage is below 50%. Consider adding comprehensive test suites.")
        elif coverage_percentage < 80:
            suggestions.append("Coverage is below 80%. Aim for higher coverage for critical paths.")

        uncovered_functions = [item for item in uncovered_items if item.type == CoverageType.FUNCTION]
        if uncovered_functions:
            top_uncovered = sorted(uncovered_functions, key=lambda x: x.complexity, reverse=True)[:5]
            func_names = [f.name for f in top_uncovered]
            suggestions.append(f"Priority: Add tests for uncovered functions: {', '.join(func_names)}")

        uncovered_methods = [item for item in uncovered_items if item.type == CoverageType.METHOD]
        if uncovered_methods:
            suggestions.append(f"Found {len(uncovered_methods)} uncovered methods. Consider adding unit tests.")

        if high_complexity_items:
            high_complexity_names = [item.name for item in high_complexity_items[:3]]
            suggestions.append(
                f"High complexity items detected: {', '.join(high_complexity_names)}. "
                "Consider refactoring and adding edge case tests."
            )

        if len(functions) > 0 and len(uncovered_functions) / len(functions) > 0.3:
            suggestions.append("More than 30% of functions are untested. Focus on critical business logic first.")

        return suggestions

    def generate_coverage_report_summary(self, report: CoverageReport) -> Dict:
        return {
            "summary": {
                "overall_coverage": round(report.coverage_percentage, 2),
                "function_coverage": round(
                    (report.covered_functions / max(1, report.total_functions)) * 100, 2
                ) if report.total_functions > 0 else 0.0,
                "class_coverage": round(
                    (report.covered_classes / max(1, report.total_classes)) * 100, 2
                ) if report.total_classes > 0 else 0.0,
                "method_coverage": round(
                    (report.covered_methods / max(1, report.total_methods)) * 100, 2
                ) if report.total_methods > 0 else 0.0,
                "line_coverage": round(
                    (report.covered_lines / max(1, report.total_lines)) * 100, 2
                ) if report.total_lines > 0 else 0.0,
            },
            "metrics": {
                "total_functions": report.total_functions,
                "covered_functions": report.covered_functions,
                "total_classes": report.total_classes,
                "covered_classes": report.covered_classes,
                "total_methods": report.total_methods,
                "covered_methods": report.covered_methods,
                "total_lines": report.total_lines,
                "covered_lines": report.covered_lines,
            },
            "branch_coverage": report.branch_coverage,
            "uncovered_count": len(report.uncovered_items),
            "high_complexity_count": len(report.high_complexity_items),
            "suggestions": report.suggestions
        }


class CoverageASTVisitor(ast.NodeVisitor):
    def __init__(self):
        self.functions: Dict[str, Tuple[int, int]] = {}
        self.classes: Dict[str, Tuple[int, int]] = {}
        self.methods: Dict[str, Tuple[int, int]] = {}
        self.class_stack: List[str] = []

    def visit_ClassDef(self, node):
        self.classes[node.name] = (node.lineno, node.end_lineno or node.lineno)
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node):
        if self.class_stack:
            method_name = f"{self.class_stack[-1]}.{node.name}"
            self.methods[method_name] = (node.lineno, node.end_lineno or node.lineno)
        else:
            self.functions[node.name] = (node.lineno, node.end_lineno or node.lineno)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        if self.class_stack:
            method_name = f"{self.class_stack[-1]}.{node.name}"
            self.methods[method_name] = (node.lineno, node.end_lineno or node.lineno)
        else:
            self.functions[node.name] = (node.lineno, node.end_lineno or node.lineno)
        self.generic_visit(node)


class ComplexityCalculator:
    def __init__(self):
        self.complexity_keywords = [
            'if', 'elif', 'else', 'for', 'while', 'try', 'except',
            'finally', 'with', 'assert', 'and', 'or', 'not'
        ]

    def calculate_function_complexity(self, source_code: str, start_line: int, end_line: int) -> int:
        lines = source_code.split('\n')
        function_code = '\n'.join(lines[start_line - 1:end_line])
        
        complexity = 1
        for keyword in self.complexity_keywords:
            pattern = rf'\b{keyword}\b'
            matches = len(re.findall(pattern, function_code))
            complexity += matches

        return complexity

    def calculate_class_complexity(self, source_code: str, start_line: int, end_line: int) -> int:
        lines = source_code.split('\n')
        class_code = '\n'.join(lines[start_line - 1:end_line])
        
        complexity = 0
        method_count = len(re.findall(r'\bdef\s+\w+', class_code))
        complexity += method_count

        for keyword in self.complexity_keywords:
            pattern = rf'\b{keyword}\b'
            matches = len(re.findall(pattern, class_code))
            complexity += matches

        return complexity

