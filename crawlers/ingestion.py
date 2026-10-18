"""Shared ingestion contracts, safe updates and durable crawl work."""

from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import uuid
import threading
import time

from bs4 import BeautifulSoup


class FetchList(list):
    def __init__(self, items=(), *, complete=False, error=None, cursor=None):
        super().__init__(items)
        self.complete = complete
        self.error = error
        self.cursor = cursor


def now():
    return datetime.now().isoformat()


def time_text(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        return datetime.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError):
        return str(value or "")


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def public_record(record):
    return {key: value for key, value in record.items() if not key.startswith("_")}


def is_login_page(html, url=""):
    if "/accounts/login" in str(url):
        return True
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.select_one(".song_title, .user_head"):
        return False
    # Logged-in pages contain an account-settings email field as well.
    return bool(soup.select_one("#J_signin")) or any(
        node.get_text(" ", strip=True).lower() == "sign in"
        for node in soup.select(".g_title")
    )


def limit_session(session, rpm=15):
    """Throttle all actual requests, including supplementary HTML and talks."""
    if hasattr(session, "_malody_limiter"):
        return session
    lock = threading.Lock()
    state = {"next": 0.0, "rpm": max(1, min(float(rpm), 30))}
    original = session.request

    def request(*args, **kwargs):
        with lock:
            delay = max(0, state["next"] - time.monotonic())
            state["next"] = max(time.monotonic(), state["next"]) + 60 / state["rpm"]
        if delay:
            time.sleep(delay)
        return original(*args, **kwargs)

    session.request = request
    session._malody_limiter = state
    return session


@contextmanager
def atomic(conn):
    nested = conn.in_transaction
    savepoint = "ingest_" + uuid.uuid4().hex
    conn.execute("SAVEPOINT " + savepoint if nested else "BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        if nested:
            conn.execute("ROLLBACK TO " + savepoint)
            conn.execute("RELEASE " + savepoint)
        else:
            conn.rollback()
        raise
    else:
        if nested:
            conn.execute("RELEASE " + savepoint)
        else:
            conn.commit()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_progress(path):
    """Never interpret damaged progress as an empty/new crawl."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Progress must be an object")
        for key in ("current_cid", "current_sid"):
            if key in value and (not isinstance(value[key], int) or value[key] < 1):
                raise ValueError(f"Invalid {key}")
        return value
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        raise ValueError(
            f"Progress is unreadable; restore a verified backup: {path}"
        ) from exc


def ensure_schema(conn):
    # executescript commits implicitly, so use individual statements here.
    for statement in (
        """CREATE TABLE IF NOT EXISTS crawl_observations (
            entity TEXT, object_id TEXT, section TEXT, source TEXT,
            observed_at TEXT, source_time TEXT, complete INTEGER, detail TEXT,
            PRIMARY KEY(entity,object_id,section))""",
        """CREATE TABLE IF NOT EXISTS crawl_changes (
            change_id INTEGER PRIMARY KEY,entity TEXT,object_id TEXT,
            observed_at TEXT,source TEXT,before_json TEXT,after_json TEXT)""",
        """CREATE TABLE IF NOT EXISTS crawl_tasks (
            scope TEXT,kind TEXT,object_id TEXT,state TEXT NOT NULL DEFAULT 'pending',
            payload TEXT,attempts INTEGER NOT NULL DEFAULT 0,next_attempt TEXT,
            lease_until TEXT,last_error TEXT,updated_at TEXT,
            PRIMARY KEY(scope,kind,object_id))""",
        "CREATE INDEX IF NOT EXISTS idx_crawl_tasks_ready ON crawl_tasks(scope,state,next_attempt)",
    ):
        conn.execute(statement)
    additions = {
        "charts": {
            "checksum": "TEXT",
            "tags_json": "TEXT",
            "not_recommend_count": "INTEGER",
        },
        "songs": {"title_org": "TEXT", "artist_org": "TEXT"},
        "player_rankings": {"source": "TEXT"},
        "chart_comments": {
            "is_not_recommend": "INTEGER NOT NULL DEFAULT 0",
            "is_current": "INTEGER NOT NULL DEFAULT 1",
            "seen_generation": "TEXT",
        },
        "player_titles": {"first_observed_at": "TEXT"},
        "player_achievements": {"first_observed_at": "TEXT"},
    }
    for table, columns in additions.items():
        existing = {row[1] for row in conn.execute("PRAGMA table_info(" + table + ")")}
        if existing:
            for column, declaration in columns.items():
                if column not in existing:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"
                    )


def row_dict(cursor, row):
    return (
        dict(zip((item[0] for item in cursor.description), row))
        if row is not None
        else None
    )


def merge_record(old, incoming, allowed):
    old = old or {}
    present = incoming.get("_present")
    merged = (
        dict(old) if old else {field: None for field in allowed if field in incoming}
    )
    for field in allowed:
        if field not in incoming:
            continue
        value = incoming[field]
        if present is not None:
            if field not in present:
                continue
        elif value is None or value == "":
            continue
        merged[field] = value
    return merged


def save_record(conn, table, key, value, incoming, allowed, *, metadata_fields=()):
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # Legacy DATE columns contain sentinel text such as "Never". Read values
    # without SQLite's eager date converter so the next valid observation can repair them.
    selection = ",".join(
        (
            f"CAST({row[1]} AS TEXT) AS {row[1]}"
            if row[2].upper() in ("DATE", "TIMESTAMP", "DATETIME")
            else row[1]
        )
        for row in info
    )
    cursor = conn.execute(f"SELECT {selection} FROM {table} WHERE {key}=?", (value,))
    old = row_dict(cursor, cursor.fetchone())
    merged = merge_record(old, incoming, allowed)
    source_time = incoming.get("_source_time")
    metadata_prior = conn.execute(
        "SELECT source FROM crawl_observations WHERE entity=? AND object_id=? AND section='metadata'",
        (table, str(value)),
    ).fetchone()
    downgrade = (
        metadata_prior
        and metadata_prior[0] == "newapi"
        and incoming.get("_source") == "page_chart"
    )
    stale_metadata = (
        old
        and source_time
        and old.get("last_updated")
        and time_text(source_time) < time_text(old["last_updated"])
    )
    if stale_metadata or downgrade:
        for field in metadata_fields:
            if field in (old or {}) and old[field] is not None:
                merged[field] = old[field]
    merged[key] = value
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    stamp = time_text(incoming.get("_observed_at") or now())
    prior = conn.execute(
        "SELECT observed_at FROM crawl_observations WHERE entity=? AND object_id=? AND section='record'",
        (table, str(value)),
    ).fetchone()
    if prior and stamp < time_text(prior[0]):
        return old, False
    before = {
        k: v
        for k, v in (old or {}).items()
        if k not in ("crawl_time", "data_hash", "last_crawled")
    }
    after = {
        k: v
        for k, v in merged.items()
        if k in columns and k not in ("crawl_time", "data_hash", "last_crawled")
    }
    for record in (before, after):
        for field in record:
            if record[field] is not None and (
                field.endswith("_date") or field in ("last_updated", "deleted_at")
            ):
                record[field] = time_text(record[field])
    changed = json_text(before) != json_text(after)
    if changed:
        conn.execute(
            "INSERT INTO crawl_changes(entity,object_id,observed_at,source,before_json,after_json) VALUES(?,?,?,?,?,?)",
            (
                table,
                str(value),
                stamp,
                incoming.get("_source", "unknown"),
                json_text(before),
                json_text(after),
            ),
        )
    fields = [field for field in merged if field in columns]
    values = [merged[field] for field in fields]
    updates = ",".join(f"{field}=excluded.{field}" for field in fields if field != key)
    conn.execute(
        f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) "
        f"ON CONFLICT({key}) DO UPDATE SET {updates}",
        values,
    )
    observe(
        conn,
        table,
        value,
        "record",
        incoming.get("_source", "unknown"),
        bool(incoming.get("_complete", False)),
        source_time=source_time,
        observed_at=stamp,
        detail={
            "present": sorted(
                field
                for field in (
                    incoming.keys()
                    if incoming.get("_present") is None
                    else incoming["_present"]
                )
                if field in columns
            ),
            "field_sources": incoming.get("_field_sources", {}),
        },
    )
    if metadata_fields and not stale_metadata and not downgrade:
        observe(
            conn,
            table,
            value,
            "metadata",
            incoming.get("_source", "unknown"),
            bool(incoming.get("_complete", False)),
            source_time=source_time,
            observed_at=stamp,
        )
    return merged, changed


def observe(
    conn,
    entity,
    object_id,
    section,
    source,
    complete,
    *,
    source_time=None,
    observed_at=None,
    detail=None,
):
    conn.execute(
        """INSERT INTO crawl_observations
        (entity,object_id,section,source,observed_at,source_time,complete,detail)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(entity,object_id,section) DO UPDATE SET
        source=excluded.source,observed_at=excluded.observed_at,source_time=excluded.source_time,
        complete=excluded.complete,detail=excluded.detail
        WHERE excluded.observed_at >= crawl_observations.observed_at""",
        (
            entity,
            str(object_id),
            section,
            source,
            time_text(observed_at or now()),
            time_text(source_time) if source_time is not None else None,
            int(complete),
            json_text(detail),
        ),
    )


class TaskStore:
    """Durable tasks; scopes separate refresh generations and filter settings."""

    def __init__(self, conn, scope):
        self.conn, self.scope = conn, scope
        self.leases = {}
        with atomic(conn):
            ensure_schema(conn)

    def add(self, kind, object_id, payload=None):
        self.conn.execute(
            """INSERT INTO crawl_tasks(scope,kind,object_id,payload,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(scope,kind,object_id) DO NOTHING""",
            (self.scope, kind, str(object_id), json_text(payload or {}), now()),
        )

    def claim(self, limit=1, lease_seconds=900, *, kind=None, object_ids=None):
        stamp = now()
        filters, args = "", [self.scope, stamp, stamp]
        if kind is not None:
            filters += " AND kind=?"
            args.append(kind)
        if object_ids is not None:
            if not object_ids:
                return []
            filters += " AND object_id IN (" + ",".join("?" for _ in object_ids) + ")"
            args.extend(str(value) for value in object_ids)
        args.append(limit)
        with atomic(self.conn):
            cursor = self.conn.execute(
                """SELECT kind,object_id,payload FROM crawl_tasks
                WHERE scope=? AND ((state IN ('pending','retry') AND (next_attempt IS NULL OR next_attempt<=?))
                    OR (state='running' AND lease_until<=?))"""
                + filters
                + " ORDER BY updated_at,kind,object_id LIMIT ?",
                args,
            )
            rows = cursor.fetchall()
            for kind, object_id, _ in rows:
                lease_until = (
                    datetime.now() + timedelta(seconds=lease_seconds)
                ).isoformat()
                self.conn.execute(
                    """UPDATE crawl_tasks SET state='running',attempts=attempts+1,
                    lease_until=?,updated_at=? WHERE scope=? AND kind=? AND object_id=?""",
                    (
                        lease_until,
                        stamp,
                        self.scope,
                        kind,
                        object_id,
                    ),
                )
                self.leases[(kind, str(object_id))] = lease_until
        return [
            (kind, object_id, json.loads(payload or "{}"))
            for kind, object_id, payload in rows
        ]

    def finish(
        self,
        kind,
        object_id,
        *,
        state="done",
        error=None,
        payload=None,
        retry_seconds=60,
    ):
        if state not in ("done", "not_found", "retry", "pending"):
            raise ValueError("Invalid task state")
        lease = self.leases.pop((kind, str(object_id)), None)
        guard = (
            " AND state='running' AND lease_until=?"
            if lease
            else " AND state!='running'"
        )
        with atomic(self.conn):
            cursor = self.conn.execute(
                """UPDATE crawl_tasks SET state=?,last_error=?,lease_until=NULL,
                next_attempt=?,payload=COALESCE(?,payload),updated_at=?
                WHERE scope=? AND kind=? AND object_id=?""" + guard,
                [
                    state,
                    error,
                    (
                        (datetime.now() + timedelta(seconds=retry_seconds)).isoformat()
                        if state == "retry"
                        else None
                    ),
                    json_text(payload) if payload is not None else None,
                    now(),
                    self.scope,
                    kind,
                    str(object_id),
                ]
                + ([lease] if lease else []),
            )
        return cursor.rowcount == 1

    def counts(self):
        return dict(
            self.conn.execute(
                "SELECT state,COUNT(*) FROM crawl_tasks WHERE scope=? GROUP BY state",
                (self.scope,),
            )
        )
