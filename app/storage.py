from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, unquote
from flask import current_app
from . import media as media_service


def media_root():
    return media_service.root()


def media_prefix():
    return current_app.config.get('MEDIA_URL_PREFIX', '/media').rstrip('/')


def key_from_media_url(url):
    if media_service.is_local_url(url):
        return unquote(urlparse(url).path).removeprefix('/media/')
    base = current_app.config.get('R2_PUBLIC_URL', '').rstrip('/') + '/portaltrivox/'
    if current_app.config.get('R2_PUBLIC_URL') and (url or '').startswith(base):
        return unquote(url[len(base):])
    return None


def local_path_from_url(url):
    key = key_from_media_url(url)
    return media_service.local_path(key) if key else None


def open_media_bytes(url_or_key):
    key = key_from_media_url(url_or_key) or url_or_key
    path = media_service.local_path(key)
    if path.stat().st_size > current_app.config['IMAGE_MAX_BYTES']:
        raise ValueError('Imagem excede o limite permitido')
    return path.read_bytes(), media_service.content_type(path.name), path.name


def save_stream(stream, folder, filename_hint='file', content_type='', *, optimize_image=False):
    return media_service.save_stream(stream, filename_hint, folder, optimize_image=optimize_image)


def save_bytes(content, folder, filename_hint='file', content_type=''):
    if not content:
        return ''
    with BytesIO(content) as stream:
        return save_stream(stream, folder, filename_hint, content_type)
