"""WordPress-shaped metadata, taxonomy, comment, and link tables."""

from database.orm import Field, Model


class _WordPressModel(Model):
    _wp_id_field = ""

    def save(self) -> None:
        super().save()
        if self._wp_id_field and getattr(self, self._wp_id_field) != self.id:
            setattr(self, self._wp_id_field, self.id)
            super().save()


class UserMeta(_WordPressModel):
    _table = "usermeta"
    _wp_id_field = "umeta_id"
    umeta_id = Field("INTEGER", nullable=False, default=0, index=True)
    user_id = Field("INTEGER", nullable=False, index=True)
    meta_key = Field("TEXT")
    meta_value = Field("TEXT")


class PostMeta(_WordPressModel):
    _table = "postmeta"
    _wp_id_field = "meta_id"
    meta_id = Field("INTEGER", nullable=False, default=0, index=True)
    post_id = Field("INTEGER", nullable=False, index=True)
    meta_key = Field("TEXT", index=True)
    meta_value = Field("TEXT")


class Term(_WordPressModel):
    _table = "terms"
    _wp_id_field = "term_id"
    term_id = Field("INTEGER", nullable=False, default=0, index=True)
    name = Field("TEXT", nullable=False)
    slug = Field("TEXT", nullable=False, index=True)
    term_group = Field("INTEGER", nullable=False, default=0)


class TermTaxonomy(_WordPressModel):
    _table = "term_taxonomy"
    _wp_id_field = "term_taxonomy_id"
    term_taxonomy_id = Field("INTEGER", nullable=False, default=0, index=True)
    term_id = Field("INTEGER", nullable=False, index=True)
    taxonomy = Field("TEXT", nullable=False, index=True)
    description = Field("TEXT")
    parent = Field("INTEGER", nullable=False, default=0)
    count = Field("INTEGER", nullable=False, default=0)


class TermRelationship(_WordPressModel):
    _table = "term_relationships"
    object_id = Field("INTEGER", nullable=False, index=True)
    term_taxonomy_id = Field("INTEGER", nullable=False, index=True)
    term_order = Field("INTEGER", nullable=False, default=0)


class Comment(_WordPressModel):
    _table = "comments"
    _wp_id_field = "comment_id"
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


class CommentMeta(_WordPressModel):
    _table = "commentmeta"
    _wp_id_field = "meta_id"
    meta_id = Field("INTEGER", nullable=False, default=0, index=True)
    comment_id = Field("INTEGER", nullable=False, index=True)
    meta_key = Field("TEXT", index=True)
    meta_value = Field("TEXT")


class Link(_WordPressModel):
    _table = "links"
    _wp_id_field = "link_id"
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


class TermMeta(_WordPressModel):
    _table = "termmeta"
    _wp_id_field = "meta_id"
    meta_id = Field("INTEGER", nullable=False, default=0, index=True)
    term_id = Field("INTEGER", nullable=False, index=True)
    meta_key = Field("TEXT", index=True)
    meta_value = Field("TEXT")


class WordPressSchema:
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
            else:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
                ).fetchone()
                if exists is None:
                    continue
                columns = {row["name"].lower() for row in conn.execute(f'PRAGMA table_info("{table}")')}

            alias = getattr(model, "_wp_id_field", "")
            if "id" not in columns:
                if mysql and not alias:
                    definition = "BIGINT NOT NULL AUTO_INCREMENT UNIQUE"
                else:
                    definition = "BIGINT NULL" if mysql else "INTEGER"
                conn.execute(f'ALTER TABLE `{table}` ADD COLUMN `id` {definition}')
                if not mysql:
                    conn.execute(f'UPDATE `{table}` SET `id` = rowid WHERE `id` IS NULL')
            if "created_at" not in columns:
                conn.execute(f'ALTER TABLE `{table}` ADD COLUMN `created_at` VARCHAR(32) NULL' if mysql
                             else f'ALTER TABLE `{table}` ADD COLUMN `created_at` TEXT')
            if "updated_at" not in columns:
                conn.execute(f'ALTER TABLE `{table}` ADD COLUMN `updated_at` VARCHAR(32) NULL' if mysql
                             else f'ALTER TABLE `{table}` ADD COLUMN `updated_at` TEXT')
            if alias and alias.lower() in columns:
                conn.execute(f'UPDATE `{table}` SET `id` = `{alias}` WHERE `{alias}` IS NOT NULL')
        conn.commit()
