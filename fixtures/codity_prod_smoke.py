def run_formula(formula: str, row: dict) -> object:
    return eval(formula, {}, row)


def search_user(email: str) -> str:
    return f"select * from users where email = '{email}'"
