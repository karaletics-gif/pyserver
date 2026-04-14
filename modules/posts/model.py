"""
modules/posts/model.py – Post model.
"""

from database.orm import Model, Field


class Post(Model):
    _table = "posts"

    title      = Field("TEXT",    nullable=False)
    slug       = Field("TEXT",    nullable=False, unique=True, index=True)
    body       = Field("TEXT",    nullable=False)
    author_id  = Field("INTEGER", nullable=False, index=True)   # FK → users.id
    status     = Field("TEXT",    nullable=False, default="draft")  # draft | published | archived
    views      = Field("INTEGER", nullable=False, default=0)

    def publish(self) -> None:
        self.status = "published"
        self.save()

    def archive(self) -> None:
        self.status = "archived"
        self.save()

    def increment_views(self) -> None:
        Post.objects.filter(id=self.id).update(views=self.views + 1)
        self.views += 1

    def __repr__(self) -> str:
        return f"<Post id={self.id} slug={self.slug!r} status={self.status!r}>"
