from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email"),
        CheckConstraint(
            "email = lower(btrim(email)) AND email <> '' AND position('@' in email) > 1",
            name="email_normalized",
        ),
        CheckConstraint("role IN ('USER', 'OPERATOR', 'ADMIN', 'SYSTEM')", name="role_values"),
    )

    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), server_default="USER")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def permissions(self) -> set[str]:
        # Defined permissions per role
        role_permissions = {
            "USER": {"read:incidents", "create:incidents", "read:routes"},
            "OPERATOR": {
                "read:incidents",
                "create:incidents",
                "update:incidents",
                "delete:incidents",
                "read:routes",
            },
            "ADMIN": {
                "read:incidents",
                "create:incidents",
                "update:incidents",
                "delete:incidents",
                "read:routes",
                "manage:users",
                "manage:system",
            },
            "SYSTEM": {"*"},
        }
        return role_permissions.get(self.role, set())

    def has_permission(self, permission: str) -> bool:
        if self.role == "SYSTEM":
            return True
        if "*" in self.permissions:
            return True
        return permission in self.permissions
