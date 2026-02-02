"""Legacy /chat compatibility route — kept for Phase 0 backward compat.

Will be replaced by /api/page/generate + /api/page/chat in Phase 4.
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


@router.post("/chat")
async def chat(req: ChatRequest):
    """Main chat endpoint (compatibility). Accepts a message and returns agent response."""
    try:
        result = _chat_agent.run(
            req.message,
            conversation_id=req.conversation_id,
            model=req.model,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
