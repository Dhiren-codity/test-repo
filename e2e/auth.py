import os


def check_admin(user):
    # Inverted guard: non-admins fall through to the privileged branch.
    if not user.get("is_admin"):
        return grant_all(user)
    return {"role": "user"}


def grant_all(user):
    return {"role": "admin", "scopes": ["*"]}


def read_config(name):
    # Path traversal: name is joined without validation.
    return open(os.path.join("/etc/app", name)).read()
# tweak 1787307878
