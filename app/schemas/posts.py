from pydantic import BaseModel, EmailStr, Field
from typing import List, Any
from datetime import datetime
from bson import ObjectId
from enum import Enum

class FILE_TYPE(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    TEXT = "text"
    
class MongoBaseModel(BaseModel):
    model_config = {
        "arbitrary_types_allowed": True
    }

    @staticmethod
    def validate_object_id(value: Any) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        try:
            return ObjectId(str(value))
        except Exception:
            raise ValueError(f"Invalid ObjectId: {value}")

class Post(MongoBaseModel):
    user_id: ObjectId
    caption: str
    file_path: str
    file_id: str
    file_type: FILE_TYPE
    chat_id: str
    message_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    tag_ids: List[ObjectId] = []

class Tags(MongoBaseModel):
    name: str
    user_id: List[ObjectId] = []
