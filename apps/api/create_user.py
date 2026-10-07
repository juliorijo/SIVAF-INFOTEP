from __future__ import annotations

import getpass
import re
from uuid import uuid4

from sqlalchemy import select

from apps.api.auth import hash_password
from apps.api.database import SessionLocal, UserORM, init_db


def main() -> None:
    init_db()
    username = input("Nombre de usuario (3-80 caracteres): ").strip().lower()
    if not 3 <= len(username) <= 80 or not re.fullmatch(r"[a-z0-9._-]+", username):
        raise SystemExit("El usuario solo puede contener letras, números, punto, guion y guion bajo.")

    role = input("Rol [admin/analyst] (analyst): ").strip().lower() or "analyst"
    if role not in {"admin", "analyst"}:
        raise SystemExit("Rol no válido. Usa admin o analyst.")

    password = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
    confirmation = getpass.getpass("Confirma la contraseña: ")
    if password != confirmation:
        raise SystemExit("Las contraseñas no coinciden.")

    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    with SessionLocal() as session:
        if session.scalar(select(UserORM.id).where(UserORM.username == username)):
            raise SystemExit("Ese nombre de usuario ya existe.")
        session.add(UserORM(
            id=str(uuid4()),
            username=username,
            password_hash=password_hash,
            role=role,
        ))
        session.commit()

    print(f"Usuario '{username}' creado con rol '{role}'.")


if __name__ == "__main__":
    main()
