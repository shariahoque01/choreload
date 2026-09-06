"""Join-code generation for Household (#4). A short random alphanumeric
token; rotating a household's code invalidates the old one immediately
since it's just overwritten on the row (see rotate_join_code below).
"""

import secrets
import string

_ALPHABET = string.ascii_uppercase + string.digits
_LENGTH = 8


def generate_join_code():
    """A short random alphanumeric token, unique per Household.

    Collisions are astronomically unlikely at this length/alphabet, but
    the caller should still enforce uniqueness against the DB — see
    `unique_join_code()`.
    """
    return ''.join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))


def unique_join_code(model):
    """Generate a join_code guaranteed not to collide with an existing row."""
    code = generate_join_code()
    while model.objects.filter(join_code=code).exists():
        code = generate_join_code()
    return code
