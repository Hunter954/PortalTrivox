from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests
from flask import current_app, url_for

from .models import Post, SiteSetting, db


@dataclass
class WhatsAppResult:
    ok: bool
    message: str
    data: dict[str, Any] | None = None


def _setting(key: str, default: str = "") -> str:
    item = SiteSetting.query.filter_by(key=key).first()
    return item.value if item and item.value is not None else default


def _save_setting(key: str, value: str) -> None:
    item = SiteSetting.query.filter_by(key=key).first()
    if item is None:
        item = SiteSetting(key=key, value=value)
        db.session.add(item)
    else:
        item.value = value


def _setting_json(key: str, default):
    raw = (_setting(key, "") or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _strip_html(value: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", text).strip()


def _summary(post: Post, max_len: int = 500) -> str:
    text = _strip_html(post.excerpt) or _strip_html(post.content_html)
    if len(text) > max_len:
        text = text[: max_len - 1].rsplit(" ", 1)[0].strip() + "…"
    return text


def _absolute_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    try:
        return url_for("site.home", _external=True).rstrip("/") + "/" + value.lstrip("/")
    except Exception:
        base = (current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        return f"{base}/{value.lstrip('/')}" if base else value


def public_post_url(post: Post) -> str:
    try:
        return url_for("site.post", slug=post.slug, _external=True)
    except Exception:
        base = (current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        return f"{base}/p/{post.slug}" if base else f"/p/{post.slug}"


def whatsapp_config() -> dict[str, Any]:
    return {
        "enabled": bool(current_app.config.get("WHATSAPP_AUTO_SEND_ENABLED", True)),
        "service_url": (current_app.config.get("WHATSAPP_SERVICE_URL") or "").strip().rstrip("/"),
        "service_token": (current_app.config.get("WHATSAPP_SERVICE_TOKEN") or "").strip(),
        "group_id": (current_app.config.get("WHATSAPP_TRIVOX_GROUP_ID") or "").strip(),
        "timeout": int(current_app.config.get("WHATSAPP_SERVICE_TIMEOUT", 30)),
    }


def _sent_ids() -> list[int]:
    raw = _setting_json("whatsapp_trivox_sent_post_ids_json", [])
    result: list[int] = []
    if isinstance(raw, list):
        for item in raw:
            try:
                result.append(int(item))
            except Exception:
                continue
    return result


def _was_sent(post_id: int) -> bool:
    return int(post_id) in set(_sent_ids())


def _mark_sent(post_id: int) -> None:
    ids = _sent_ids()
    post_id = int(post_id)
    if post_id not in ids:
        ids.append(post_id)
        ids = ids[-1000:]
        _save_setting("whatsapp_trivox_sent_post_ids_json", json.dumps(ids))
        _save_setting("whatsapp_trivox_last_send_at", datetime.utcnow().isoformat())
        db.session.commit()


def send_post_to_whatsapp(post: Post) -> WhatsAppResult:
    cfg = whatsapp_config()
    if not cfg["enabled"]:
        return WhatsAppResult(True, "Automação WhatsApp desativada.")
    if not cfg["service_url"]:
        return WhatsAppResult(False, "WHATSAPP_SERVICE_URL não configurada no Portal Trivox.")
    if not cfg["group_id"]:
        return WhatsAppResult(False, "WHATSAPP_TRIVOX_GROUP_ID não configurado no Portal Trivox.")
    if not post.featured_image:
        return WhatsAppResult(False, "A matéria não possui imagem destacada para enviar ao WhatsApp.")

    title = (post.title or "Nova matéria").strip()
    summary = _summary(post)
    post_url = public_post_url(post)
    image_url = _absolute_url(post.featured_image or "")
    category = post.categories[0].name if post.categories else ""

    caption_parts = ["📰 Nova matéria publicada no Portal Trivox", "", title]
    if category:
        caption_parts.extend(["", f"{category}"])
    if summary:
        caption_parts.extend(["", summary])
    caption_parts.extend(["", f"Leia agora: {post_url}"])
    caption = "\n".join(caption_parts).strip()

    payload = {
        "group_id": cfg["group_id"],
        "portal_name": "Portal Trivox",
        "post": {
            "id": post.id,
            "title": title,
            "summary": summary,
            "url": post_url,
            "category": category,
            "published_at": post.published_at.isoformat() if post.published_at else "",
        },
        "images": [
            {
                "type": "featured",
                "label": "Imagem da matéria",
                "url": image_url,
            }
        ],
        "generate_standard_art": True,
        "art_brand": "trivox",
        "art_only_feed": True,
        "whatsapp_caption": caption,
        "send_text": False,
    }

    headers = {"Content-Type": "application/json"}
    if cfg["service_token"]:
        headers["X-Service-Token"] = cfg["service_token"]

    try:
        response = requests.post(
            f"{cfg['service_url']}/send-news",
            json=payload,
            headers=headers,
            timeout=max(5, cfg["timeout"]),
        )
        try:
            data = response.json() if response.content else {}
        except Exception:
            data = {"raw": response.text[:500]}
        if response.ok:
            return WhatsAppResult(True, data.get("message") or "Imagem enviada ao WhatsApp.", data)
        return WhatsAppResult(
            False,
            data.get("message") or data.get("error") or f"Erro HTTP {response.status_code} no serviço WhatsApp.",
            data,
        )
    except requests.RequestException as exc:
        return WhatsAppResult(False, f"Falha ao conectar no serviço WhatsApp: {exc}")


def auto_send_post_to_whatsapp(post: Post) -> WhatsAppResult:
    cfg = whatsapp_config()
    if not cfg["enabled"]:
        return WhatsAppResult(True, "Automação WhatsApp desativada.")
    if not post.published_at or post.published_at > datetime.now():
        return WhatsAppResult(True, "Matéria ainda não está publicada.")
    if _was_sent(post.id):
        return WhatsAppResult(True, "Matéria já enviada anteriormente.")

    result = send_post_to_whatsapp(post)
    if result.ok:
        _mark_sent(post.id)
    return result
