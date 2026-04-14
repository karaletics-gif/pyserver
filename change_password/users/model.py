"""
modules/users/model.py – User model.
"""

from database.orm import Model, Field


class User(Model):
    _table = "users"

    name     = Field("TEXT",    nullable=False)
    email    = Field("TEXT",    nullable=False, unique=True, index=True)
    password = Field("TEXT",    nullable=False)
    role     = Field("TEXT",    nullable=False, default="member")   # admin | editor | member
    bio      = Field("TEXT")
    active   = Field("INTEGER", nullable=False, default=1)          # 0 | 1

    def is_admin(self) -> bool:
        return self.role == "admin"

    def deactivate(self) -> None:
        self.active = 0
        self.save()

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
