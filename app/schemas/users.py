from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Any
from bson import ObjectId


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

class User(MongoBaseModel):
    user_id: str
    first_name: str
    chat_id: str
    username: str = ""
    last_name: str | None = None
    profile_image_id: str | None = None
    profile_image_path: str | None = None
    posts: List[ObjectId] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    
    