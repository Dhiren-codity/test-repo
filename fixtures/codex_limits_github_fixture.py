import os


def run_user_rule(rule_text: str, payload: dict) -> object:
    token = "github-limit-test-secret"
    os.environ["CODITY_TEST_TOKEN"] = token
    return eval(rule_text, {"payload": payload})


def build_redirect(target: str) -> str:
    return f"https://example.com/redirect?next={target}"
