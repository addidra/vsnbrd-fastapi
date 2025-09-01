from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from bson import ObjectId
from datetime import datetime
from enum import Enum


# Enums
class FILE_TYPE(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


# ObjectId compatible type
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        return ObjectId(str(v))


# BaseModel for MongoDB
class MongoBaseModel(BaseModel):
    class Config:
        json_encoders = {ObjectId: str}
        arbitrary_types_allowed = True


# FileDetails model
class FileDetails(MongoBaseModel):
    file_id: str
    file_path: str


# Wrapper for resolution-based file details
class ResolutionDetails(MongoBaseModel):
    high: FileDetails
    medium: Optional[FileDetails] = None
    # low: Optional[FileDetails] = None


# Post model
class Post(MongoBaseModel):
    user_id: str
    caption: str
    file_details: ResolutionDetails
    file_type: FILE_TYPE
    message_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    tag_names: List[str] = []


class Tags(MongoBaseModel):
    name: str
    user_id: List[PyObjectId] = []