from typing import Dict, List
from dataclasses import dataclass
from src.code_reviewer import CodeReviewer


@dataclass
class ReviewStatistics:
    total_files: int
    average_score: float
    total_issues: int
    issues_by_severity: Dict[str, int]
    average_complexity: float
    files_with_high_complexity: int
    total_suggestions: int


class StatisticsAggregator:
    def __init__(self):
        self.reviewer = CodeReviewer()

    def aggregate_reviews(self, files: List[Dict[str, str]]) -> ReviewStatistics:
        if not files:
            return ReviewStatistics(
                total_files=0,
                average_score=0.0,
                total_issues=0,
                issues_by_severity={},
                average_complexity=0.0,
                files_with_high_complexity=0,
                total_suggestions=0,
            )

        total_score = 0.0
        total_issues = 0
        total_complexity = 0.0
        files_with_high_complexity = 0
        total_suggestions = 0
        issues_by_severity = {"error": 0, "warning": 0, "info": 0}

        for file_data in files:
            content = file_data.get("content", "")
            language = file_data.get("language", "python")

            if not content:
                continue

            result = self.reviewer.review_code(content, language)
            total_score += result.score
            total_issues += len(result.issues)
            total_complexity += result.complexity_score
            total_suggestions += len(result.suggestions)

            if result.complexity_score > 0.7:
                files_with_high_complexity += 1

            for issue in result.issues:
                severity = issue.severity
                if severity in issues_by_severity:
                    issues_by_severity[severity] += 1

        file_count = len(files)

        return ReviewStatistics(
            total_files=file_count,
            average_score=round(total_score / file_count, 2) if file_count > 0 else 0.0,
            total_issues=total_issues,
            issues_by_severity=issues_by_severity,
            average_complexity=round(total_complexity / file_count, 2) if file_count > 0 else 0.0,
            files_with_high_complexity=files_with_high_complexity,
            total_suggestions=total_suggestions,
        )
