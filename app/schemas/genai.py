from pydantic import BaseModel, Field
from typing import List, Optional

class InlineData(BaseModel):
    mime_type: str = Field(..., description="MIME type of the data, e.g., image/jpeg, video/quicktime")
    data: str = Field(..., description="Base64-encoded binary data of the media file")


class Part(BaseModel):
    inline_data: Optional[InlineData] = Field(None, description="Inline media data for Gemini input")
    text: Optional[str] = Field(None, description="Text prompt for Gemini")


class Content(BaseModel):
    parts: List[Part] = Field(..., description="List of content parts including media and/or text")


class GeminiRequest(BaseModel):
    contents: List[Content] = Field(..., description="Top-level list of Gemini API content items")