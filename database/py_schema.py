"""PyServer-prefixed metadata, taxonomy, comment, and link tables."""

from database.orm import Field, Model


class _PyModel(Model):
    _native_id_field = ""

    def save(self) -> None:
        super().save()
        if self._native_id_field and getattr(self, self._native_id_field) != self.id:
            setattr(self, self._native_id_field, self.id)
            super().save()


class UserMeta(_PyModel):
    _table = "usermeta"
    _native_id_field = "umeta_id"
    umeta_id = Field("INTEGER", nullable=False, default=0, index=True)
    user_id = Field("INTEGER", nullable=False, index=True)
    meta_key = Field("TEXT")
    meta_value = Field("TEXT")


class PostMeta(_PyModel):
    _table = "postmeta"
    _native_id_field = "meta_id"
    meta_id = Field("INTEGER", nullable=False, default=0, index=True)
    post_id = Field("INTEGER", nullable=False, index=True)
    meta_key = Field("TEXT", index=True)
    meta_value = Field("TEXT")


class Term(_PyModel):
    _table = "terms"
    _native_id_field = "term_id"
    term_id = Field("INTEGER", nullable=False, default=0, index=True)
    name = Field("TEXT", nullable=False)
    slug = Field("TEXT", nullable=False, index=True)
    term_group = Field("INTEGER", nullable=False, default=0)


class TermTaxonomy(_PyModel):
    _table = "term_taxonomy"
    _native_id_field = "term_taxonomy_id"
    term_taxonomy_id = Field("INTEGER", nullable=False, default=0, index=True)
    term_id = Field("INTEGER", nullable=False, index=True)
    taxonomy = Field("TEXT", nullable=False, index=True)
    description = Field("TEXT")
    parent = Field("INTEGER", nullable=False, default=0)
    count = Field("INTEGER", nullable=False, default=0)


class TermRelationship(_PyModel):
    _table = "term_relationships"
    object_id = Field("INTEGER", nullable=False, index=True)
    term_taxonomy_id = Field("INTEGER", nullable=False, index=True)
    term_order = Field("INTEGER", nullable=False, default=0)


class Comment(_PyModel):
    _table = "comments"
    _native_id_field = "comment_id"
    comment_id = Field("INTEGER", nullable=False, default=0, index=True)
    comment_post_id = Field("INTEGER", nullable=False, index=True)
    comment_author = Field("TEXT", nullable=False)
    comment_author_email = Field("TEXT", nullable=False, default="")
    comment_author_url = Field("TEXT", nullable=False, default="")
    comment_author_ip = Field("TEXT", nullable=False, default="")
    comment_date = Field("TEXT", nullable=False)
    comment_date_gmt = Field("TEXT", nullable=False)
    comment_content = Field("TEXT", nullable=False)
    comment_karma = Field("INTEGER", nullable=False, default=0)
    comment_approved = Field("TEXT", nullable=False, default="1")
    comment_agent = Field("TEXT", nullable=False, default="")
    comment_type = Field("TEXT", nullable=False, default="")
    comment_parent = Field("INTEGER", nullable=False, default=0)
    user_id = Field("INTEGER", nullable=False, default=0, index=True)


class CommentMeta(_PyModel):
    _table = "commentmeta"
    _native_id_field = "meta_id"
    meta_id = Field("INTEGER", nullable=False, default=0, index=True)
    comment_id = Field("INTEGER", nullable=False, index=True)
    meta_key = Field("TEXT", index=True)
    meta_value = Field("TEXT")


class Link(_PyModel):
    _table = "links"
    _native_id_field = "link_id"
    link_id = Field("INTEGER", nullable=False, default=0, index=True)
    link_url = Field("TEXT", nullable=False)
    link_name = Field("TEXT", nullable=False)
    link_image = Field("TEXT", nullable=False, default="")
    link_target = Field("TEXT", nullable=False, default="")
    link_description = Field("TEXT", nullable=False, default="")
    link_visible = Field("TEXT", nullable=False, default="Y")
    link_owner = Field("INTEGER", nullable=False, default=1)
    link_rating = Field("INTEGER", nullable=False, default=0)
    link_updated = Field("TEXT")
    link_rel = Field("TEXT", nullable=False, default="")
    link_notes = Field("TEXT", nullable=False, default="")
    link_rss = Field("TEXT", nullable=False, default="")


class TermMeta(_PyModel):
    _table = "termmeta"
    _native_id_field = "meta_id"
    meta_id = Field("INTEGER", nullable=False, default=0, index=True)
    term_id = Field("INTEGER", nullable=False, index=True)
    meta_key = Field("TEXT", index=True)
    meta_value = Field("TEXT")


class PySchema:
    TABLES = (
        UserMeta, PostMeta, Term, TermTaxonomy, TermRelationship,
        Comment, CommentMeta, Link, TermMeta,
    )

    @classmethod
    def create_tables(cls) -> None:
        for model in cls.TABLES:
            model.create_table()

    @classmethod
    def migrate_existing_tables(cls) -> None:
        from database.orm import get_connection

        conn = get_connection()
        mysql = getattr(conn, "dialect", "sqlite") == "mysql"
        for model in cls.TABLES:
            table = model._table
            if mysql:
                rows = conn.execute(
                    "SELECT COLUMN_NAME FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() AND table_name = ?", (table,)
                ).fetchall()
                columns = {row["column_name"].lower() for row in rows}
                if not columns:
                    continue
            else:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
                ).fetchone()
                if exists is None:
                    continue
                columns = {row["name"].lower() for row in conn.execute(f'PRAGMA table_info("{table}")')}

            native_id = getattr(model, "_native_id_field", "")
            if "id" not in columns:
                definition = "BIGINT NOT NULL AUTO_INCREMENT UNIQUE" if mysql and not native_id else (
                    "BIGINT NULL" if mysql else "INTEGER"
                )
                conn.execute(f'ALTER TABLE `{table}` ADD COLUMN `id` {definition}')
                if not mysql:
                    conn.execute(f'UPDATE `{table}` SET `id` = rowid WHERE `id` IS NULL')
            if "created_at" not in columns:
                conn.execute(f'ALTER TABLE `{table}` ADD COLUMN `created_at` VARCHAR(32) NULL' if mysql
                             else f'ALTER TABLE `{table}` ADD COLUMN `created_at` TEXT')
            if "updated_at" not in columns:
                conn.execute(f'ALTER TABLE `{table}` ADD COLUMN `updated_at` VARCHAR(32) NULL' if mysql
                             else f'ALTER TABLE `{table}` ADD COLUMN `updated_at` TEXT')
            if native_id and native_id.lower() in columns:
                conn.execute(f'UPDATE `{table}` SET `id` = `{native_id}` WHERE `{native_id}` IS NOT NULL')
        conn.commit()