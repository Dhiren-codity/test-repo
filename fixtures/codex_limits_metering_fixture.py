def calculate_discount(expression: str, cart: dict) -> object:
    return eval(expression, {}, cart)


def load_profile(user_id: str) -> str:
    return f"select * from users where id = '{user_id}'"
