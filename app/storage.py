from __future__ import annotations
import mimetypes
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from flask import current_app

def media_root() -> Path:
    path = Path(current_app.config['MEDIA_ROOT']).resolve(); path.mkdir(parents=True, exist_ok=True); return path

def media_prefix() -> str:
    return current_app.config.get('MEDIA_URL_PREFIX', '/media').rstrip('/')

def key_from_media_url(url: str) -> str | None:
    if not url: return None
    parsed = urlparse(url.strip()); path = parsed.path or url
    prefix = media_prefix() + '/'
    if path.startswith(prefix): return path[len(prefix):].lstrip('/') or None
    return None

def local_path_from_url(url: str) -> Path | None:
    key = key_from_media_url(url); return (media_root() / key) if key else None

def open_media_bytes(url_or_key: str):
    key = key_from_media_url(url_or_key) or (url_or_key or '').lstrip('/')
    path = media_root() / key
    if not path.exists(): raise FileNotFoundError(key)
    ctype = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    return path.read_bytes(), ctype, path.name

def save_bytes(content: bytes, folder: str, filename_hint: str='file', content_type: str='') -> str:
    if not content: return ''
    ext = Path(filename_hint or '').suffix.lower() or (mimetypes.guess_extension((content_type or '').split(';')[0]) or '.bin')
    if ext == '.jpeg': ext = '.jpg'
    target = media_root() / folder.strip('/') / f'{uuid4().hex}{ext}'
    target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    rel = target.relative_to(media_root()).as_posix()
    return f'{media_prefix()}/{rel}'
