from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from bson import ObjectId
from datetime import datetime
from enum import Enum

class Boards(BaseModel):
    name: str = "Board"
    posts: List[ObjectId] = []
    created_at: datetime = Field(default_factory=datetime.now)