from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from flask import current_app
from PIL import Image, ImageDraw, ImageFilter

from .art_generator import _asset_path, _load_font, _normalize_text, _text_bbox
from .storage import key_from_media_url, save_bytes


class VideoGeneratorError(Exception):
    pass


TRIVOX_REELS_SIZE = (1080, 1920)
TRIVOX_TEMPLATE_ASSET = "trivox-video-overlay.png"

# Sombra baseada no padrão enviado do Photoshop:
# preto, 83%, ângulo 90°, distância 7 px, expansão 7% e tamanho 13 px.
SHADOW_OPACITY = 0.83
SHADOW_DISTANCE = 7
SHADOW_SPREAD_PERCENT = 7
SHADOW_SIZE = 13


def _media_binary(config_key: str, default: str) -> str:
    configured = (current_app.config.get(config_key) or default).strip()
    resolved = shutil.which(configured)
    if not resolved:
        raise VideoGeneratorError(f"{default} não está instalado no ambiente de processamento.")
    return resolved


def _ffmpeg_binary() -> str:
    return _media_binary("FFMPEG_BINARY", "ffmpeg")


def _probe_video(input_path: Path) -> dict[str, float | int]:
    ffprobe = _media_binary("FFPROBE_BINARY", "ffprobe")
    command = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "json",
        str(input_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if completed.returncode != 0:
        detail = (completed.stderr or "erro desconhecido").strip()[-500:]
        raise VideoGeneratorError(f"Não foi possível analisar o vídeo: {detail}")

    try:
        payload = json.loads(completed.stdout or "{}")
        stream = (payload.get("streams") or [{}])[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VideoGeneratorError("Não foi possível interpretar as informações do vídeo.") from exc

    if duration <= 0 or width <= 0 or height <= 0:
        raise VideoGeneratorError("O vídeo recebido possui informações inválidas.")
    return {"duration": duration, "width": width, "height": height}


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    words = _normalize_text(text).split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        left, _top, right, _bottom = _text_bbox(font, candidate)
        if right - left <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_title(text: str, *, max_width: int, max_lines: int = 4):
    clean = _normalize_text(text)
    if not clean:
        return _load_font(36), []

    for size in range(70, 35, -2):
        font = _load_font(size)
        lines = _wrap_text(clean, font, max_width)
        if 0 < len(lines) <= max_lines:
            return font, lines

    font = _load_font(36)
    lines = _wrap_text(clean, font, max_width)
    if len(lines) <= max_lines:
        return font, lines

    # Se ainda passar de quatro linhas, reduz preservando palavras inteiras
    # e adiciona reticências na última linha.
    words = clean.split()
    trimmed: list[str] = []
    idx = 0
    for _ in range(max_lines):
        if idx >= len(words):
            break
        current = words[idx]
        idx += 1
        while idx < len(words):
            candidate = f"{current} {words[idx]}"
            left, _top, right, _bottom = _text_bbox(font, candidate)
            if right - left <= max_width:
                current = candidate
                idx += 1
            else:
                break
        trimmed.append(current)

    if idx < len(words) and trimmed:
        last = trimmed[-1]
        while last:
            candidate = last.rstrip(" .,;:") + "..."
            left, _top, right, _bottom = _text_bbox(font, candidate)
            if right - left <= max_width:
                trimmed[-1] = candidate
                break
            last = " ".join(last.split()[:-1]).strip()
    return font, trimmed


def _load_reels_template() -> Image.Image:
    width, height = TRIVOX_REELS_SIZE
    template_path = _asset_path(TRIVOX_TEMPLATE_ASSET)
    if not template_path.exists():
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))

    with Image.open(template_path) as source:
        template = source.convert("RGBA")
    if template.size != (width, height):
        template = template.resize((width, height), Image.Resampling.LANCZOS)
    return template


def _offset_mask(mask: Image.Image, dx: int, dy: int) -> Image.Image:
    shifted = Image.new("L", mask.size, 0)
    shifted.paste(mask, (dx, dy))
    return shifted


def _draw_shadowed_title(canvas: Image.Image, title: str) -> None:
    width, height = canvas.size
    max_width = width - 128
    font, lines = _fit_title(title, max_width=max_width, max_lines=4)
    if not lines:
        return

    line_gap = max(10, int(font.size * 0.20))
    metrics: list[tuple[int, int, int, int, int, int]] = []
    total_height = 0
    for line in lines:
        left, top, right, bottom = _text_bbox(font, line)
        line_width = right - left
        line_height = bottom - top
        metrics.append((left, top, right, bottom, line_width, line_height))
        total_height += line_height
    total_height += line_gap * (len(lines) - 1)

    x = 64
    # Reserva a faixa inferior onde ficam legenda/botões do Reels.
    block_bottom = height - 300
    y = max(300, block_bottom - total_height)

    text_mask = Image.new("L", (width, height), 0)
    draw_mask = ImageDraw.Draw(text_mask)
    current_y = y
    for line, metric in zip(lines, metrics):
        left, top, _right, _bottom, _line_width, line_height = metric
        draw_mask.text((x - left, current_y - top), line, font=font, fill=255)
        current_y += line_height + line_gap

    # Expansão 7% sobre tamanho 13 px -> ~1 px de spread antes do blur.
    spread_px = max(1, round(SHADOW_SIZE * SHADOW_SPREAD_PERCENT / 100))
    spread_filter_size = spread_px * 2 + 1
    shadow_mask = text_mask.filter(ImageFilter.MaxFilter(spread_filter_size))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(radius=SHADOW_SIZE / 2))
    shadow_mask = _offset_mask(shadow_mask, 0, SHADOW_DISTANCE)
    shadow_mask = shadow_mask.point(lambda p: int(p * SHADOW_OPACITY))

    shadow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_layer.putalpha(shadow_mask)
    canvas.alpha_composite(shadow_layer)

    text_layer = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    text_layer.putalpha(text_mask)
    canvas.alpha_composite(text_layer)


def generate_trivox_reels_overlay(title: str) -> Image.Image:
    """Overlay 1080x1920: template enviado + título branco com sombra preta."""
    canvas = _load_reels_template()
    _draw_shadowed_title(canvas, title)
    return canvas


def _render_video_with_overlay(
    *,
    input_path: Path,
    output_path: Path,
    overlay_path: Path,
    output_duration: float,
) -> None:
    ffmpeg = _ffmpeg_binary()
    width, height = TRIVOX_REELS_SIZE
    filter_complex = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1[base];"
        "[base][1:v]overlay=0:0:format=auto:shortest=1:eof_action=endall[v]"
    )
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(input_path),
        "-loop", "1",
        "-i", str(overlay_path),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a?",
        "-t", f"{output_duration:.3f}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(120, int(output_duration * 3)),
        )
    except subprocess.TimeoutExpired as exc:
        raise VideoGeneratorError("O processamento do vídeo excedeu o tempo permitido.") from exc

    if completed.returncode != 0 or not output_path.exists():
        detail = (completed.stderr or "erro desconhecido").strip()[-700:]
        raise VideoGeneratorError(f"Falha no FFmpeg: {detail}")


def generate_trivox_reels_video(
    *, video_content: bytes, title: str, filename_hint: str = "video.mp4"
) -> dict[str, str]:
    if not video_content:
        raise VideoGeneratorError("O vídeo recebido está vazio.")
    if not _normalize_text(title):
        raise VideoGeneratorError("O título é obrigatório.")

    max_seconds = int(current_app.config.get("VIDEO_MAX_SECONDS", 180))

    with tempfile.TemporaryDirectory(prefix="trivox-reels-") as tmp:
        tmp_dir = Path(tmp)
        input_ext = Path(filename_hint or "video.mp4").suffix.lower()
        if input_ext not in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
            input_ext = ".mp4"

        input_path = tmp_dir / f"input{input_ext}"
        overlay_path = tmp_dir / "overlay.png"
        output_path = tmp_dir / "trivox-reels.mp4"
        input_path.write_bytes(video_content)

        info = _probe_video(input_path)
        output_duration = min(float(info["duration"]), float(max_seconds))
        generate_trivox_reels_overlay(title).save(overlay_path, "PNG")
        _render_video_with_overlay(
            input_path=input_path,
            output_path=output_path,
            overlay_path=overlay_path,
            output_duration=output_duration,
        )
        output = output_path.read_bytes()

    filename = f"trivox-reels-{uuid.uuid4().hex}.mp4"
    url = save_bytes(
        output,
        folder="gerador/video-generated",
        filename_hint=filename,
        content_type="video/mp4",
    )
    return {
        "key": "reels",
        "label": "Vídeo Reels",
        "size": "1080x1920",
        "url": url,
        "download_key": key_from_media_url(url) or f"gerador/video-generated/{filename}",
        "download_name": filename,
        "mimetype": "video/mp4",
    }
