import os


def _database_url():
    url = os.getenv("DATABASE_URL", "sqlite:///dev.db")
    # Railway/SQLAlchemy pode fornecer explicitamente o dialeto psycopg (v3),
    # mas este projeto usa psycopg2-binary. Normalizamos para o driver instalado.
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql+psycopg2://" + url[len("postgresql+psycopg://"):]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def _engine_options(database_url: str) -> dict:
    options = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    # Avoid hanging the whole Gunicorn worker for a long time when Railway
    # private networking/Postgres is temporarily unavailable.
    if database_url.startswith(("postgresql", "postgres://")):
        options.update(pool_size=int(os.getenv("DB_POOL_SIZE", "4")),
                       max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "1")),
                       pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")))
        options["connect_args"] = {"connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "5"))}

    return options



class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(SQLALCHEMY_DATABASE_URI)

    WP_BASE_URL = os.getenv("WP_BASE_URL", "https://www.paranaatual.com.br").rstrip("/")
    WP_PER_PAGE = int(os.getenv("WP_PER_PAGE", "20"))

    AUTO_SYNC_INTERVAL = int(os.getenv("AUTO_SYNC_INTERVAL", "0"))

    SITE_NAME = os.getenv("SITE_NAME", "Portal Trivox")
    LIVE_EMBED_TITLE = os.getenv("LIVE_EMBED_TITLE", "AO VIVO")

    MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/data/uploads")
    MEDIA_URL_PREFIX = os.getenv("MEDIA_URL_PREFIX", "/media")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(128 * 1024 * 1024)))
    VIDEO_MAX_BYTES = int(os.getenv("VIDEO_MAX_BYTES", str(80 * 1024 * 1024)))
    VIDEO_MAX_SECONDS = int(os.getenv("VIDEO_MAX_SECONDS", "180"))
    # Integração do Portal Trivox com o serviço Baileys/WhatsApp já usado pelo Paraná Pop.
    WHATSAPP_SERVICE_URL = os.getenv("WHATSAPP_SERVICE_URL", "").rstrip("/")
    WHATSAPP_SERVICE_TOKEN = os.getenv("WHATSAPP_SERVICE_TOKEN", os.getenv("SERVICE_TOKEN", ""))
    WHATSAPP_TRIVOX_GROUP_ID = os.getenv("WHATSAPP_TRIVOX_GROUP_ID", os.getenv("PHOTO_TRIVOX_GROUP_ID", ""))
    WHATSAPP_AUTO_SEND_ENABLED = os.getenv("WHATSAPP_AUTO_SEND_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on", "sim"}
    WHATSAPP_SERVICE_TIMEOUT = int(os.getenv("WHATSAPP_SERVICE_TIMEOUT", "30"))
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


    IMAGE_MAX_BYTES = int(os.getenv('IMAGE_MAX_BYTES', '15000000'))
    IMAGE_MAX_PIXELS = int(os.getenv('IMAGE_MAX_PIXELS', '24000000'))
    IMAGE_WEB_MAX_EDGE = int(os.getenv('IMAGE_WEB_MAX_EDGE', '1280'))
    IMAGE_WEB_QUALITY = int(os.getenv('IMAGE_WEB_QUALITY', '68'))
    FFMPEG_THREADS = int(os.getenv('FFMPEG_THREADS', '2'))
    R2_ENDPOINT_URL = os.getenv('R2_ENDPOINT_URL', '').strip().rstrip('/')
    R2_BUCKET = os.getenv('R2_BUCKET', '').strip()
    R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID', '').strip()
    R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY', '').strip()
    R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', '').strip().rstrip('/')
    MEDIA_WORKER_ENABLED = os.getenv('MEDIA_WORKER_ENABLED', '1') == '1'
    MEDIA_OPTIMIZE_LEGACY = os.getenv('MEDIA_OPTIMIZE_LEGACY', '0') == '1'
