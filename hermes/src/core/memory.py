"""
Memory Engine — Hermes long-term context store.

Responsibilities:
- Store facts, preferences, events, people, projects
- Retrieve relevant memories by type or text search
- Prune expired memories
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Memory

log = structlog.get_logger()


class MemoryEngine:
    """Interface to the long-term memory store."""

    async def store(
        self,
        db: AsyncSession,
        type: str,
        content: str,
        topic: str | None = None,
        importance: int = 5,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> Memory:
        """Store a new memory."""
        memory = Memory(
            type=type,
            topic=topic,
            content=content,
            importance=importance,
            source=source,
            metadata_=metadata or {},
            expires_at=expires_at,
        )
        db.add(memory)
        await db.flush()
        log.info("memory.stored", type=type, topic=topic, id=str(memory.id))
        return memory

    async def search(
        self,
        db: AsyncSession,
        query: str | None = None,
        type: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """Search memories by text or type."""
        stmt = select(Memory).where(
            or_(
                Memory.expires_at.is_(None),
                Memory.expires_at > datetime.now(timezone.utc),
            )
        )
        if type:
            stmt = stmt.where(Memory.type == type)
        if query:
            stmt = stmt.where(
                or_(
                    Memory.content.ilike(f"%{query}%"),
                    Memory.topic.ilike(f"%{query}%"),
                )
            )
        stmt = stmt.order_by(Memory.importance.desc(), Memory.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, db: AsyncSession, memory_id: UUID) -> Memory | None:
        """Get a specific memory by ID."""
        result = await db.execute(select(Memory).where(Memory.id == memory_id))
        return result.scalar_one_or_none()

    async def delete(self, db: AsyncSession, memory_id: UUID) -> bool:
        """Delete a memory."""
        memory = await self.get(db, memory_id)
        if not memory:
            return False
        await db.delete(memory)
        log.info("memory.deleted", id=str(memory_id))
        return True

    async def prune_expired(self, db: AsyncSession) -> int:
        """Remove expired memories. Returns count deleted."""
        stmt = select(Memory).where(
            and_(
                Memory.expires_at.is_not(None),
                Memory.expires_at <= datetime.now(timezone.utc),
            )
        )
        result = await db.execute(stmt)
        expired = result.scalars().all()
        count = len(expired)
        for m in expired:
            await db.delete(m)
        if count:
            log.info("memory.pruned", count=count)
        return count

    async def recent(self, db: AsyncSession, limit: int = 10) -> list[Memory]:
        """Get most recently created memories."""
        stmt = (
            select(Memory)
            .where(
                or_(
                    Memory.expires_at.is_(None),
                    Memory.expires_at > datetime.now(timezone.utc),
                )
            )
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())


# Singleton
memory_engine = MemoryEngine()
