from __future__ import annotations 
 
from typing import Literal, Optional 
 
from pydantic import Field 
 
from models.base import CamelModel 
 
 
class ClarifyPayload(CamelModel): 
    question: str 
    options: Optional[list[str]] = None 
    hint: Optional[str] = None 
 
 
class FinalResult(CamelModel): 
    status: Literal['answer_ready', 'artifact_ready', 'clarify_needed'] 
    message: str 
    artifacts: list[str] = Field(default_factory=list) 
    clarify: Optional[ClarifyPayload] = None
