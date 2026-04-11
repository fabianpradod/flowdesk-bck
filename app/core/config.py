import os
from dotenv import load_dotenv

load_dotenv()

# Database
DB_HOST     = os.getenv("DB_SERVER", "localhost")
DB_NAME     = os.getenv("DB_DATABASE")
DB_USER     = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT     = os.getenv("DB_PORT", "5432")

# Auth
SECRET_KEY  = os.getenv("SECRET_KEY")
ALGORITHM   = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

SUPERADMIN_EMAIL: str = os.getenv("SUPERADMIN_EMAIL")
SUPERADMIN_PASSWORD: str = os.getenv("SUPERADMIN_PASSWORD")
SUPERADMIN_USERNAME: str = os.getenv("SUPERADMIN_USERNAME")