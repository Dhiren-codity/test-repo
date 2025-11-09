import re
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class CodeIssue:
    severity: str
    line: int
    message: str
    suggestion: Optional[str] = None


@dataclass
class ReviewResult:
    score: float
    issues: List[CodeIssue]
    suggestions: List[str]
    complexity_score: float


class CodeReviewer:
    def __init__(self):
        self.complexity_patterns = [
            r"\bif\s+",
            r"\bfor\s+",
            r"\bwhile\s+",
            r"\btry\s*:",
            r"\bexcept\s+",
            r"\bswitch\s+",
            r"\bcase\s+",
        ]

        self.smell_patterns = [
            (r"def\s+\w+\([^)]*\):\s*pass", "Empty function detected"),
            (r"print\s*\(", "Debug print statement found"),
            (r"todo|fixme|hack|xxx", "TODO/FIXME comment found", re.IGNORECASE),
            (r"\.\.\.", "Ellipsis placeholder found"),
        ]

    def review_code(self, content: str, language: str = "python") -> ReviewResult:
        lines = content.split("\n")
        issues = []
        suggestions = []
        complexity_count = 0

        for line_num, line in enumerate(lines, 1):
            line_issues = self._analyze_line(line, line_num, language)
            issues.extend(line_issues)

            complexity_count += self._count_complexity(line)

        complexity_score = self._calculate_complexity_score(
            complexity_count, len(lines)
        )

        if complexity_score > 0.7:
            suggestions.append("Consider refactoring to reduce cyclomatic complexity")

        if len(issues) > 10:
            suggestions.append("High number of issues detected. Consider code review")

        score = self._calculate_score(issues, complexity_score)

        return ReviewResult(
            score=score,
            issues=issues,
            suggestions=suggestions,
            complexity_score=complexity_score,
        )

    def _analyze_line(self, line: str, line_num: int, language: str) -> List[CodeIssue]:
        issues = []

        stripped = line.strip()

        if len(line) > 120:
            issues.append(
                CodeIssue(
                    severity="warning",
                    line=line_num,
                    message="Line exceeds 120 characters",
                    suggestion="Consider breaking into multiple lines",
                )
            )

        if stripped.endswith(";") and language == "python":
            issues.append(
                CodeIssue(
                    severity="info",
                    line=line_num,
                    message="Unnecessary semicolon in Python",
                    suggestion="Remove semicolon",
                )
            )

        for pattern, message, *flags in self.smell_patterns:
            flag = flags[0] if flags else 0
            if re.search(pattern, line, flag):
                issues.append(
                    CodeIssue(
                        severity="warning",
                        line=line_num,
                        message=message,
                        suggestion="Review and address",
                    )
                )

        if re.search(r'\bpassword\s*=\s*["\']', line, re.IGNORECASE):
            issues.append(
                CodeIssue(
                    severity="error",
                    line=line_num,
                    message="Potential hardcoded password",
                    suggestion="Use environment variables or secure storage",
                )
            )

        return issues

    def _count_complexity(self, line: str) -> int:
        count = 0
        for pattern in self.complexity_patterns:
            if re.search(pattern, line):
                count += 1
        return count

    def _calculate_complexity_score(
        self, complexity_count: int, total_lines: int
    ) -> float:
        if total_lines == 0:
            return 0.0
        normalized = complexity_count / total_lines
        return min(normalized, 1.0)

    def _calculate_score(
        self, issues: List[CodeIssue], complexity_score: float
    ) -> float:
        base_score = 100.0

        error_penalty = sum(10 for issue in issues if issue.severity == "error")
        warning_penalty = sum(5 for issue in issues if issue.severity == "warning")
        info_penalty = sum(1 for issue in issues if issue.severity == "info")

        complexity_penalty = complexity_score * 20

        score = (
            base_score
            - error_penalty
            - warning_penalty
            - info_penalty
            - complexity_penalty
        )

        return max(0.0, min(100.0, score))

    def review_function(self, function_code: str) -> Dict:
        lines = function_code.split("\n")
        param_match = re.search(r"\(([^)]*)\)", function_code)
        if param_match:
            params_str = param_match.group(1)
            param_count = (
                len([p for p in params_str.split(",") if p.strip()])
                if params_str.strip()
                else 0
            )
        else:
            param_count = 0

        if param_count > 5:
            return {
                "warning": "Function has too many parameters",
                "suggestion": "Consider using a configuration object or data class",
            }

        if len(lines) > 50:
            return {
                "warning": "Function is too long",
                "suggestion": "Consider breaking into smaller functions",
            }

        return {"status": "ok"}
