"""SQLite persistence for sessions, messages, and session-scoped todos."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterator, List, Optional, Union


class MemoryStoreError(Exception):
    """Base exception for SQLite storage failures."""


class SessionNotFoundError(MemoryStoreError):
    """Raised when a required user/session pair does not exist."""


class TodoNotFoundError(MemoryStoreError):
    """Raised when a todo does not exist in the requested user/session scope."""


class DuplicateSessionError(MemoryStoreError):
    """Raised when a user already owns the requested session id."""


@dataclass
class SessionRecord:
    """Stored Session metadata."""

    user_id: str
    session_id: str
    title: str
    created_at: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class MessageRecord:
    """One ordered message belonging to a Session."""

    id: int
    user_id: str
    session_id: str
    role: str
    content: str
    created_at: str
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class TodoRecord:
    """A Todo whose id is local to one user/session pair."""

    id: int
    user_id: str
    session_id: str
    content: str
    completed: bool
    created_at: str
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "content": self.content,
            "completed": self.completed,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class SQLiteStore:
    """Short-connection SQLite store with user/session isolation."""

    def __init__(
        self,
        db_path: Union[str, Path] = "data/agent.db",
    ) -> None:
        if not isinstance(db_path, (str, Path)):
            raise ValueError("db_path must be a string or Path.")
        if not str(db_path).strip():
            raise ValueError("db_path must not be empty.")
        self.db_path = Path(db_path)
        self._lock = RLock()
        self.initialize()

    def initialize(self) -> None:
        """Create the database directory, schema, and indexes idempotently."""
        with self._lock:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self._connection() as connection:
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.executescript(
                        """
                        CREATE TABLE IF NOT EXISTS sessions (
                            user_id TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            title TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            PRIMARY KEY (user_id, session_id)
                        );

                        CREATE TABLE IF NOT EXISTS messages (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            role TEXT NOT NULL,
                            content TEXT NOT NULL,
                            metadata_json TEXT,
                            created_at TEXT NOT NULL,
                            FOREIGN KEY (user_id, session_id)
                                REFERENCES sessions(user_id, session_id)
                                ON DELETE CASCADE
                        );

                        CREATE TABLE IF NOT EXISTS todos (
                            user_id TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            todo_id INTEGER NOT NULL,
                            content TEXT NOT NULL,
                            completed INTEGER NOT NULL DEFAULT 0,
                            created_at TEXT NOT NULL,
                            completed_at TEXT,
                            PRIMARY KEY (user_id, session_id, todo_id),
                            FOREIGN KEY (user_id, session_id)
                                REFERENCES sessions(user_id, session_id)
                                ON DELETE CASCADE
                        );

                        CREATE TABLE IF NOT EXISTS todo_counters (
                            user_id TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            next_id INTEGER NOT NULL,
                            PRIMARY KEY (user_id, session_id),
                            FOREIGN KEY (user_id, session_id)
                                REFERENCES sessions(user_id, session_id)
                                ON DELETE CASCADE
                        );

                        CREATE TABLE IF NOT EXISTS agent_runs (
                            run_id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            status TEXT NOT NULL CHECK (
                                status IN ('running', 'completed', 'failed')
                            ),
                            user_input TEXT NOT NULL,
                            final_answer TEXT,
                            error_type TEXT,
                            error_message TEXT,
                            total_llm_calls INTEGER NOT NULL DEFAULT 0,
                            total_tool_calls INTEGER NOT NULL DEFAULT 0,
                            started_at TEXT NOT NULL,
                            finished_at TEXT,
                            FOREIGN KEY (user_id, session_id)
                                REFERENCES sessions(user_id, session_id)
                                ON DELETE CASCADE
                        );

                        CREATE TABLE IF NOT EXISTS trace_events (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            run_id TEXT NOT NULL,
                            sequence INTEGER NOT NULL,
                            event_type TEXT NOT NULL,
                            step_number INTEGER,
                            payload_json TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            UNIQUE (run_id, sequence),
                            FOREIGN KEY (run_id)
                                REFERENCES agent_runs(run_id)
                                ON DELETE CASCADE
                        );

                        CREATE INDEX IF NOT EXISTS idx_messages_session_order
                            ON messages(user_id, session_id, id);
                        CREATE INDEX IF NOT EXISTS idx_todos_session_order
                            ON todos(user_id, session_id, todo_id);
                        CREATE INDEX IF NOT EXISTS idx_agent_runs_session_started
                            ON agent_runs(user_id, session_id, started_at);
                        CREATE INDEX IF NOT EXISTS idx_agent_runs_status_started
                            ON agent_runs(status, started_at);
                        CREATE INDEX IF NOT EXISTS idx_trace_events_run_sequence
                            ON trace_events(run_id, sequence);
                        """
                    )
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to initialize the SQLite store.") from error

    def create_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        title: str = "新会话",
    ) -> SessionRecord:
        user_id = self._validate_text(user_id, "user_id")
        session_id = (
            uuid.uuid4().hex
            if session_id is None
            else self._validate_text(session_id, "session_id")
        )
        title = self._validate_title(title)
        timestamp = self._now()
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    connection.execute(
                        """
                        INSERT INTO sessions (
                            user_id, session_id, title, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (user_id, session_id, title, timestamp, timestamp),
                    )
            except sqlite3.IntegrityError as error:
                raise DuplicateSessionError(
                    "Session '{}' already exists for this user.".format(session_id)
                ) from error
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to create the Session.") from error
        return SessionRecord(user_id, session_id, title, timestamp, timestamp)

    def get_session(self, user_id: str, session_id: str) -> Optional[SessionRecord]:
        user_id, session_id = self._validate_scope(user_id, session_id)
        try:
            with self._connection() as connection:
                row = connection.execute(
                    """
                    SELECT user_id, session_id, title, created_at, updated_at
                    FROM sessions
                    WHERE user_id = ? AND session_id = ?
                    """,
                    (user_id, session_id),
                ).fetchone()
        except sqlite3.Error as error:
            raise MemoryStoreError("Failed to read the Session.") from error
        return self._session_from_row(row) if row is not None else None

    def list_sessions(self, user_id: str) -> List[SessionRecord]:
        user_id = self._validate_text(user_id, "user_id")
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT user_id, session_id, title, created_at, updated_at
                    FROM sessions
                    WHERE user_id = ?
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (user_id,),
                ).fetchall()
        except sqlite3.Error as error:
            raise MemoryStoreError("Failed to list Sessions.") from error
        return [self._session_from_row(row) for row in rows]

    def update_session_title(
        self,
        user_id: str,
        session_id: str,
        title: str,
    ) -> SessionRecord:
        user_id, session_id = self._validate_scope(user_id, session_id)
        title = self._validate_title(title)
        timestamp = self._now()
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    cursor = connection.execute(
                        """
                        UPDATE sessions
                        SET title = ?, updated_at = ?
                        WHERE user_id = ? AND session_id = ?
                        """,
                        (title, timestamp, user_id, session_id),
                    )
                    if cursor.rowcount == 0:
                        raise self._session_not_found(user_id, session_id)
                    row = self._select_session(connection, user_id, session_id)
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to update the Session title.") from error
        return self._session_from_row(row)

    def touch_session(self, user_id: str, session_id: str) -> SessionRecord:
        user_id, session_id = self._validate_scope(user_id, session_id)
        timestamp = self._now()
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    cursor = connection.execute(
                        """
                        UPDATE sessions SET updated_at = ?
                        WHERE user_id = ? AND session_id = ?
                        """,
                        (timestamp, user_id, session_id),
                    )
                    if cursor.rowcount == 0:
                        raise self._session_not_found(user_id, session_id)
                    row = self._select_session(connection, user_id, session_id)
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to touch the Session.") from error
        return self._session_from_row(row)

    def delete_session(self, user_id: str, session_id: str) -> bool:
        user_id, session_id = self._validate_scope(user_id, session_id)
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    cursor = connection.execute(
                        "DELETE FROM sessions WHERE user_id = ? AND session_id = ?",
                        (user_id, session_id),
                    )
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to delete the Session.") from error
        return cursor.rowcount > 0

    def add_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MessageRecord:
        user_id, session_id = self._validate_scope(user_id, session_id)
        if role not in {"user", "assistant"}:
            raise ValueError("role must be 'user' or 'assistant'.")
        content = self._validate_text(content, "content")
        metadata_json = self._serialize_metadata(metadata)
        timestamp = self._now()
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    self._require_session(connection, user_id, session_id)
                    cursor = connection.execute(
                        """
                        INSERT INTO messages (
                            user_id, session_id, role, content,
                            metadata_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            session_id,
                            role,
                            content,
                            metadata_json,
                            timestamp,
                        ),
                    )
                    self._touch_session_row(connection, user_id, session_id, timestamp)
                    message_id = int(cursor.lastrowid)
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to add the message.") from error
        return MessageRecord(
            id=message_id,
            user_id=user_id,
            session_id=session_id,
            role=role,
            content=content,
            created_at=timestamp,
            metadata=metadata,
        )

    def add_exchange(
        self,
        user_id: str,
        session_id: str,
        user_content: str,
        assistant_content: str,
        assistant_metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[MessageRecord, MessageRecord]:
        """Atomically store one user message and its final assistant answer."""
        user_id, session_id = self._validate_scope(user_id, session_id)
        user_content = self._validate_text(user_content, "user_content")
        if len(user_content) > 8000:
            raise ValueError("user_content must not exceed 8000 characters.")
        assistant_content = self._validate_text(
            assistant_content,
            "assistant_content",
        )
        metadata_json = self._serialize_metadata(assistant_metadata)
        stored_metadata = (
            json.loads(metadata_json) if metadata_json is not None else None
        )
        timestamp = self._now()

        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    self._require_session(connection, user_id, session_id)
                    user_cursor = connection.execute(
                        """
                        INSERT INTO messages (
                            user_id, session_id, role, content,
                            metadata_json, created_at
                        ) VALUES (?, ?, 'user', ?, NULL, ?)
                        """,
                        (user_id, session_id, user_content, timestamp),
                    )
                    assistant_cursor = connection.execute(
                        """
                        INSERT INTO messages (
                            user_id, session_id, role, content,
                            metadata_json, created_at
                        ) VALUES (?, ?, 'assistant', ?, ?, ?)
                        """,
                        (
                            user_id,
                            session_id,
                            assistant_content,
                            metadata_json,
                            timestamp,
                        ),
                    )
                    self._touch_session_row(
                        connection,
                        user_id,
                        session_id,
                        timestamp,
                    )
                    user_message_id = int(user_cursor.lastrowid)
                    assistant_message_id = int(assistant_cursor.lastrowid)
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to save the conversation exchange.") from error

        return (
            MessageRecord(
                id=user_message_id,
                user_id=user_id,
                session_id=session_id,
                role="user",
                content=user_content,
                created_at=timestamp,
            ),
            MessageRecord(
                id=assistant_message_id,
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=assistant_content,
                created_at=timestamp,
                metadata=stored_metadata,
            ),
        )

    def list_messages(
        self,
        user_id: str,
        session_id: str,
        limit: Optional[int] = None,
    ) -> List[MessageRecord]:
        user_id, session_id = self._validate_scope(user_id, session_id)
        if limit is not None:
            self._validate_bounded_integer(limit, "limit", 1, 500)
        try:
            with self._connection() as connection:
                if limit is None:
                    rows = connection.execute(
                        """
                        SELECT id, user_id, session_id, role, content,
                               metadata_json, created_at
                        FROM messages
                        WHERE user_id = ? AND session_id = ?
                        ORDER BY id ASC
                        """,
                        (user_id, session_id),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT * FROM (
                            SELECT id, user_id, session_id, role, content,
                                   metadata_json, created_at
                            FROM messages
                            WHERE user_id = ? AND session_id = ?
                            ORDER BY id DESC
                            LIMIT ?
                        ) ORDER BY id ASC
                        """,
                        (user_id, session_id, limit),
                    ).fetchall()
        except sqlite3.Error as error:
            raise MemoryStoreError("Failed to list messages.") from error
        return [self._message_from_row(row) for row in rows]

    def count_messages(self, user_id: str, session_id: str) -> int:
        user_id, session_id = self._validate_scope(user_id, session_id)
        try:
            with self._connection() as connection:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS message_count
                    FROM messages
                    WHERE user_id = ? AND session_id = ?
                    """,
                    (user_id, session_id),
                ).fetchone()
        except sqlite3.Error as error:
            raise MemoryStoreError("Failed to count messages.") from error
        return int(row["message_count"])

    def clear_messages(self, user_id: str, session_id: str) -> int:
        user_id, session_id = self._validate_scope(user_id, session_id)
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    cursor = connection.execute(
                        "DELETE FROM messages WHERE user_id = ? AND session_id = ?",
                        (user_id, session_id),
                    )
                    if cursor.rowcount:
                        self._touch_session_row(
                            connection,
                            user_id,
                            session_id,
                            self._now(),
                        )
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to clear messages.") from error
        return cursor.rowcount

    def create_trace_run(
        self,
        run_id: str,
        user_id: str,
        session_id: str,
        user_input: str,
    ) -> Dict[str, Any]:
        """Create a running Trace and its first event atomically."""
        run_id = self._validate_text(run_id, "run_id")
        user_id, session_id = self._validate_scope(user_id, session_id)
        user_input = self._validate_text(user_input, "user_input")
        timestamp = self._now()
        payload_json = json.dumps({"status": "running"}, ensure_ascii=False)
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    self._require_session(connection, user_id, session_id)
                    connection.execute(
                        """
                        INSERT INTO agent_runs (
                            run_id, user_id, session_id, status, user_input,
                            final_answer, error_type, error_message,
                            total_llm_calls, total_tool_calls,
                            started_at, finished_at
                        ) VALUES (?, ?, ?, 'running', ?, NULL, NULL, NULL,
                                  0, 0, ?, NULL)
                        """,
                        (run_id, user_id, session_id, user_input, timestamp),
                    )
                    connection.execute(
                        """
                        INSERT INTO trace_events (
                            run_id, sequence, event_type, step_number,
                            payload_json, created_at
                        ) VALUES (?, 1, 'run_started', NULL, ?, ?)
                        """,
                        (run_id, payload_json, timestamp),
                    )
            except sqlite3.IntegrityError as error:
                raise MemoryStoreError("Failed to create the Trace run.") from error
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to create the Trace run.") from error
        result = self.get_trace_run(run_id)
        if result is None:
            raise MemoryStoreError("Created Trace run could not be read.")
        return result

    def append_trace_event(
        self,
        run_id: str,
        event_type: str,
        payload: Dict[str, Any],
        step_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Append the next event sequence to one running Trace."""
        run_id = self._validate_text(run_id, "run_id")
        event_type = self._validate_text(event_type, "event_type")
        if step_number is not None:
            self._validate_positive_integer(step_number, "step_number")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object.")
        try:
            payload_json = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as error:
            raise ValueError("payload must be JSON serializable.") from error
        timestamp = self._now()
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    run = connection.execute(
                        "SELECT status FROM agent_runs WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()
                    if run is None:
                        raise MemoryStoreError("Trace run was not found.")
                    if run["status"] != "running":
                        raise MemoryStoreError("Trace run is no longer running.")
                    row = connection.execute(
                        """
                        SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
                        FROM trace_events WHERE run_id = ?
                        """,
                        (run_id,),
                    ).fetchone()
                    sequence = int(row["next_sequence"])
                    cursor = connection.execute(
                        """
                        INSERT INTO trace_events (
                            run_id, sequence, event_type, step_number,
                            payload_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            sequence,
                            event_type,
                            step_number,
                            payload_json,
                            timestamp,
                        ),
                    )
                    event_id = int(cursor.lastrowid)
            except MemoryStoreError:
                raise
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to append the Trace event.") from error
        return {
            "id": event_id,
            "run_id": run_id,
            "sequence": sequence,
            "event_type": event_type,
            "step_number": step_number,
            "payload": json.loads(payload_json),
            "created_at": timestamp,
        }

    def update_trace_run_completed(
        self,
        run_id: str,
        final_answer: str,
        total_llm_calls: int,
        total_tool_calls: int,
    ) -> Optional[Dict[str, Any]]:
        """Mark one running Trace completed and return it."""
        run_id = self._validate_text(run_id, "run_id")
        final_answer = self._validate_text(final_answer, "final_answer")
        self._validate_non_negative_integer(total_llm_calls, "total_llm_calls")
        self._validate_non_negative_integer(total_tool_calls, "total_tool_calls")
        timestamp = self._now()
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    cursor = connection.execute(
                        """
                        UPDATE agent_runs
                        SET status = 'completed', final_answer = ?,
                            error_type = NULL, error_message = NULL,
                            total_llm_calls = ?, total_tool_calls = ?,
                            finished_at = ?
                        WHERE run_id = ? AND status = 'running'
                        """,
                        (
                            final_answer,
                            total_llm_calls,
                            total_tool_calls,
                            timestamp,
                            run_id,
                        ),
                    )
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to complete the Trace run.") from error
        if cursor.rowcount == 0:
            return None
        return self.get_trace_run(run_id)

    def update_trace_run_failed(
        self,
        run_id: str,
        error_type: str,
        error_message: str,
    ) -> Optional[Dict[str, Any]]:
        """Mark one running Trace failed and return it."""
        run_id = self._validate_text(run_id, "run_id")
        error_type = self._validate_text(error_type, "error_type")
        error_message = self._validate_text(error_message, "error_message")
        timestamp = self._now()
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    cursor = connection.execute(
                        """
                        UPDATE agent_runs
                        SET status = 'failed', final_answer = NULL,
                            error_type = ?, error_message = ?, finished_at = ?
                        WHERE run_id = ? AND status = 'running'
                        """,
                        (error_type, error_message, timestamp, run_id),
                    )
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to fail the Trace run.") from error
        if cursor.rowcount == 0:
            return None
        return self.get_trace_run(run_id)

    def get_trace_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return one Trace run by id."""
        run_id = self._validate_text(run_id, "run_id")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    """
                    SELECT run_id, user_id, session_id, status, user_input,
                           final_answer, error_type, error_message,
                           total_llm_calls, total_tool_calls,
                           started_at, finished_at
                    FROM agent_runs WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
        except sqlite3.Error as error:
            raise MemoryStoreError("Failed to read the Trace run.") from error
        return self._trace_run_from_row(row) if row is not None else None

    def list_trace_runs(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List one user's Trace runs newest first with optional filters."""
        user_id = self._validate_text(user_id, "user_id")
        if session_id is not None:
            session_id = self._validate_text(session_id, "session_id")
        if status is not None:
            self._validate_trace_status(status)
        self._validate_trace_limit(limit)
        clauses = ["user_id = ?"]
        parameters: List[Any] = [user_id]
        if session_id is not None:
            clauses.append("session_id = ?")
            parameters.append(session_id)
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        parameters.append(limit)
        query = """
            SELECT run_id, user_id, session_id, status, user_input,
                   final_answer, error_type, error_message,
                   total_llm_calls, total_tool_calls,
                   started_at, finished_at
            FROM agent_runs
            WHERE {}
            ORDER BY started_at DESC, run_id DESC
            LIMIT ?
        """.format(" AND ".join(clauses))
        try:
            with self._connection() as connection:
                rows = connection.execute(query, parameters).fetchall()
        except sqlite3.Error as error:
            raise MemoryStoreError("Failed to list Trace runs.") from error
        return [self._trace_run_from_row(row) for row in rows]

    def list_trace_events(self, run_id: str) -> List[Dict[str, Any]]:
        """Return a Trace's events in sequence order."""
        run_id = self._validate_text(run_id, "run_id")
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT id, run_id, sequence, event_type, step_number,
                           payload_json, created_at
                    FROM trace_events
                    WHERE run_id = ?
                    ORDER BY sequence ASC
                    """,
                    (run_id,),
                ).fetchall()
        except sqlite3.Error as error:
            raise MemoryStoreError("Failed to list Trace events.") from error
        return [self._trace_event_from_row(row) for row in rows]

    def delete_trace_run(self, user_id: str, run_id: str) -> bool:
        """Delete one Trace only when it belongs to the supplied user."""
        user_id = self._validate_text(user_id, "user_id")
        run_id = self._validate_text(run_id, "run_id")
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    cursor = connection.execute(
                        "DELETE FROM agent_runs WHERE user_id = ? AND run_id = ?",
                        (user_id, run_id),
                    )
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to delete the Trace run.") from error
        return cursor.rowcount > 0

    def add_todo(self, user_id: str, session_id: str, content: str) -> TodoRecord:
        user_id, session_id = self._validate_scope(user_id, session_id)
        content = self._validate_text(content, "content")
        if len(content) > 1000:
            raise ValueError("content must not exceed 1000 characters.")
        timestamp = self._now()
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    self._require_session(connection, user_id, session_id)
                    counter_row = connection.execute(
                        """
                        SELECT next_id FROM todo_counters
                        WHERE user_id = ? AND session_id = ?
                        """,
                        (user_id, session_id),
                    ).fetchone()
                    if counter_row is None:
                        todo_id = 1
                        connection.execute(
                            """
                            INSERT INTO todo_counters (
                                user_id, session_id, next_id
                            ) VALUES (?, ?, ?)
                            """,
                            (user_id, session_id, 2),
                        )
                    else:
                        todo_id = int(counter_row["next_id"])
                        connection.execute(
                            """
                            UPDATE todo_counters SET next_id = ?
                            WHERE user_id = ? AND session_id = ?
                            """,
                            (todo_id + 1, user_id, session_id),
                        )
                    connection.execute(
                        """
                        INSERT INTO todos (
                            user_id, session_id, todo_id, content,
                            completed, created_at, completed_at
                        ) VALUES (?, ?, ?, ?, 0, ?, NULL)
                        """,
                        (user_id, session_id, todo_id, content, timestamp),
                    )
                    self._touch_session_row(connection, user_id, session_id, timestamp)
            except sqlite3.IntegrityError as error:
                raise MemoryStoreError("Failed to allocate a unique Todo id.") from error
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to add the Todo.") from error
        return TodoRecord(
            id=todo_id,
            user_id=user_id,
            session_id=session_id,
            content=content,
            completed=False,
            created_at=timestamp,
        )

    def list_todos(self, user_id: str, session_id: str) -> List[TodoRecord]:
        user_id, session_id = self._validate_scope(user_id, session_id)
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT todo_id, user_id, session_id, content,
                           completed, created_at, completed_at
                    FROM todos
                    WHERE user_id = ? AND session_id = ?
                    ORDER BY todo_id ASC
                    """,
                    (user_id, session_id),
                ).fetchall()
        except sqlite3.Error as error:
            raise MemoryStoreError("Failed to list Todos.") from error
        return [self._todo_from_row(row) for row in rows]

    def complete_todo(
        self,
        user_id: str,
        session_id: str,
        todo_id: int,
    ) -> TodoRecord:
        user_id, session_id = self._validate_scope(user_id, session_id)
        self._validate_positive_integer(todo_id, "todo_id")
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    row = self._select_todo(connection, user_id, session_id, todo_id)
                    if row is None:
                        raise self._todo_not_found(todo_id)
                    if not bool(row["completed"]):
                        completed_at = self._now()
                        connection.execute(
                            """
                            UPDATE todos
                            SET completed = 1, completed_at = ?
                            WHERE user_id = ? AND session_id = ? AND todo_id = ?
                            """,
                            (completed_at, user_id, session_id, todo_id),
                        )
                        self._touch_session_row(
                            connection,
                            user_id,
                            session_id,
                            completed_at,
                        )
                        row = self._select_todo(
                            connection,
                            user_id,
                            session_id,
                            todo_id,
                        )
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to complete the Todo.") from error
        return self._todo_from_row(row)

    def delete_todo(
        self,
        user_id: str,
        session_id: str,
        todo_id: int,
    ) -> bool:
        user_id, session_id = self._validate_scope(user_id, session_id)
        self._validate_positive_integer(todo_id, "todo_id")
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    cursor = connection.execute(
                        """
                        DELETE FROM todos
                        WHERE user_id = ? AND session_id = ? AND todo_id = ?
                        """,
                        (user_id, session_id, todo_id),
                    )
                    if cursor.rowcount:
                        self._touch_session_row(
                            connection,
                            user_id,
                            session_id,
                            self._now(),
                        )
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to delete the Todo.") from error
        return cursor.rowcount > 0

    def clear_todos(self, user_id: str, session_id: str) -> int:
        user_id, session_id = self._validate_scope(user_id, session_id)
        with self._lock:
            try:
                with self._connection(write=True) as connection:
                    cursor = connection.execute(
                        "DELETE FROM todos WHERE user_id = ? AND session_id = ?",
                        (user_id, session_id),
                    )
                    if cursor.rowcount:
                        self._touch_session_row(
                            connection,
                            user_id,
                            session_id,
                            self._now(),
                        )
            except sqlite3.Error as error:
                raise MemoryStoreError("Failed to clear Todos.") from error
        return cursor.rowcount

    @contextmanager
    def _connection(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.db_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _validate_text(
        value: Any,
        field_name: str,
        max_chars: Optional[int] = None,
    ) -> str:
        if not isinstance(value, str):
            raise ValueError("{} must be a string.".format(field_name))
        value = value.strip()
        if not value:
            raise ValueError("{} must not be empty.".format(field_name))
        if max_chars is None and field_name in {"user_id", "session_id"}:
            max_chars = 128
        if max_chars is not None and len(value) > max_chars:
            raise ValueError(
                "{} must not exceed {} characters.".format(field_name, max_chars)
            )
        return value

    @classmethod
    def _validate_scope(cls, user_id: str, session_id: str) -> tuple[str, str]:
        return (
            cls._validate_text(user_id, "user_id", max_chars=128),
            cls._validate_text(session_id, "session_id", max_chars=128),
        )

    @classmethod
    def _validate_title(cls, title: str) -> str:
        title = cls._validate_text(title, "title")
        if len(title) > 200:
            raise ValueError("title must not exceed 200 characters.")
        return title

    @staticmethod
    def _validate_positive_integer(value: Any, field_name: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("{} must be an integer greater than 0.".format(field_name))

    @staticmethod
    def _validate_non_negative_integer(value: Any, field_name: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                "{} must be an integer greater than or equal to 0.".format(field_name)
            )

    @staticmethod
    def _validate_bounded_integer(
        value: Any,
        field_name: str,
        minimum: int,
        maximum: int,
    ) -> None:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < minimum
            or value > maximum
        ):
            raise ValueError(
                "{} must be an integer from {} to {}.".format(
                    field_name, minimum, maximum
                )
            )

    @staticmethod
    def _validate_trace_status(status: str) -> None:
        if status not in {"running", "completed", "failed"}:
            raise ValueError("status must be 'running', 'completed', or 'failed'.")

    @staticmethod
    def _validate_trace_limit(limit: Any) -> None:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > 200
        ):
            raise ValueError("limit must be an integer from 1 to 200.")

    @staticmethod
    def _serialize_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        if metadata is None:
            return None
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object or None.")
        try:
            return json.dumps(metadata, ensure_ascii=False)
        except (TypeError, ValueError) as error:
            raise ValueError("metadata must be JSON serializable.") from error

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            user_id=row["user_id"],
            session_id=row["session_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> MessageRecord:
        metadata_json = row["metadata_json"]
        try:
            metadata = json.loads(metadata_json) if metadata_json is not None else None
        except json.JSONDecodeError as error:
            raise MemoryStoreError("Stored message metadata is invalid JSON.") from error
        if metadata is not None and not isinstance(metadata, dict):
            raise MemoryStoreError("Stored message metadata is not an object.")
        return MessageRecord(
            id=int(row["id"]),
            user_id=row["user_id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            metadata=metadata,
        )

    @staticmethod
    def _trace_run_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "user_id": row["user_id"],
            "session_id": row["session_id"],
            "status": row["status"],
            "user_input": row["user_input"],
            "final_answer": row["final_answer"],
            "error_type": row["error_type"],
            "error_message": row["error_message"],
            "total_llm_calls": int(row["total_llm_calls"]),
            "total_tool_calls": int(row["total_tool_calls"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    @staticmethod
    def _trace_event_from_row(row: sqlite3.Row) -> Dict[str, Any]:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as error:
            raise MemoryStoreError("Stored Trace payload is invalid JSON.") from error
        if not isinstance(payload, dict):
            raise MemoryStoreError("Stored Trace payload is not an object.")
        return {
            "id": int(row["id"]),
            "run_id": row["run_id"],
            "sequence": int(row["sequence"]),
            "event_type": row["event_type"],
            "step_number": (
                int(row["step_number"])
                if row["step_number"] is not None
                else None
            ),
            "payload": payload,
            "created_at": row["created_at"],
        }

    @staticmethod
    def _todo_from_row(row: sqlite3.Row) -> TodoRecord:
        return TodoRecord(
            id=int(row["todo_id"]),
            user_id=row["user_id"],
            session_id=row["session_id"],
            content=row["content"],
            completed=bool(row["completed"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _select_session(
        connection: sqlite3.Connection,
        user_id: str,
        session_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT user_id, session_id, title, created_at, updated_at
            FROM sessions WHERE user_id = ? AND session_id = ?
            """,
            (user_id, session_id),
        ).fetchone()
        if row is None:
            raise SessionNotFoundError("Session does not exist for this user.")
        return row

    @classmethod
    def _require_session(
        cls,
        connection: sqlite3.Connection,
        user_id: str,
        session_id: str,
    ) -> None:
        cls._select_session(connection, user_id, session_id)

    @staticmethod
    def _touch_session_row(
        connection: sqlite3.Connection,
        user_id: str,
        session_id: str,
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            UPDATE sessions SET updated_at = ?
            WHERE user_id = ? AND session_id = ?
            """,
            (timestamp, user_id, session_id),
        )

    @staticmethod
    def _select_todo(
        connection: sqlite3.Connection,
        user_id: str,
        session_id: str,
        todo_id: int,
    ) -> Optional[sqlite3.Row]:
        return connection.execute(
            """
            SELECT todo_id, user_id, session_id, content,
                   completed, created_at, completed_at
            FROM todos
            WHERE user_id = ? AND session_id = ? AND todo_id = ?
            """,
            (user_id, session_id, todo_id),
        ).fetchone()

    @staticmethod
    def _session_not_found(user_id: str, session_id: str) -> SessionNotFoundError:
        return SessionNotFoundError(
            "Session '{}' does not exist for this user.".format(session_id)
        )

    @staticmethod
    def _todo_not_found(todo_id: int) -> TodoNotFoundError:
        return TodoNotFoundError("Todo with id {} was not found.".format(todo_id))
