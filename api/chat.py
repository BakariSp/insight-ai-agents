"""Legacy /chat compatibility route — DEPRECATED.

Superseded by POST /api/conversation in Phase 4. Kept for backward compatibility
but should not be used by new clients.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.chat_agent import ChatAgent

router = APIRouter()

# Singleton agent instance
_chat_agent = ChatAgent()


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    model: str | None = None


@router.post("/chat", deprecated=True)
async def chat(req: ChatRequest):
    """DEPRECATED: Use POST /api/conversation instead. Kept for backward compatibility."""
    try:
        result = _chat_agent.run(
            req.message,
            conversation_id=req.conversation_id,
            model=req.model,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
