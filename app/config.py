import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    WP_BASE_URL = os.getenv("WP_BASE_URL", "https://www.paranaatual.com.br").rstrip("/")
    WP_PER_PAGE = int(os.getenv("WP_PER_PAGE", "20"))

    AUTO_SYNC_INTERVAL = int(os.getenv("AUTO_SYNC_INTERVAL", "0"))

    SITE_NAME = os.getenv("SITE_NAME", "Portal Trivox")
    LIVE_EMBED_TITLE = os.getenv("LIVE_EMBED_TITLE", "AO VIVO")

    MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/data/uploads")
    MEDIA_URL_PREFIX = os.getenv("MEDIA_URL_PREFIX", "/media")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(32 * 1024 * 1024)))
    # Integração do Portal Trivox com o serviço Baileys/WhatsApp já usado pelo Paraná Pop.
    WHATSAPP_SERVICE_URL = os.getenv("WHATSAPP_SERVICE_URL", "").rstrip("/")
    WHATSAPP_SERVICE_TOKEN = os.getenv("WHATSAPP_SERVICE_TOKEN", os.getenv("SERVICE_TOKEN", ""))
    WHATSAPP_TRIVOX_GROUP_ID = os.getenv("WHATSAPP_TRIVOX_GROUP_ID", os.getenv("PHOTO_TRIVOX_GROUP_ID", ""))
    WHATSAPP_AUTO_SEND_ENABLED = os.getenv("WHATSAPP_AUTO_SEND_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on", "sim"}
    WHATSAPP_SERVICE_TIMEOUT = int(os.getenv("WHATSAPP_SERVICE_TIMEOUT", "30"))
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

