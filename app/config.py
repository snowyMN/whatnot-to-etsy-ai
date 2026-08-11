from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    SHOP_URL: str = ""
    FLASK_ENV: str = "development"
    SECRET_KEY: str = "change-me"
    DATABASE_URL: str = "sqlite:///data/app.db"

    class Config:
        env_file = ".env"

settings = Settings()

OPENAI_API_KEY = settings.OPENAI_API_KEY
SHOP_URL = settings.SHOP_URL
SECRET_KEY = settings.SECRET_KEY
DATABASE_URL = settings.DATABASE_URL
