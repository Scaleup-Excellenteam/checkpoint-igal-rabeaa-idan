import hashlib
import secrets
from typing import Tuple
from Server.database import db_insert_user, get_user_hash
from Server.logger import logger

# PBKDF2 iterations for cryptographic hashing
HASH_ITERATIONS = 100_000


# ==========================================
# AUTHENTICATION INTERFACE (TEAMMATE 1 CONTRACT)
# ==========================================

def hash_password(plaintext: str) -> str:
    """
    Hashes a plaintext password with a cryptographically secure random salt using PBKDF2-HMAC-SHA256.
    Returns string in the format: 'salt$hash'
    """
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        plaintext.encode("utf-8"),
        salt.encode("utf-8"),
        HASH_ITERATIONS
    )
    return f"{salt}${key.hex()}"


def verify_password(plaintext: str, stored_hash: str) -> bool:
    """
    Verifies a plaintext password against a stored 'salt$hash' string.
    Uses constant-time comparison to prevent timing attacks.
    """
    try:
        salt, expected_key = stored_hash.split("$", 1)
        new_key = hashlib.pbkdf2_hmac(
            "sha256",
            plaintext.encode("utf-8"),
            salt.encode("utf-8"),
            HASH_ITERATIONS
        ).hex()
        return secrets.compare_digest(new_key, expected_key)
    except (ValueError, AttributeError) as e:
        logger.error(f"Error parsing stored password hash: {e}")
        return False


def verify_credentials(username: str, plaintext: str) -> bool:
    """
    Check DB for matching username and valid salted hash.
    Returns True if valid, False otherwise.
    """
    username = username.strip()
    stored_hash = get_user_hash(username)

    if not stored_hash:
        logger.warning(f"Login failed: user '{username}' not found")
        return False

    is_valid = verify_password(plaintext, stored_hash)
    if not is_valid:
        logger.warning(f"Login failed: invalid password for user '{username}'")
        return False

    logger.info(f"User '{username}' credentials verified successfully")
    return True


def create_user(username: str, plaintext: str) -> bool:
    """
    Reject duplicate usernames, store salted hash.
    Returns True if user was created, False if username exists or input is invalid.
    """
    username = username.strip()
    if not username or len(username) < 3:
        logger.warning("User creation failed: username must be at least 3 characters")
        return False

    if not plaintext or len(plaintext) < 4:
        logger.warning("User creation failed: password must be at least 4 characters")
        return False

    hashed = hash_password(plaintext)
    created = db_insert_user(username=username, password_hash=hashed)

    if not created:
        logger.warning(f"User creation failed: username '{username}' already exists")
        return False

    logger.info(f"User '{username}' created successfully")
    return True
