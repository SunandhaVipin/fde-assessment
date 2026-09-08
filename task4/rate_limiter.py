import sqlite3
import time
import uuid
from pathlib import Path


class RateLimitExceeded(Exception):
    """Raised when a tenant exceeds the token budget."""
    pass


class SQLiteTokenRateLimiter:
    def __init__(
        self,
        db_path: str = "rate_limit.db",
        token_limit: int = 50_000,
        window_seconds: int = 60,
    ) -> None:
        self.db_path = Path(db_path)
        self.token_limit = token_limit
        self.window_seconds = window_seconds
        self._initialize_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.db_path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )

        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA synchronous=NORMAL;")

        return connection

    def _initialize_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS token_usage (
                    reservation_id TEXT PRIMARY KEY,
                    tenant_key TEXT NOT NULL,
                    tokens INTEGER NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_token_usage_tenant_time
                ON token_usage (tenant_key, created_at)
                """
            )

    def _delete_expired(
        self,
        connection: sqlite3.Connection,
        now: float,
    ) -> None:
        cutoff = now - self.window_seconds

        connection.execute(
            """
            DELETE FROM token_usage
            WHERE created_at < ?
            """,
            (cutoff,),
        )

    def reserve(
        self,
        tenant_key: str,
        tokens: int,
    ) -> str:
        """
        Atomically reserve tokens for a tenant.

        Returns a reservation ID when successful.
        Raises RateLimitExceeded if the reservation would exceed
        the 50,000-token sliding-window limit.
        """
        if not tenant_key:
            raise ValueError("tenant_key is required")

        if tokens <= 0:
            raise ValueError("tokens must be positive")

        if tokens > self.token_limit:
            raise RateLimitExceeded(
                f"Requested {tokens} tokens exceeds the "
                f"{self.token_limit}-token limit"
            )

        reservation_id = str(uuid.uuid4())
        now = time.time()

        connection = self._connect()

        try:
            connection.execute("BEGIN IMMEDIATE")

            self._delete_expired(connection, now)

            row = connection.execute(
                """
                SELECT COALESCE(SUM(tokens), 0)
                FROM token_usage
                WHERE tenant_key = ?
                AND created_at >= ?
                """,
                (
                    tenant_key,
                    now - self.window_seconds,
                ),
            ).fetchone()

            current_usage = int(row[0])

            if current_usage + tokens > self.token_limit:
                connection.execute("ROLLBACK")

                raise RateLimitExceeded(
                    f"Token limit exceeded for tenant"
                )

            connection.execute(
                """
                INSERT INTO token_usage (
                    reservation_id,
                    tenant_key,
                    tokens,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    reservation_id,
                    tenant_key,
                    tokens,
                    now,
                ),
            )

            connection.execute("COMMIT")

            return reservation_id

        except RateLimitExceeded:
            raise

        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass

            raise

        finally:
            connection.close()

    def reconcile(
        self,
        reservation_id: str,
        actual_tokens: int,
    ) -> None:
        """
        Replace the reserved token estimate with actual provider usage.
        """
        if actual_tokens < 0:
            raise ValueError("actual_tokens cannot be negative")

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE token_usage
                SET tokens = ?
                WHERE reservation_id = ?
                """,
                (
                    actual_tokens,
                    reservation_id,
                ),
            )

    def release(
        self,
        reservation_id: str,
    ) -> None:
        """
        Delete a reservation when no provider successfully completes.
        """
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM token_usage
                WHERE reservation_id = ?
                """,
                (reservation_id,),
            )

    def current_usage(
        self,
        tenant_key: str,
    ) -> int:
        """
        Return the tenant's token usage inside the active 60-second window.
        """
        now = time.time()

        with self._connect() as connection:
            self._delete_expired(connection, now)

            row = connection.execute(
                """
                SELECT COALESCE(SUM(tokens), 0)
                FROM token_usage
                WHERE tenant_key = ?
                AND created_at >= ?
                """,
                (
                    tenant_key,
                    now - self.window_seconds,
                ),
            ).fetchone()

            return int(row[0])