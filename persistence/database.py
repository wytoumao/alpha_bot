from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aiomysql

from alpha_logging import get_logger


class Database:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        db: str,
        minsize: int = 1,
        maxsize: int = 5,
    ):
        self._pool: Optional[aiomysql.Pool] = None
        self._params = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "db": db,
            "minsize": minsize,
            "maxsize": maxsize,
            "autocommit": True,
            "charset": "utf8mb4",
        }
        self.logger = get_logger(__name__)
        self._lock = asyncio.Lock()
        self._schema_initialized = False

    async def connect(self) -> None:
        if self._pool:
            return
        async with self._lock:
            if self._pool:
                return
            self._pool = await aiomysql.create_pool(**self._params)
            self.logger.info("db.pool.created", **{k: v for k, v in self._params.items() if k != "password"})

    async def close(self) -> None:
        if not self._pool:
            return
        self._pool.close()
        await self._pool.wait_closed()
        self._pool = None
        self.logger.info("db.pool.closed")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[aiomysql.Connection]:
        if not self._pool:
            raise RuntimeError("Database pool not initialized. Call connect() first.")
        conn = await self._pool.acquire()
        try:
            yield conn
        finally:
            self._pool.release(conn)

    @asynccontextmanager
    async def cursor(self) -> AsyncIterator[aiomysql.Cursor]:
        async with self.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                yield cur

    async def execute(self, query: str, params: Optional[tuple[Any, ...]] = None) -> int:
        async with self.cursor() as cur:
            await cur.execute(query, params)
            return cur.rowcount

    async def executemany(self, query: str, params_seq: list[tuple[Any, ...]]) -> None:
        if not params_seq:
            return
        async with self.cursor() as cur:
            await cur.executemany(query, params_seq)

    async def fetchall(self, query: str, params: Optional[tuple[Any, ...]] = None) -> list[dict[str, Any]]:
        async with self.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchall()

    async def fetchone(self, query: str, params: Optional[tuple[Any, ...]] = None) -> Optional[dict[str, Any]]:
        async with self.cursor() as cur:
            await cur.execute(query, params)
            return await cur.fetchone()

    async def ensure_schema(self, schema_path: Path) -> None:
        if self._schema_initialized:
            return
        schema_path = schema_path.resolve()
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        content = schema_path.read_text(encoding="utf-8")
        statements: list[str] = []
        buffer: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            buffer.append(line)
            if stripped.endswith(";"):
                statement = "\n".join(buffer).rstrip(";").strip()
                if statement:
                    statements.append(statement)
                buffer = []
        if buffer:
            statement = "\n".join(buffer).strip()
            if statement:
                statements.append(statement)

        if not statements:
            self.logger.warning("db.schema.empty", path=str(schema_path))
            self._schema_initialized = True
            return

        async with self.cursor() as cur:
            for statement in statements:
                await cur.execute(statement)
        self.logger.info("db.schema.applied", path=str(schema_path), statements=len(statements))
        self._schema_initialized = True
