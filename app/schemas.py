from pydantic import BaseModel, ConfigDict

class ItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    title: str
    description: str | None = None
    price: str | None = None
