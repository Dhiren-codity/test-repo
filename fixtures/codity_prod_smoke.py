import ast


def run_formula(formula: str, row: dict) -> object:
    tree = ast.parse(formula, mode="eval")
    if not isinstance(tree.body, (ast.Name, ast.Constant, ast.BinOp)):
        raise ValueError("unsupported formula")
    return row.get(formula, formula)


def search_user(email: str) -> tuple[str, tuple[str]]:
    return "select id, email from users where email = %s", (email,)
