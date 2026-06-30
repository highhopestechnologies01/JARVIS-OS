"""Memory API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db
from src.db.models import Memory
from src.core.memory import memory_engine

router = APIRouter()


class MemoryCreate(BaseModel):
    type: str
    content: str
    topic: str | None = None
    importance: int = 5
    source: str | None = None
    metadata: dict = {}


class MemoryResponse(BaseModel):
    id: str
    type: str
    topic: str | None
    content: str
    importance: int
    source: str | None
    created_at: str

    @classmethod
    def from_orm(cls, m: Memory) -> "MemoryResponse":
        return cls(
            id=str(m.id),
            type=m.type,
            topic=m.topic,
            content=m.content,
            importance=m.importance,
            source=m.source,
            created_at=m.created_at.isoformat(),
        )


@router.post("/", response_model=MemoryResponse)
async def store_memory(body: MemoryCreate, db: AsyncSession = Depends(get_db)):
    """Store a new memory."""
    memory = await memory_engine.store(
        db,
        type=body.type,
        content=body.content,
        topic=body.topic,
        importance=body.importance,
        source=body.source,
        metadata=body.metadata,
    )
    return MemoryResponse.from_orm(memory)


@router.get("/", response_model=list[MemoryResponse])
async def search_memories(
    q: str | None = Query(None),
    type: str | None = Query(None),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search memories by text or type."""
    memories = await memory_engine.search(db, query=q, type=type, limit=limit)
    return [MemoryResponse.from_orm(m) for m in memories]


@router.get("/recent", response_model=list[MemoryResponse])
async def recent_memories(
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Get most recent memories."""
    memories = await memory_engine.recent(db, limit=limit)
    return [MemoryResponse.from_orm(m) for m in memories]


@router.delete("/{memory_id}")
async def delete_memory(memory_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a memory by ID."""
    deleted = await memory_engine.delete(db, memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": True}
