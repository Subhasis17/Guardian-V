"""Provision/reset the single operator: python -m app.manage."""
import getpass
import secrets
from app.database import init_db, db
from app.security import password_hash


def main():
    username = input("Operator username: ").strip()
    password = getpass.getpass("Password (12–256 characters): ")
    if not username or len(username) > 100 or not 12 <= len(password) <= 256:
        raise SystemExit("Invalid username or password length.")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match.")
    init_db()
    salt = secrets.token_hex(16)
    with db() as conn:
        conn.execute("INSERT INTO operator VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username, salt=excluded.salt, password_hash=excluded.password_hash", (username, salt, password_hash(password, salt)))
        conn.execute("DELETE FROM auth_sessions")
    print("Operator saved and all sessions revoked.")


if __name__ == "__main__":
    main()
