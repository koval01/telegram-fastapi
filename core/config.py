"""
Configuration settings for the application.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_ID: str
    API_HASH: str
    SESSION: str
    ALLOWED_HOSTS: str
    REDIS_URI: str
    CRYPT_KEY: str

    class Config:
        env_file = "./.env.local"


settings = Settings()
