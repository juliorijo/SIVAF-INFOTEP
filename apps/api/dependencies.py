"""
Dependencias compartidas para FastAPI (autenticación, autorización, etc.)
"""

import hashlib
import time
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from apps.api.database import SessionLocal, UserORM, UserSessionORM
from packages.domain.permissions_enums import RoleType

AUTH_COOKIE_NAME = "sivaf_session"


def get_db():
    """Obtener sesión de BD."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request) -> UserORM:
    """Obtener usuario actual de la sesión (via cookies)."""
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with SessionLocal() as session:
        auth_session = session.get(UserSessionORM, token_hash)
        if auth_session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
        if auth_session.expires_at <= time.time():
            session.delete(auth_session)
            session.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")

        user = session.get(UserORM, auth_session.user_id)
        if user is None or not user.is_active:
            session.delete(auth_session)
            session.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
        return user


def require_admin(current_user: UserORM = Depends(get_current_user)) -> UserORM:
    """Verificar que el usuario sea administrador."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return current_user

