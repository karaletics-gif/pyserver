"""
modules/settings/model.py – Setting model (key-value store).
"""

from database.orm import Model, Field


class Setting(Model):
    _table = "settings"

    key        = Field("TEXT",    nullable=False, unique=True, index=True)
    value      = Field("TEXT")
    value_type = Field("TEXT",    nullable=False, default="string")  # string | int | bool | json
    group      = Field("TEXT",    nullable=False, default="general")
    label      = Field("TEXT")

    # ── Typed getters ──────────────────────────────────────────────────

    def as_int(self) -> int:
        return int(self.value or 0)

    def as_bool(self) -> bool:
        return str(self.value).lower() in ("1", "true", "yes")

    def as_json(self):
        import json
        return json.loads(self.value or "null")

    # ── Class-level helpers ────────────────────────────────────────────

    @classmethod
    def get_value(cls, key: str, default=None):
        """Shorthand: Setting.get_value('site_name', 'My Site')"""
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_value(cls, key: str, value, group: str = "general") -> "Setting":
        """Upsert by key."""
        try:
            setting = cls.objects.get(key=key)
            setting.value = str(value)
            setting.save()
        except cls.DoesNotExist:
            setting = cls.objects.create(key=key, value=str(value), group=group)
        return setting

    def __repr__(self) -> str:
        return f"<Setting {self.key!r}={self.value!r}>"
