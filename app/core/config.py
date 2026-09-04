import os
from dotenv import load_dotenv

load_dotenv()

#Database
DB_HOST     = os.getenv("DB_SERVER", "localhost")
DB_NAME     = os.getenv("DB_DATABASE")
DB_USER     = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT     = os.getenv("DB_PORT", "5432")

#Auth
SECRET_KEY  = os.getenv("SECRET_KEY")
ALGORITHM   = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

SUPERADMIN_EMAIL: str = os.getenv("SUPERADMIN_EMAIL")
SUPERADMIN_PASSWORD: str = os.getenv("SUPERADMIN_PASSWORD")
SUPERADMIN_USERNAME: str = os.getenv("SUPERADMIN_USERNAME")

#File upload
MAX_IMPORT_FILE_SIZE = 5 * 1024 * 1024

#Email
FRONTEND_URL: str = os.getenv("FRONTEND_URL")
SMTP_USERNAME: str = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD")

#Intelligent analysis (Z.AI OpenAI-compatible API)
ZAI_API_KEY: str | None = os.getenv("ZAI_API_KEY")
ZAI_MODEL: str = os.getenv("ZAI_MODEL", "glm-5.3-flash")
ZAI_BASE_URL: str = os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
ZAI_TIMEOUT_SECONDS: float = float(os.getenv("ZAI_TIMEOUT_SECONDS", "30"))
DEMO_SEED_ENABLED: bool = os.getenv("DEMO_SEED_ENABLED", "false").lower() in {"1", "true", "yes"}
DEMO_USER_PASSWORD: str = os.getenv("DEMO_USER_PASSWORD", "Demo12345!")