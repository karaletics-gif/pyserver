"""
database/orm.py – a minimal SQLite ORM.

Design
------
  Field          Descriptor that holds column metadata (type, constraints).
  ModelMeta      Metaclass that collects Field declarations into _fields.
  Model          Base class every table inherits from.
  QuerySet       Lazy, chainable query builder returned by Model.objects.
  ConnectionPool Thin wrapper that keeps one sqlite3 connection per DB path.

Usage
-----
    from database.orm import Model, Field, connect

    connect("app.db")          # call once at startup

    class User(Model):
        name  = Field("TEXT", nullable=False)
        email = Field("TEXT", nullable=False, unique=True)
        age   = Field("INTEGER", default=0)

    User.create_table()

    alice = User.objects.create(name="Alice", email="alice@example.com", age=30)
    user  = User.objects.get(id=alice.id)
    users = User.objects.filter(age__gte=18).order_by("name").all()
    User.objects.filter(id=alice.id).update(age=31)
    User.objects.filter(id=alice.id).delete()
"""

from __future__ import annotations

import sqlite3
import re
import threading
from datetime import datetime
from typing import Any, Iterator


# ─────────────────────────────────────────────────────────────────────────────
# Connection pool  (one connection per db path, thread-safe)
# ─────────────────────────────────────────────────────────────────────────────

class _Pool:
    def __init__(self) -> None:
        self._lock  = threading.Lock()
        self._conns: dict[str, Any] = {}
        self._default: str | None = None

    def connect(self, path: str = ":memory:", default: bool = True) -> sqlite3.Connection:
        with self._lock:
            if path not in self._conns:
                conn = sqlite3.connect(path, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                self._conns[path] = conn
            if default or self._default is None:
                self._default = path
            return self._conns[path]

    def connect_mysql(self, config: dict[str, Any], default: bool = True):
        import mysql.connector

        key = "mysql://{}:{}/{}".format(
            config.get("host", "127.0.0.1"), config.get("port", 3306), config["database"]
        )
        with self._lock:
            if key not in self._conns:
                raw = mysql.connector.connect(
                    host=config.get("host", "127.0.0.1"),
                    port=int(config.get("port", 3306)),
                    user=config["user"],
                    password=config["password"],
                    database=config["database"],
                    charset="utf8mb4",
                    autocommit=False,
                )
                self._conns[key] = _MySQLConnection(raw)
            if default or self._default is None:
                self._default = key
            return self._conns[key]

    def get(self, path: str | None = None):
        key = path or self._default
        if key is None or key not in self._conns:
            raise RuntimeError(
                "No database connected. Call connect() before using the ORM."
            )
        return self._conns[key]

    def close(self, path: str | None = None) -> None:
        key = path or self._default
        with self._lock:
            if key and key in self._conns:
                self._conns[key].close()
                del self._conns[key]
                if self._default == key:
                    self._default = next(iter(self._conns), None)


pool = _Pool()


def connect(path: str = ":memory:", default: bool = True):
    """Open (or reuse) a connection to *path*. Call once at app startup."""
    return pool.connect(path, default=default)


def connect_mysql(config: dict[str, Any], default: bool = True):
    """Connect the ORM to a configured MySQL or MariaDB database."""
    return pool.connect_mysql(config, default=default)


def get_connection(path: str | None = None):
    return pool.get(path)


class _MySQLRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class _MySQLCursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self.rowcount = cursor.rowcount
        self.lastrowid = cursor.lastrowid

    def fetchone(self):
        row = self._cursor.fetchone()
        return _MySQLRow(row) if row is not None else None

    def fetchall(self):
        return [_MySQLRow(row) for row in self._cursor.fetchall()]


class _MySQLConnection:
    dialect = "mysql"

    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql: str, params=()):
        from mysql.connector import Error

        sql = re.sub(r'"([A-Za-z_][A-Za-z0-9_]*)"', r'`\1`', sql)
        sql = sql.replace("?", "%s")
        sql = re.sub(r"CREATE INDEX IF NOT EXISTS", "CREATE INDEX", sql, flags=re.I)
        cursor = self._connection.cursor(dictionary=True)
        try:
            cursor.execute(sql, tuple(params))
        except Error as exc:
            cursor.close()
            if exc.errno == 1061 and sql.lstrip().upper().startswith("CREATE INDEX "):
                return _MySQLCursor(_EmptyMySQLCursor())
            raise
        return _MySQLCursor(cursor)

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()


class _EmptyMySQLCursor:
    rowcount = 0
    lastrowid = None

    def close(self):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Field descriptor
# ─────────────────────────────────────────────────────────────────────────────

class Field:
    """
    Declares one column on a Model.

    Parameters
    ----------
    col_type  : SQLite type keyword ("TEXT", "INTEGER", "REAL", "BLOB").
    primary_key : make this the PRIMARY KEY (auto-assigned to 'id' if not set).
    nullable  : allow NULL  (default True).
    unique    : add UNIQUE constraint.
    default   : Python default value (stored as SQL DEFAULT literal).
    index     : create an index for faster lookups.
    """

    # Injected by ModelMeta after class creation
    name: str = ""

    def __init__(
        self,
        col_type: str = "TEXT",
        *,
        primary_key: bool = False,
        nullable:    bool = True,
        unique:      bool = False,
        default:     Any  = None,
        index:       bool = False,
    ) -> None:
        self.col_type    = col_type.upper()
        self.primary_key = primary_key
        self.nullable    = nullable
        self.unique      = unique
        self.default     = default
        self.index       = index

    def sql_definition(self, dialect: str = "sqlite") -> str:
        col_type = self.col_type
        if dialect == "mysql":
            if self.primary_key:
                col_type = "BIGINT"
            elif self.col_type == "TEXT" and (self.unique or self.index):
                col_type = "VARCHAR(191)"
            elif self.col_type == "TEXT":
                col_type = "LONGTEXT"
            elif self.col_type == "INTEGER":
                col_type = "BIGINT"
        quote = "`" if dialect == "mysql" else '"'
        parts = [f"{quote}{self.name}{quote}", col_type]
        if self.primary_key:
            parts.append("PRIMARY KEY" if dialect == "mysql" else "PRIMARY KEY AUTOINCREMENT")
            if dialect == "mysql":
                parts.append("AUTO_INCREMENT")
        if not self.nullable and not self.primary_key:
            parts.append("NOT NULL")
        if self.unique:
            parts.append("UNIQUE")
        if self.default is not None and not (
            dialect == "mysql" and isinstance(self.default, str)
        ):
            parts.append(f"DEFAULT {self._sql_default()}")
        return " ".join(parts)

    def _sql_default(self) -> str:
        d = self.default
        if isinstance(d, str):
            return f"'{d}'"
        if isinstance(d, bool):
            return "1" if d else "0"
        return str(d)

    # Descriptor protocol – only used for type-annotation style access
    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"Field({self.col_type}, name={self.name!r})"


# ─────────────────────────────────────────────────────────────────────────────
# QuerySet  (lazy, chainable)
# ─────────────────────────────────────────────────────────────────────────────

_OPS = {
    "eq":  "=",  "ne": "!=",
    "lt":  "<",  "lte": "<=",
    "gt":  ">",  "gte": ">=",
    "like": "LIKE",
    "in":  "IN",
    "isnull": "IS NULL",
}


class QuerySet:
    """
    Lazy SQL query builder.  Nothing hits the DB until you call
    .all(), .first(), .get(), .count(), .update(), or .delete().

    Filtering
    ---------
    Lookups use Django-style double-underscore suffixes:

        .filter(age__gte=18)         → WHERE age >= 18
        .filter(name__like="%alice%")→ WHERE name LIKE '%alice%'
        .filter(name="Alice")        → WHERE name = 'Alice'  (exact, short-hand)
        .filter(deleted__isnull=True)→ WHERE deleted IS NULL
        .filter(role__in=["a","b"]) → WHERE role IN ('a','b')
    """

    def __init__(self, model: type[Model]) -> None:
        self._model    = model
        self._wheres:  list[tuple[str, list]]  = []  # (sql_fragment, params)
        self._order:   list[str]               = []
        self._limit_:  int | None              = None
        self._offset_: int | None              = None

    # ── Cloning helpers ───────────────────────────────────────────────────────

    def _clone(self) -> QuerySet:
        q = QuerySet(self._model)
        q._wheres  = list(self._wheres)
        q._order   = list(self._order)
        q._limit_  = self._limit_
        q._offset_ = self._offset_
        return q

    # ── Public chainable methods ──────────────────────────────────────────────

    def filter(self, **kwargs) -> QuerySet:
        """Add WHERE clauses. Returns a new QuerySet (immutable chain)."""
        q = self._clone()
        for raw_key, val in kwargs.items():
            if "__" in raw_key:
                col, op_name = raw_key.rsplit("__", 1)
            else:
                col, op_name = raw_key, "eq"

            op = _OPS.get(op_name)
            if op is None:
                raise ValueError(f"Unknown lookup: {op_name!r}. "
                                 f"Valid: {list(_OPS)}")

            if op_name == "isnull":
                clause = f'"{col}" IS {"NULL" if val else "NOT NULL"}'
                q._wheres.append((clause, []))
            elif op_name == "in":
                placeholders = ",".join("?" * len(val))
                q._wheres.append((f'"{col}" IN ({placeholders})', list(val)))
            else:
                q._wheres.append((f'"{col}" {op} ?', [val]))
        return q

    def exclude(self, **kwargs) -> QuerySet:
        """Negate a filter. exclude(active=True) → WHERE NOT active = 1."""
        q = self._clone()
        inner = QuerySet(self._model)
        inner._wheres = []
        sub = inner.filter(**kwargs)
        if sub._wheres:
            frag, params = self._merge_wheres(sub._wheres)
            q._wheres.append((f"NOT ({frag})", params))
        return q

    def order_by(self, *fields: str) -> QuerySet:
        """
        Pass field names; prefix with '-' for DESC.
          .order_by("name")    → ORDER BY name ASC
          .order_by("-created")→ ORDER BY created DESC
        """
        q = self._clone()
        for f in fields:
            if f.startswith("-"):
                q._order.append(f'"{f[1:]}" DESC')
            else:
                q._order.append(f'"{f}" ASC')
        return q

    def limit(self, n: int) -> QuerySet:
        q = self._clone(); q._limit_ = n; return q

    def offset(self, n: int) -> QuerySet:
        q = self._clone(); q._offset_ = n; return q

    # ── Terminal methods (hit the DB) ─────────────────────────────────────────

    def all(self) -> list[Model]:
        """Return all matching rows as Model instances."""
        sql, params = self._select_sql()
        rows = self._execute(sql, params).fetchall()
        return [self._model._from_row(r) for r in rows]

    def first(self) -> Model | None:
        return self.limit(1).all()[0:1] and self.limit(1).all()[0] or None

    def get(self, **kwargs) -> Model:
        """
        Return exactly one row.
        Raises DoesNotExist / MultipleObjectsReturned on mismatches.
        """
        results = self.filter(**kwargs).all()
        if not results:
            raise self._model.DoesNotExist(
                f"{self._model.__name__} matching {kwargs} does not exist."
            )
        if len(results) > 1:
            raise self._model.MultipleObjectsReturned(
                f"get() returned {len(results)} rows for {kwargs}."
            )
        return results[0]

    def count(self) -> int:
        where_sql, params = self._merge_wheres(self._wheres)
        sql = f"SELECT COUNT(*) FROM {self._model._table}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        row = self._execute(sql, params).fetchone()
        return row[0]

    def exists(self) -> bool:
        return self.count() > 0

    def create(self, **kwargs) -> Model:
        """INSERT a new row and return the saved instance."""
        instance = self._model(**kwargs)
        instance.save()
        return instance

    def update(self, **kwargs) -> int:
        """
        UPDATE matching rows.  Returns number of rows affected.
        Does NOT auto-set updated_at – models do that in save().
        """
        if not kwargs:
            return 0
        sets   = ", ".join(f'"{k}" = ?' for k in kwargs)
        params = list(kwargs.values())
        where_sql, where_params = self._merge_wheres(self._wheres)
        sql = f"UPDATE {self._model._table} SET {sets}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        params += where_params
        cur = self._execute(sql, params)
        get_connection().commit()
        return cur.rowcount

    def delete(self) -> int:
        """DELETE matching rows. Returns number of rows deleted."""
        where_sql, params = self._merge_wheres(self._wheres)
        sql = f"DELETE FROM {self._model._table}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        cur = self._execute(sql, params)
        get_connection().commit()
        return cur.rowcount

    def values(self, *fields: str) -> list[dict]:
        """Return list of dicts with only the requested fields."""
        cols = ", ".join(fields) if fields else "*"
        where_sql, params = self._merge_wheres(self._wheres)
        sql = f"SELECT {cols} FROM {self._model._table}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        if self._order:
            sql += f" ORDER BY {', '.join(self._order)}"
        if self._limit_ is not None:
            sql += f" LIMIT {self._limit_}"
        rows = self._execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ── Iteration shortcut ────────────────────────────────────────────────────

    def __iter__(self) -> Iterator[Model]:
        return iter(self.all())

    def __len__(self) -> int:
        return self.count()

    def __repr__(self) -> str:
        return f"<QuerySet [{self._model.__name__}] wheres={self._wheres}>"

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _select_sql(self) -> tuple[str, list]:
        where_sql, params = self._merge_wheres(self._wheres)
        sql = f"SELECT * FROM {self._model._table}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        if self._order:
            sql += f" ORDER BY {', '.join(self._order)}"
        if self._limit_ is not None:
            sql += f" LIMIT {self._limit_}"
        if self._offset_ is not None:
            sql += f" OFFSET {self._offset_}"
        return sql, params

    @staticmethod
    def _merge_wheres(wheres: list[tuple[str, list]]) -> tuple[str, list]:
        if not wheres:
            return "", []
        frags  = [w[0] for w in wheres]
        params = [p for w in wheres for p in w[1]]
        return " AND ".join(frags), params

    def _execute(self, sql: str, params: list) -> sqlite3.Cursor:
        return get_connection().execute(sql, params)


# ─────────────────────────────────────────────────────────────────────────────
# ModelMeta  (metaclass)
# ─────────────────────────────────────────────────────────────────────────────

class ModelMeta(type):
    def __new__(mcs, name: str, bases: tuple, namespace: dict) -> type:
        fields: dict[str, Field] = {}

        # Inherit fields from parent models
        for base in bases:
            if hasattr(base, "_fields"):
                fields.update(base._fields)

        # Collect Field instances declared on this class
        for attr, val in list(namespace.items()):
            if isinstance(val, Field):
                val.name = attr
                fields[attr] = val

        namespace["_fields"] = fields

        # Derive table name from class name (snake_case plural)
        if "_table" not in namespace:
            table = _to_snake(name) + "s"
            namespace["_table"] = table

        cls = super().__new__(mcs, name, bases, namespace)

        # Attach a per-class QuerySet manager
        cls.objects = QuerySet(cls)

        return cls


def _to_snake(name: str) -> str:
    """UserProfile → user_profiles"""
    import re
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# ─────────────────────────────────────────────────────────────────────────────
# Base Model
# ─────────────────────────────────────────────────────────────────────────────

class Model(metaclass=ModelMeta):
    """
    Base class for all ORM models.

    Subclass and declare Field() attributes:

        class Article(Model):
            title = Field("TEXT", nullable=False)
            body  = Field("TEXT")

    Then call Article.create_table() once.
    """

    # Every model gets id, created_at, updated_at automatically
    id         = Field("INTEGER", primary_key=True)
    created_at = Field("TEXT", nullable=False, default="CURRENT_TIMESTAMP")
    updated_at = Field("TEXT", nullable=False, default="CURRENT_TIMESTAMP")

    # ── Metaclass-injected ──────────────────────────────────────────────
    _fields: dict[str, Field]
    _table:  str
    objects: QuerySet

    # ── Exceptions ──────────────────────────────────────────────────────
    class DoesNotExist(Exception): pass
    class MultipleObjectsReturned(Exception): pass

    def __init__(self, **kwargs) -> None:
        # Set defaults from Field declarations
        for name, field in self._fields.items():
            value = kwargs.get(name, field.default)
            # Don't store SQL-function defaults (like CURRENT_TIMESTAMP) as Python
            if isinstance(value, str) and value == "CURRENT_TIMESTAMP":
                value = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
            object.__setattr__(self, name, value)
        # Allow arbitrary extra kwargs (e.g. loaded from DB row)
        for k, v in kwargs.items():
            if k not in self._fields:
                object.__setattr__(self, k, v)

    # ── DDL ──────────────────────────────────────────────────────────────

    @classmethod
    def create_table(cls, if_not_exists: bool = True) -> None:
        """CREATE TABLE for this model."""
        guard = "IF NOT EXISTS " if if_not_exists else ""
        col_defs = []
        indices  = []
        conn = get_connection()
        dialect = getattr(conn, "dialect", "sqlite")
        for name, field in cls._fields.items():
            col_defs.append(f"    {field.sql_definition(dialect)}")
            if field.index and not field.primary_key:
                idx_name = f"idx_{cls._table}_{name}"
                guard_index = "" if dialect == "mysql" else "IF NOT EXISTS "
                indices.append(
                    f"CREATE INDEX {guard_index}{idx_name} "
                    f"ON `{cls._table}` (`{name}`);"
                )
        sql = (
            f"CREATE TABLE {guard}{cls._table} (\n"
            + ",\n".join(col_defs)
            + "\n);"
        )
        conn.execute(sql)
        for idx_sql in indices:
            conn.execute(idx_sql)
        conn.commit()

    @classmethod
    def drop_table(cls, if_exists: bool = True) -> None:
        guard = "IF EXISTS " if if_exists else ""
        conn  = get_connection()
        conn.execute(f"DROP TABLE {guard}{cls._table};")
        conn.commit()

    # ── CRUD ──────────────────────────────────────────────────────────────

    def save(self) -> None:
        """INSERT or UPDATE (upsert by id)."""
        now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
        self.updated_at = now

        conn = get_connection()
        # Collect columns that have a value (skip id on INSERT, include on UPDATE)
        data = {
            name: getattr(self, name, None)
            for name in self._fields
            if name != "id" or getattr(self, "id", None) is not None
        }

        if getattr(self, "id", None) is None:
            # INSERT
            self.created_at = now
            data["created_at"] = now
            cols   = ", ".join(f'"{k}"' for k in data.keys())
            placeholders = ", ".join("?" * len(data))
            sql = f"INSERT INTO {self._table} ({cols}) VALUES ({placeholders})"
            cur = conn.execute(sql, list(data.values()))
            self.id = cur.lastrowid
        else:
            # UPDATE
            sets   = ", ".join(f'"{k}" = ?' for k in data if k != "id")
            params = [v for k, v in data.items() if k != "id"]
            params.append(self.id)
            sql = f"UPDATE {self._table} SET {sets} WHERE id = ?"
            conn.execute(sql, params)

        conn.commit()

    def delete(self) -> None:
        """DELETE this instance from the database."""
        if self.id is None:
            raise ValueError("Cannot delete an unsaved instance.")
        get_connection().execute(
            f"DELETE FROM {self._table} WHERE id = ?", [self.id]
        )
        get_connection().commit()
        self.id = None

    def refresh(self) -> None:
        """Reload this instance's data from the database."""
        fresh = self.__class__.objects.get(id=self.id)
        for name in self._fields:
            object.__setattr__(self, name, getattr(fresh, name))

    # ── Internals ─────────────────────────────────────────────────────────

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> Model:
        return cls(**dict(row))

    def to_dict(self) -> dict:
        return {name: getattr(self, name, None) for name in self._fields}

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{self.__class__.__name__} id={pk}>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return self.id is not None and self.id == other.id
