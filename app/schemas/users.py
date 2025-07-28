from pydantic import BaseModel, Field
from datetime import datetime
from typing import List
from bson import ObjectId

class User(BaseModel):
    user_id: str
    username: str
    first_name: str
    last_name: str | None = None
    profile_image: str | None = None
    posts: List[ObjectId] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now())