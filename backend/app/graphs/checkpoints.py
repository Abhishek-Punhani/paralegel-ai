"""Persistent checkpoints supporting synchronous reads and async graph execution.

SQLite's serializer and write locking remain managed by LangGraph. Async calls
run those short SQLite operations in worker threads, while API snapshot reads
can continue to use get_state(). Separate databases isolate the two graphs.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from app.config import SQLITE_CHECKPOINT_PATH


class PersistentSqliteSaver(SqliteSaver):
    async def aget_tuple(self, config):
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        records = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for record in records:
            yield record

    async def adelete_thread(self, thread_id):
        await asyncio.to_thread(self.delete_thread, thread_id)


def checkpoint_store(graph_name: str) -> PersistentSqliteSaver:
    configured = Path(SQLITE_CHECKPOINT_PATH).expanduser().resolve()
    path = configured.with_name(f"{configured.stem}.{graph_name}{configured.suffix or '.db'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    return PersistentSqliteSaver(connection)
