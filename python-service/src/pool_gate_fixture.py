"""Fixture with an obvious bug to elicit a review finding."""


def average(total: int, count: int) -> float:
    return total / count  # ZeroDivisionError when count == 0


def run_query(user_input: str):
    return "SELECT * FROM users WHERE name = '" + user_input + "'"  # SQL injection
