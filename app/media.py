"""Bounded image processing and durable, single-consumer media delivery.

Publication stores the text immediately. Remote images retain their working source
until a background task replaces them. Originals are never removed by migration.
"""
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, quote, unquote

import click
import requests
from flask import current_app, request, jsonify
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select, case
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge
from .models import db, MediaAsset, MediaTask, Post

_IMAGE_LOCK = threading.Lock()
IMAGE_SRC = re.compile(r'(<img\b[^>]*?\bsrc=["\'])([^"\']+)(["\'])', re.I)
MEDIA_LINK = re.compile(r'(?:(?:https?://[^\s"\'<>/]+))?/media/[^\s"\'<>?&#)]+')
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.ico'}


def content_type(filename):
    # Python 3.11/minimal runtime images do not always ship a WebP MIME entry.
    known = {'.webp': 'image/webp', '.avif': 'image/avif', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif', '.svg': 'image/svg+xml', '.ico': 'image/x-icon'}
    return known.get(Path(filename).suffix.lower()) or mimetypes.guess_type(filename)[0] or 'application/octet-stream'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def root():
    return Path(current_app.config['MEDIA_ROOT']).resolve()


def local_path(relative):
    path = (root() / relative).resolve()
    if not path.is_relative_to(root()):
        raise BadRequest('Caminho de mídia inválido')
    return path


def r2_enabled():
    return all(current_app.config.get(k) for k in ('R2_ENDPOINT_URL', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET', 'R2_PUBLIC_URL'))


def r2_client():
    if 'r2_client' not in current_app.extensions:
        import boto3
        from botocore.config import Config
        current_app.extensions['r2_client'] = boto3.client('s3', endpoint_url=current_app.config['R2_ENDPOINT_URL'], aws_access_key_id=current_app.config['R2_ACCESS_KEY_ID'], aws_secret_access_key=current_app.config['R2_SECRET_ACCESS_KEY'], region_name='auto', config=Config(connect_timeout=4, read_timeout=15, max_pool_connections=2, retries={'max_attempts': 2, 'mode': 'standard'}))
    return current_app.extensions['r2_client']


def _asset(source):
    return db.session.execute(select(MediaAsset).where(MediaAsset.source_key == digest(source)).execution_options(populate_existing=True)).scalar_one_or_none()


def _remember(source, relative, original_bytes=0, public_url=None, size_bytes=None):
    # Independent transaction: never commits an unfinished editorial request.
    table = MediaAsset.__table__
    values = dict(source_key=digest(source), source_url=source, local_path=relative, size_bytes=size_bytes if size_bytes is not None else local_path(relative).stat().st_size, original_bytes=original_bytes, updated_at=datetime.utcnow())
    if public_url:
        values['public_url'] = public_url
    with db.engine.begin() as conn:
        found = conn.execute(select(table.c.id).where(table.c.source_key == values['source_key'])).scalar()
        if found:
            conn.execute(table.update().where(table.c.id == found).values(**values))
        else:
            conn.execute(table.insert().values(**values))


def enqueue(kind, target, background=False):
    table = MediaTask.__table__
    key = digest(kind + ':' + str(target))
    stored_kind = 'backfill-' + kind if background else kind
    try:
        with db.engine.begin() as conn:
            task = conn.execute(select(table.c.id).where(table.c.task_key == key)).scalar()
            if task:
                conn.execute(table.update().where(table.c.id == task).values(kind=stored_kind, state='pending', attempts=0, available_at=datetime.utcnow(), error=None))
            else:
                conn.execute(table.insert().values(kind=stored_kind, target=str(target), task_key=key, state='pending', attempts=0, available_at=datetime.utcnow()))
    except IntegrityError:
        pass  # Another request already queued the same durable work.


def enqueue_post(post_id):
    enqueue('post', post_id)


def _bounded_copy(source, output):
    count = 0
    while chunk := source.read(64 * 1024):
        count += len(chunk)
        if count > current_app.config['IMAGE_MAX_BYTES']:
            raise RequestEntityTooLarge('A imagem excede o limite de 15 MB.')
        output.write(chunk)
    return count


def save_stream(stream, filename, subdir='general', *, optimize_image=True):
    from .image_uploads import prepared_image
    import shutil
    stream.seek(0)
    with tempfile.TemporaryFile() as source:
        # Videos have a separate byte limit and are never decoded as images.
        limit = current_app.config['IMAGE_MAX_BYTES'] if optimize_image else current_app.config['VIDEO_MAX_BYTES']
        original_size = 0
        while chunk := stream.read(64 * 1024):
            original_size += len(chunk)
            if original_size > limit:
                raise RequestEntityTooLarge('Arquivo excede o limite permitido.')
            source.write(chunk)
        source.seek(0)
        with prepared_image(source, filename, content_type(filename), enabled=optimize_image) as (prepared, name, _mime):
            hasher = hashlib.sha256()
            while chunk := prepared.read(64 * 1024):
                hasher.update(chunk)
            prepared.seek(0)
            ext = Path(name).suffix.lower() or '.bin'
            safe_folder = re.sub(r'[^a-zA-Z0-9/_-]', '', subdir).strip('/') or 'general'
            relative = f'{safe_folder}/{hasher.hexdigest()}{ext}'
            if r2_enabled():
                from boto3.s3.transfer import TransferConfig
                prepared.seek(0, 2)
                size = prepared.tell()
                prepared.seek(0)
                key = 'portaltrivox/' + relative
                r2_client().upload_fileobj(prepared, current_app.config['R2_BUCKET'], key,
                    ExtraArgs={'ContentType': content_type(relative), 'CacheControl': 'public, max-age=31536000, immutable'},
                    Config=TransferConfig(use_threads=False, max_concurrency=1))
                public = current_app.config['R2_PUBLIC_URL'] + '/' + quote(key, safe='/')
                with requests.head(public, timeout=(4, 10), allow_redirects=True) as response:
                    response.raise_for_status()
                    if int(response.headers.get('Content-Length', -1)) != size:
                        raise ValueError('public_size_mismatch')
                _remember('/media/' + relative, relative, original_size, public, size_bytes=size)
                return public

            if current_app.config.get('R2_BUCKET'):
                raise RuntimeError('R2 configurado sem credenciais completas; upload local bloqueado')
            destination = local_path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                temp_name = None
                try:
                    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.', delete=False) as temp:
                        temp_name = temp.name
                        shutil.copyfileobj(prepared, temp, length=64 * 1024)
                    os.replace(temp_name, destination)
                finally:
                    if temp_name and Path(temp_name).exists():
                        Path(temp_name).unlink()
    url = '/media/' + relative
    _remember(url, relative, original_size)
    return resolve_media(url)


def save_upload(stream, filename, subdir='general'):
    return save_stream(stream, filename, subdir)


def resolve_media(url):
    if not url:
        return url
    parsed = urlparse(url)
    # Do not confuse another publisher's /media path with our own files.
    if parsed.netloc and parsed.hostname not in {'portaltrivox.com.br', 'www.portaltrivox.com.br', 'portal-trivox.up.railway.app'}:
        return url
    if not parsed.path.startswith('/media/'):
        return url
    asset = _asset(unquote(parsed.path))
    if asset and asset.public_url:
        if asset.public_url.startswith('/media/') and asset.public_url != url:
            child = _asset(asset.public_url)
            return child.public_url if child and child.public_url else asset.public_url
        return asset.public_url
    return url


def remote_image(url, folder='imported'):
    if not url:
        return url
    if is_local_url(url):
        return resolve_media(url)
    base = current_app.config.get('R2_PUBLIC_URL', '').rstrip('/')
    if base and url.startswith(base + '/'):
        return url
    cached = _asset(url)
    if cached:
        return cached.public_url or resolve_media('/media/' + cached.local_path)
    parsed = urlparse(url)
    if parsed.scheme not in ('https', 'http'):
        return url
    with tempfile.TemporaryFile() as source:
        with requests.get(url, stream=True, timeout=(4, 15)) as response:
            response.raise_for_status()
            count = 0
            for chunk in response.iter_content(64 * 1024):
                count += len(chunk)
                if count > current_app.config['IMAGE_MAX_BYTES']:
                    raise ValueError('remote_image_too_large')
                source.write(chunk)
            source.seek(0)
            with Image.open(source) as image:
                ext = '.' + ('jpg' if image.format == 'JPEG' else image.format.lower())
            source.seek(0)
            local_url = save_upload(source, 'source' + ext, folder)
    # Canonical lookup only: aliases may still point to historical originals.
    key = local_url.removeprefix('/media/') if local_url.startswith('/media/') else None
    if key is None:
        base = current_app.config['R2_PUBLIC_URL'].rstrip('/') + '/portaltrivox/'
        key = unquote(local_url.removeprefix(base)) if local_url.startswith(base) else None
    if key is not None:
        canonical = _asset('/media/' + key)
        _remember(url, key, count, canonical.public_url if canonical else None,
                  size_bytes=canonical.size_bytes if canonical else 0)
    return local_url


def is_local_url(url):
    parsed = urlparse(url or '')
    return parsed.path.startswith('/media/') and (not parsed.netloc or parsed.hostname in {'portaltrivox.com.br', 'www.portaltrivox.com.br', 'portal-trivox.up.railway.app'})


def deferred_image(url, folder='imported'):
    if not url or is_local_url(url):
        return resolve_media(url)
    cached = _asset(url)
    if cached:
        return cached.public_url or resolve_media('/media/' + cached.local_path)
    enqueue('remote', url)
    # Keep a working source while the queue downloads, compresses and copies.
    return url


def process_post(post_id):
    row = db.session.execute(select(Post.featured_image, Post.content_html).where(Post.id == int(post_id))).first()
    db.session.remove()
    if not row:
        return
    featured, body = row
    cache = {}
    def convert(src):
        src = html.unescape(src)
        if src not in cache:
            cache[src] = remote_image(src)
        return cache[src]
    new_featured = convert(featured) if featured else featured
    body_for_images = re.sub(r'(<img\b[^>]*?)\s+srcset=[\"\'][^\"\']*[\"\']', r'\1', body or '', flags=re.I)
    new_body = IMAGE_SRC.sub(lambda m: m[1] + html.escape(convert(m[2]), quote=True) + m[3], body_for_images) if body else body
    # Compare snapshots so a slow image task cannot overwrite a newer edit.
    table = Post.__table__
    with db.engine.begin() as conn:
        conn.execute(table.update().where(table.c.id == int(post_id), table.c.featured_image == featured).values(featured_image=new_featured))
        conn.execute(table.update().where(table.c.id == int(post_id), table.c.content_html == body).values(content_html=new_body))


def _optimized_relative(relative):
    path = local_path(relative)
    # Historical files are uploaded from their existing volume without creating another local copy.
    if r2_enabled():
        return relative
    # Generated social cards keep their exact dimensions and PNG representation.
    if (len(path.stem) == 64 or relative.startswith('gerador/') or path.suffix.lower() not in IMAGE_EXT):
        return relative
    with path.open('rb') as stream:
        output = save_upload(stream, path.name, 'optimized')
    if output.startswith('/media/'):
        return output.removeprefix('/media/')
    base = current_app.config['R2_PUBLIC_URL'].rstrip('/') + '/portaltrivox/'
    if output.startswith(base):
        return unquote(output.removeprefix(base))
    raise ValueError('missing_canonical_asset')


def upload_asset(relative):
    if not r2_enabled():
        raise ValueError('r2_not_configured')
    path = local_path(relative)
    if not path.is_file():
        raise FileNotFoundError('missing_local_asset')
    asset = _asset('/media/' + relative)
    if asset and asset.public_url and asset.public_url.startswith(current_app.config['R2_PUBLIC_URL'] + '/'):
        return
    original_size = path.stat().st_size
    relative_out = _optimized_relative(relative)
    destination = local_path(relative_out)
    from boto3.s3.transfer import TransferConfig
    key = 'portaltrivox/' + relative_out
    r2_client().upload_file(str(destination), current_app.config['R2_BUCKET'], key,
        ExtraArgs={'ContentType': content_type(relative_out), 'CacheControl': 'public, max-age=31536000, immutable'},
        Config=TransferConfig(use_threads=False, max_concurrency=1))
    public = current_app.config['R2_PUBLIC_URL'] + '/' + quote(key, safe='/')
    # Do not switch any live links unless the public endpoint serves this file.
    with requests.head(public, timeout=(4, 10), allow_redirects=True) as response:
        response.raise_for_status()
        if int(response.headers.get('Content-Length', -1)) != destination.stat().st_size:
            raise ValueError('public_size_mismatch')
    _remember('/media/' + relative, relative_out, original_size, public)
    with db.engine.begin() as conn:
        conn.execute(MediaAsset.__table__.update().where(MediaAsset.local_path == relative_out).values(public_url=public))


def optimize_legacy(relative):
    path = local_path(relative)
    if not path.is_file():
        return
    target = _optimized_relative(relative)
    if target != relative:
        _remember('/media/' + relative, target, path.stat().st_size, '/media/' + target)


def seed_existing_posts():
    cursor = 0
    while True:
        with db.engine.connect() as conn:
            ids = conn.execute(select(Post.id).where(Post.id > cursor).order_by(Post.id).limit(50)).scalars().all()
        if not ids:
            break
        for post_id in ids:
            with db.engine.connect() as conn:
                exists = conn.execute(select(MediaTask.id).where(MediaTask.task_key == digest('post:'+str(post_id)))).scalar()
            if not exists:
                enqueue('post', post_id, background=True)
            cursor = post_id
        run_one()
        db.session.remove()


def list_media(page, per_page):
    rows = db.session.execute(select(MediaAsset).where(MediaAsset.source_url.like('/media/%'), MediaAsset.hidden.is_(False)).order_by(MediaAsset.updated_at.desc(), MediaAsset.id.desc()).offset((page-1)*per_page).limit(per_page+1)).scalars().all()
    return [dict(name=Path(a.local_path).name, relative_path=a.source_url.removeprefix('/media/'), is_image=Path(a.local_path).suffix.lower() in IMAGE_EXT | {'.svg'}, delete_url=a.source_url, url=resolve_media(a.source_url), size_kb=max(1, round(a.size_bytes/1024)), updated_at=a.updated_at) for a in rows[:per_page]], len(rows)>per_page


def delete_media(url):
    # Shared content hashes and original files stay available for old articles.
    # Hide only the catalog entry; never implicitly delete shared R2 objects.
    asset = _asset(urlparse(url).path if '/media/' in url else url)
    if asset:
        asset.hidden = True
        db.session.commit()


@contextmanager
def worker_lock():
    import fcntl
    with (root() / '.media-worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_one():
    task = db.session.execute(select(MediaTask).where(MediaTask.state == 'pending', MediaTask.available_at <= datetime.utcnow()).order_by(case((MediaTask.kind == 'asset', 0), (MediaTask.kind.in_(['post', 'remote']), 1), (MediaTask.kind == 'backfill-asset', 2), (MediaTask.kind == 'backfill-optimize', 3), else_=4), MediaTask.id).limit(1)).scalar_one_or_none()
    if not task:
        return False
    task_id, kind, target, attempts, revision = task.id, task.kind.removeprefix('backfill-'), task.target, task.attempts, task.available_at
    db.session.remove()
    try:
        if kind == 'post':
            process_post(target)
        elif kind == 'remote':
            remote_image(target)
        elif kind == 'asset':
            upload_asset(target)
        elif kind == 'optimize':
            optimize_legacy(target)
        error = None
    except Exception as exc:
        error = type(exc).__name__  # Never log remote URLs, tokens or credentials.
    db.session.remove()
    with db.engine.begin() as conn:
        # A save during processing requeues work and must not be marked done.
        state = 'done' if error is None else ('failed' if attempts >= 4 else 'pending')
        conn.execute(MediaTask.__table__.update().where(MediaTask.id == task_id, MediaTask.available_at == revision).values(state=state, attempts=attempts+1, error=error, available_at=datetime.utcnow()+timedelta(seconds=min(3600,30*2**attempts))))
    return True


def index_existing():
    # Streaming directory walk, no list/sort of the entire volume in RAM.
    for directory, _, files in os.walk(root()):
        for filename in files:
            if filename.startswith('.'):
                continue
            path = Path(directory)/filename
            relative = path.relative_to(root()).as_posix()
            source = '/media/' + relative
            if not _asset(source):
                _remember(source, relative, path.stat().st_size)
            kind = 'asset' if r2_enabled() else 'optimize'
            if r2_enabled() or (current_app.config.get('MEDIA_OPTIMIZE_LEGACY', False) and len(path.stem) != 64 and not relative.startswith('gerador/') and path.suffix.lower() in IMAGE_EXT):
                with db.engine.connect() as conn:
                    exists = conn.execute(select(MediaTask.id).where(MediaTask.task_key == digest(kind+':'+relative))).scalar()
                if not exists:
                    enqueue(kind, relative, background=True)
            db.session.remove()
            yield relative


def _worker(app):
    # The OS lock also covers gunicorn overlap during rolling deployments.
    while True:
        try:
            with app.app_context(), worker_lock() as acquired:
                if acquired:
                    if not app.extensions.get('media_indexed'):
                        indexed = 0
                        for n, _ in enumerate(index_existing()):
                            indexed += 1
                            if n % 10 == 0:
                                run_one()
                            time.sleep(.01)
                        if r2_enabled():
                            seed_existing_posts()
                        app.extensions['media_indexed'] = True
                        app.logger.warning('MEDIA_INDEX_READY files=%s r2=%s', indexed, r2_enabled())
                    did_work = run_one()
                else:
                    did_work = False
                db.session.remove()
        except Exception as exc:
            app.logger.warning('Media worker retry scheduled (%s)', type(exc).__name__)
            did_work = False
        time.sleep(1 if did_work else 5)


def init_media(app):
    from sqlalchemy import event, inspect
    from sqlalchemy.orm import Session
    from flask import has_app_context
    # The global hooks are installed once, and run against the current Flask app.
    if not event.contains(Session, 'after_flush', _collect_posts):
        event.listen(Session, 'after_flush', _collect_posts)

    @app.after_request
    def direct_cloud_urls(response):
        # Resolve links in one bounded query, avoiding an image proxy/redirect per view.
        if response.mimetype == 'text/html' and not response.direct_passthrough and not request.path.startswith('/admin'):
            text = response.get_data(as_text=True)
            links = set(MEDIA_LINK.findall(text))
            keys = {digest(unquote(urlparse(link).path)) for link in links if not urlparse(link).hostname or urlparse(link).hostname in {'portaltrivox.com.br','www.portaltrivox.com.br','portal-trivox.up.railway.app'}}
            if keys:
                rows = db.session.execute(select(MediaAsset.source_url, MediaAsset.public_url).where(MediaAsset.source_key.in_(list(keys)[:512]), MediaAsset.public_url.isnot(None))).all()
                mapping = dict(rows)
                text = MEDIA_LINK.sub(lambda m: mapping.get(unquote(urlparse(m[0]).path), m[0]) if not urlparse(m[0]).hostname or urlparse(m[0]).hostname in {'portaltrivox.com.br','www.portaltrivox.com.br','portal-trivox.up.railway.app'} else m[0], text)
                response.set_data(text)
        return response

    @app.get('/admin/api/resources')
    def media_resources():
        from flask_login import current_user
        if not current_user.is_authenticated or not current_user.is_admin:
            return jsonify(error='unauthorized'), 401
        from sqlalchemy import func
        counts = db.session.execute(select(MediaTask.state, func.count()).group_by(MediaTask.state)).all()
        totals = db.session.execute(select(func.sum(MediaAsset.size_bytes), func.sum(MediaAsset.original_bytes)).where(MediaAsset.source_url.like('/media/%'))).first()
        from .resources import memory_snapshot
        return jsonify(r2_enabled=r2_enabled(), queue=dict(counts), catalog_bytes=totals[0] or 0, catalog_source_bytes=totals[1] or 0, memory=memory_snapshot())

    @app.cli.command('retry-media')
    def retry_media():
        with db.engine.begin() as conn:
            result = conn.execute(MediaTask.__table__.update().where(MediaTask.state == 'failed').values(state='pending', attempts=0, available_at=datetime.utcnow()))
        click.echo(f'Requeued {result.rowcount} tasks')

    @app.cli.command('migrate-media')
    @click.option('--process', is_flag=True, help='Process queued work serially after indexing.')
    def migrate_media(process):
        with worker_lock() as acquired:
            if not acquired:
                raise click.ClickException('Media worker is already running; queued jobs will be processed automatically.')
            count = sum(1 for _ in index_existing())
            click.echo(f'Indexed {count} files; originals retained. R2 configured: {r2_enabled()}')
            if process:
                while run_one():
                    pass

    if app.config.get('MEDIA_WORKER_ENABLED'):
        threading.Thread(target=_worker, args=(app,), daemon=True, name='media-worker').start()


def _collect_posts(session, _context):
    # The durable image task commits/rolls back with its article. No network work
    # and no independent connection are needed in this editorial transaction.
    from sqlalchemy import inspect
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    posts = [post for post in session.new.union(session.dirty)
             if isinstance(post, Post) and (post in session.new or any(inspect(post).attrs[field].history.has_changes() for field in ('featured_image', 'content_html')))]
    if not posts:
        return
    conn = session.connection()
    insert = sqlite_insert if conn.dialect.name == 'sqlite' else pg_insert
    for post in posts:
        values = dict(kind='post', target=str(post.id), task_key=digest('post:' + str(post.id)),
                      state='pending', attempts=0, available_at=datetime.utcnow(), error=None)
        stmt = insert(MediaTask.__table__).values(**values)
        conn.execute(stmt.on_conflict_do_update(index_elements=['task_key'], set_=values))
