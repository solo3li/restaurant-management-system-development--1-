from typing import Optional
from pydantic import BaseModel, Field

class OrderItemInput(BaseModel):
    """عنصر مطلوب من قائمة الطعام مع الكمية والحجم والملاحظات"""
    name: Optional[str] = Field(default="", description="اسم الصنف المطلوب كما في المنيو (مثال: شاي كرك، برجر دجاج، بيتزا خضار)")
    quantity: int = Field(default=1, ge=1, description="الكمية المطلوبة (افتراضياً 1)")
    item_id: Optional[int] = Field(default=None, description="رقم معرف الصنف إذا كان معروفا")
    variant: Optional[str] = Field(default=None, description="الحجم أو الخيار المطلوب للصنف إن وجد (مثال: 'صغير', 'وسط', 'كبير', 'دبل', 'عائلي')")
    notes: Optional[str] = Field(default=None, description="ملاحظات خاصة بالصنف (مثال: بدون بصل، زيادة صوص)")

    class Config:
        extra = "allow"
