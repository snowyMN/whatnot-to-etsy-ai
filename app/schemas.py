from pydantic import BaseModel

class ItemSchema(BaseModel):
    id: int | None = None
    title: str
    description: str | None = None
    price: str | None = None

    class Config:
        orm_mode = True
