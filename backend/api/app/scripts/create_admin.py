from getpass import getpass

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User


def main() -> None:
    print("Create EnterpriseOS administrator")

    username = input("Login: ").strip().lower()
    display_name = input("Display name: ").strip()

    if not username:
        raise SystemExit("Login cannot be empty")

    if not display_name:
        display_name = username

    password = getpass("Password: ")
    password_confirmation = getpass("Confirm password: ")

    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters")

    if password != password_confirmation:
        raise SystemExit("Passwords do not match")

    with SessionLocal() as db:
        existing_user = db.scalar(
            select(User).where(User.username == username)
        )

        if existing_user is not None:
            raise SystemExit(f"User '{username}' already exists")

        user = User(
            username=username,
            display_name=display_name,
            hashed_password=hash_password(password),
            is_active=True,
            is_admin=True,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        print(
            f"Administrator created: "
            f"id={user.id}, login={user.username}"
        )


if __name__ == "__main__":
    main()
