from pydantic import BaseModel, EmailStr, Field
from typing import List
from datetime import datetime
from bson import ObjectId
from enum import Enum

class FILE_TYPE(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    TEXT = "text"

class Post(BaseModel):
    user_id: ObjectId
    caption: str
    file_path: str
    file_id: str
    file_type: FILE_TYPE
    chat_id: str
    message_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    tag_ids: List[ObjectId] = []

class Tags(BaseModel):
    name: str
    user_id: List[ObjectId] = []
