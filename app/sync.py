from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import mimetypes
import re
import time
import uuid

import bleach
import requests
from flask import current_app
from slugify import slugify

from .models import db, Post, Category
from .wp_client import WPClient

ALLOWED_TAGS = bleach.sanitizer.ALLOWED_TAGS.union({
    "p","br","hr","img","h1","h2","h3","h4","h5","h6","blockquote",
    "ul","ol","li","strong","em","a","span","div","figure","figcaption"
})
ALLOWED_ATTRS = dict(bleach.sanitizer.ALLOWED_ATTRIBUTES)
ALLOWED_ATTRS.update({
    "a": ["href","title","target","rel"],
    "img": ["src","alt","title","loading","width","height"],
    "div": ["class"], "span": ["class"], "figure": ["class"],
})
IMG_SRC_RE = re.compile(r"(<img\b[^>]*?\bsrc=[\"'])([^\"']+)([\"'])", re.IGNORECASE)


def _featured_media(p: dict) -> dict:
    try:
        media = p.get("_embedded", {}).get("wp:featuredmedia", [])
        return media[0] if media else {}
    except Exception:
        return {}


def _featured_img_from_embed(p: dict) -> str | None:
    return _featured_media(p).get("source_url") or None


def _author_from_embed(p: dict) -> str | None:
    try:
        authors = p.get("_embedded", {}).get("author", [])
        return (authors[0].get("name") if authors else None) or None
    except Exception:
        return None


def _image_credit_from_embed(p: dict) -> str | None:
    media = _featured_media(p)
    caption = ((media.get("caption") or {}).get("rendered") or "").strip()
    if caption:
        return bleach.clean(caption, tags=[], strip=True)[:255]
    return None


def _media_url(relative_path: str) -> str:
    prefix = current_app.config.get("MEDIA_URL_PREFIX", "/media").rstrip("/")
    return f"{prefix}/{relative_path.lstrip('/')}"


def _guess_extension(source_url: str, content_type: str = "") -> str:
    parsed = urlparse(source_url or "")
    ext = Path(parsed.path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}:
        return ext
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    if guessed in {".jpe", ".jpeg"}: return ".jpg"
    if guessed in {".jpg", ".png", ".webp", ".gif", ".svg"}: return guessed
    return ".jpg"


def download_external_image(source_url: str | None, folder: str = "wp") -> str | None:
    if not source_url:
        return None
    if source_url.startswith("/media/"):
        return source_url

    media_root = Path(current_app.config["MEDIA_ROOT"])
    target_dir = media_root / folder / datetime.utcnow().strftime("%Y/%m")
    target_dir.mkdir(parents=True, exist_ok=True)
    last_error = None
    response = None
    for attempt in range(3):
        try:
            response = requests.get(
                source_url,
                timeout=(8, 25),
                stream=True,
                headers={"User-Agent": "Portal-Trivox-Image-Importer/1.0"},
            )
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
    if response is None or not response.ok:
        raise last_error or RuntimeError("Falha ao baixar imagem")

    ext = _guess_extension(source_url, response.headers.get("Content-Type", ""))
    filename = f"{uuid.uuid4().hex}{ext}"
    target_path = target_dir / filename
    with target_path.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                fh.write(chunk)
    relative = target_path.relative_to(media_root).as_posix()
    return _media_url(relative)


def localize_content_images(html: str | None, report: dict | None = None) -> str | None:
    if not html: return html
    cache = {}
    def repl(match):
        prefix, src, suffix = match.groups()
        if not src or src.startswith("/media/") or src.startswith("data:"):
            return match.group(0)
        if src not in cache:
            try:
                cache[src] = download_external_image(src, folder="wp/content") or src
                if report is not None and cache[src].startswith("/media/"):
                    report["success"] = report.get("success", 0) + 1
            except Exception:
                cache[src] = src
                if report is not None:
                    report["failed"] = report.get("failed", 0) + 1
        return f"{prefix}{cache[src]}{suffix}"
    return IMG_SRC_RE.sub(repl, html)


def upsert_category(c: dict) -> tuple[Category, bool]:
    wp_id = c["id"]
    slug = c.get("slug") or slugify(c.get("name", "cat"))
    name = c.get("name", "")
    with db.session.no_autoflush:
        cat = Category.query.filter_by(wp_id=wp_id).first()
        slug_cat = Category.query.filter_by(slug=slug).first()
    created = False
    if cat is None and slug_cat is not None:
        cat = slug_cat
    if cat is None:
        cat = Category(wp_id=wp_id, slug=slug, name=name)
        db.session.add(cat)
        created = True
    else:
        cat.wp_id, cat.slug, cat.name = wp_id, slug, name
    return cat, created


def sync_categories(client: WPClient, progress_callback=None):
    page = 1
    processed = 0
    while True:
        data, headers = client.list_categories(page=page, per_page=100)
        if not data: break
        total = int(headers.get("X-WP-Total", len(data)) or len(data))
        for c in data:
            upsert_category(c)
            processed += 1
            if progress_callback:
                progress_callback(processed=processed, total=total, category=c)
        db.session.commit()
        if len(data) < 100: break
        page += 1
    return processed


def upsert_wp_post(p: dict, download_images: bool = False) -> dict:
    wp_id = p["id"]
    title = (p.get("title") or {}).get("rendered") or ""
    slug = p.get("slug") or slugify(title)[:200]
    excerpt = (p.get("excerpt") or {}).get("rendered") or ""
    content = (p.get("content") or {}).get("rendered") or ""
    source_url = p.get("link") or None
    date_str = p.get("date_gmt") or p.get("date")
    mod_str = p.get("modified_gmt") or p.get("modified")
    published_at = datetime.fromisoformat(date_str.replace("Z", "")) if date_str else None
    updated_at = datetime.fromisoformat(mod_str.replace("Z", "")) if mod_str else None

    # Localiza o registro ANTES de baixar imagens. Em reimportações, matérias sem
    # alteração no WordPress e já totalmente locais são puladas, evitando baixar
    # os mesmos arquivos novamente e acelerando retomadas após falhas.
    with db.session.no_autoflush:
        post = Post.query.filter_by(wp_id=wp_id).first()
        url_post = Post.query.filter_by(source_url=source_url).first() if source_url else None
        slug_post = Post.query.filter_by(slug=slug).first()
    if post is None and url_post is not None:
        post = url_post
    if post is None and slug_post is not None:
        post = slug_post

    content_is_local = not post or not post.content_html or not re.search(r'<img\b[^>]*\bsrc=["\']https?://', post.content_html, re.I)
    featured_is_local = not post or not post.featured_image or post.featured_image.startswith("/media/")
    if post and post.source == "wp" and post.updated_at == updated_at and content_is_local and featured_is_local:
        # Ainda garante vínculos e metadados baratos, sem rede/download.
        post.wp_id = wp_id
        post.source_url = source_url or post.source_url
        post.title = title
        post.slug = slug
        post.author_name = _author_from_embed(p) or post.author_name
        post.featured_image_credit = _image_credit_from_embed(p) or post.featured_image_credit
        post.categories = []
        for cid in (p.get("categories") or []):
            cat = Category.query.filter_by(wp_id=cid).first()
            if cat:
                post.categories.append(cat)
        return {
            "post": post, "created": False, "skipped": True, "title": title, "wp_id": wp_id,
            "image_successes": 0, "image_failures": 0,
        }

    featured = _featured_img_from_embed(p)
    excerpt_safe = bleach.clean(excerpt, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    content_safe = bleach.clean(content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    image_report = {"success": 0, "failed": 0}
    if download_images:
        if featured and not featured.startswith("/media/"):
            try:
                featured = download_external_image(featured, folder="wp/featured") or featured
                if featured.startswith("/media/"):
                    image_report["success"] += 1
            except Exception:
                image_report["failed"] += 1
        content_safe = localize_content_images(content_safe, report=image_report)

    created = False
    if post is None:
        post = Post(wp_id=wp_id, source="wp", slug=slug, title=title)
        db.session.add(post)
        created = True
    else:
        post.wp_id = wp_id
        post.source = "wp"

    post.title = title
    post.slug = slug
    post.excerpt = excerpt_safe
    post.content_html = content_safe
    post.featured_image = featured
    post.featured_image_credit = _image_credit_from_embed(p)
    post.author_name = _author_from_embed(p)
    post.source_url = source_url or post.source_url
    post.published_at = published_at
    post.updated_at = updated_at
    post.categories = []
    for cid in (p.get("categories") or []):
        cat = Category.query.filter_by(wp_id=cid).first()
        if cat:
            post.categories.append(cat)
    return {
        "post": post, "created": created, "skipped": False, "title": title, "wp_id": wp_id,
        "image_successes": image_report["success"], "image_failures": image_report["failed"],
    }


def sync_posts(client: WPClient, max_pages: int | None = None, per_page: int = 20, download_images: bool = False, progress_callback=None):
    page = 1
    processed = 0
    while True:
        if max_pages is not None and page > max_pages: break
        data, headers = client.list_posts(page=page, per_page=per_page)
        if not data: break
        total_pages = int(headers.get("X-WP-TotalPages", "1"))
        total_posts = int(headers.get("X-WP-Total", len(data)) or len(data))
        for p in data:
            result = upsert_wp_post(p, download_images=download_images)
            db.session.commit()
            processed += 1
            if progress_callback:
                progress_callback(processed=processed, total=total_posts, page=page, total_pages=total_pages, result=result)
        if page >= total_pages: break
        page += 1
    return processed


def localize_existing_wp_images(limit: int | None = None) -> dict:
    posts_query = Post.query.filter(Post.source == "wp").order_by(Post.published_at.desc(), Post.id.desc())
    posts = posts_query.limit(limit).all() if limit else posts_query.all()
    updated = featured_downloaded = content_updated = 0
    for post in posts:
        changed = False
        if post.featured_image and not post.featured_image.startswith("/media/"):
            try:
                post.featured_image = download_external_image(post.featured_image, folder="wp/featured") or post.featured_image
                featured_downloaded += 1; changed = True
            except Exception: pass
        if post.content_html and "<img" in post.content_html.lower():
            localized = localize_content_images(post.content_html)
            if localized != post.content_html:
                post.content_html = localized; content_updated += 1; changed = True
        if changed: updated += 1
    db.session.commit()
    return {"updated_posts": updated, "featured_downloaded": featured_downloaded, "content_updated": content_updated}
