from sqlalchemy import Column, Integer, String, Text
from app.db import Base

class ImportedItem(Base):
    __tablename__ = "imported_items"

    id = Column(Integer, primary_key=True, index=True)
    source_url = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=True)
    price = Column(String, nullable=True)
    size = Column(String, nullable=True)
    condition = Column(String, nullable=True)
    description_notes = Column(Text, nullable=True)
    image_urls = Column(Text, nullable=True)

    etsy_title = Column(String, nullable=True)
    etsy_description = Column(Text, nullable=True)
    etsy_tags = Column(Text, nullable=True)
    review_notes = Column(Text, nullable=True)
