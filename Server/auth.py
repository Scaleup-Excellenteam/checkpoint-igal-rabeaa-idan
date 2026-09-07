import hashlib
import secrets
from typing import Tuple
from Server.database import create_user, get_user_hash
from Server.logger import logger


# Number of PBKDF2 iterations for secure hashing
HASH_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    """
    Hashes a plain-text password with a randomly generated cryptographic salt using PBKDF2-HMAC-SHA256.
    Returns format: 'salt$hash'
    """
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        HASH_ITERATIONS
    )
    return f"{salt}${key.hex()}"


def verify_password(plain_password: str, stored_hash: str) -> bool:
    """
    Verifies a plain-text password against a stored 'salt$hash' string.
    Uses constant-time comparison (compare_digest) to prevent timing attacks.
    """
    try:
        salt, expected_key = stored_hash.split("$", 1)
        new_key = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            HASH_ITERATIONS
        ).hex()
        return secrets.compare_digest(new_key, expected_key)
    except (ValueError, AttributeError) as e:
        logger.error(f"Error parsing stored password hash: {e}")
        return False


def register_user(username: str, password: str) -> Tuple[bool, str]:
    """
    Validates input, hashes password, and saves user to relational DB.
    Returns: (success: bool, message: str)
    """
    username = username.strip()
    if not username or len(username) < 3:
        return False, "Username must be at least 3 characters long"

    if not password or len(password) < 4:
        return False, "Password must be at least 4 characters long"

    password_hash = hash_password(password)
    created = create_user(username=username, password_hash=password_hash)

    if not created:
        logger.warning(f"Registration failed: username '{username}' already exists")
        return False, f"Username '{username}' is already taken"

    logger.info(f"User '{username}' registered successfully")
    return True, f"User '{username}' created successfully"


def authenticate_user(username: str, password: str) -> Tuple[bool, str]:
    """
    Validates user credentials against relational DB.
    Returns: (success: bool, message: str)
    """
    username = username.strip()
    stored_hash = get_user_hash(username)

    if not stored_hash or not verify_password(password, stored_hash):
        logger.warning(f"Failed login attempt for username '{username}'")
        return False, "Invalid username or password"

    logger.info(f"User '{username}' logged in successfully")
    return True, f"Welcome back, {username}!"
