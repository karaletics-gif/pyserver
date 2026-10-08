"""
modules/users/model.py – User model.
"""

from database.orm import Model, Field


class User(Model):
    _table = "users"

    user_login = Field("TEXT", nullable=False, default="", index=True)
    user_pass = Field("TEXT", nullable=False, default="")
    user_email = Field("TEXT", nullable=False, default="", index=True)
    user_nicename = Field("TEXT", nullable=False, default="")
    user_url = Field("TEXT", nullable=False, default="")
    user_registered = Field("TEXT", nullable=False, default="")
    user_activation_key = Field("TEXT", nullable=False, default="")
    user_status = Field("INTEGER", nullable=False, default=0)
    display_name = Field("TEXT", nullable=False, default="")
    first_name = Field("TEXT", nullable=False, default="")
    last_name = Field("TEXT", nullable=False, default="")
    nickname = Field("TEXT", nullable=False, default="")
    admin_color_scheme = Field("TEXT", nullable=False, default="fresh")
    rich_editing = Field("INTEGER", nullable=False, default=1)
    comment_shortcuts = Field("INTEGER", nullable=False, default=0)
    show_admin_bar_front = Field("INTEGER", nullable=False, default=1)

    name     = Field("TEXT",    nullable=False)
    email    = Field("TEXT",    nullable=False, unique=True, index=True)
    password = Field("TEXT",    nullable=False)
    role     = Field("TEXT",    nullable=False, default="member")   # admin | editor | member
    bio      = Field("TEXT")
    active   = Field("INTEGER", nullable=False, default=1)          # 0 | 1

    def save(self) -> None:
        self.user_login = self.user_login or self.email
        self.user_pass = self.password
        self.user_email = self.email
        self.user_nicename = self.user_nicename or self.name.lower().replace(" ", "-")
        self.display_name = self.display_name or self.name
        self.nickname = self.nickname or self.name
        self.user_registered = self.user_registered or self.created_at
        self.user_status = 0 if self.active else 1
        super().save()

    def is_admin(self) -> bool:
        return self.role == "admin"

    def deactivate(self) -> None:
        self.active = 0
        self.save()

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
