from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Any, Optional
from bson import ObjectId
from enum import Enum


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

class PlanType(str, Enum):
    free = "free"
    quarterly = "quarterly"
    yearly = "yearly"

class PreviousPlan(MongoBaseModel):
    plan: PlanType
    start_date: datetime
    end_date: datetime

class Membership(MongoBaseModel):
    plan: PlanType = PlanType.free
    expires_at: datetime | None = None
    current_start_date: datetime | None = None
    history: list[PreviousPlan] = Field(default_factory=list)

class PaymentRecord(BaseModel):
    user_id: str
    invoice_link: str
    amount: int
    status: str
    payment_date: datetime = Field(default_factory=lambda: datetime.now())
    plan_type: PlanType
    title: str
    telegram_payment_charge_id: Optional[str] = None 

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
    membership: Membership = Field(default_factory=Membership)

class InvoiceRequest(BaseModel):
    title: str
    description: str
    amount: int
    plan_type: PlanType