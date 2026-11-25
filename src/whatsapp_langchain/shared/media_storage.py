"""Armazenamento da mídia enviada pelo painel para publicação no Instagram.

A Content Publishing API não recebe o arquivo: recebe uma URL pública e a
Meta baixa de lá. Por isso a API guarda o arquivo em MEDIA_STORAGE_DIR e o
serve sem login em `/media/<token>` (ver `server/routes/media_public.py`).
O token é aleatório (192 bits), então a URL não é adivinhável.

Imagens são normalizadas para JPEG (o feed só aceita JPEG), com a rotação
EXIF aplicada. Vídeos são aceitos como MP4/MOV, sem recodificar: a Meta
valida codec e duração e devolve o erro no status do container.
"""

from __future__ import annotations

import io
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from whatsapp_langchain.shared.config import settings

# Imagens maiores que isso no lado maior são reduzidas (a Meta usa até 1440 px).
MAX_IMAGE_SIDE = 1440
JPEG_QUALITY = 90
# Teto da Meta para imagens (depois de convertida para JPEG).
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Teto da imagem original enviada (antes de comprimir).
MAX_RAW_IMAGE_BYTES = 50 * 1024 * 1024
_CHUNK = 1024 * 1024

# Proteção contra "bomba de descompressão" (imagem minúscula em bytes que
# vira gigabytes ao abrir).
Image.MAX_IMAGE_PIXELS = 60_000_000

_VIDEO_TYPES = {"video/mp4": ".mp4", "video/quicktime": ".mov"}


class MediaRejectedError(ValueError):
    """Arquivo que não pode ser publicado (formato, tamanho, corrompido)."""


@dataclass
class StoredMedia:
    token: str
    media_kind: str  # "image" | "video"
    content_type: str
    size_bytes: int
    width: int | None
    height: int | None


def storage_dir() -> Path:
    path = Path(settings.media_storage_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_path(token: str) -> Path | None:
    """Caminho do arquivo de um token, ou None se o token é inválido.

    O token vem da URL pública: só aceita o formato gerado aqui, para não
    permitir `../` ou qualquer caminho fora da pasta.
    """
    stem, _, ext = token.partition(".")
    if not stem or ext not in ("jpg", "mp4", "mov"):
        return None
    if not all(c.isalnum() or c in "-_" for c in stem):
        return None
    path = storage_dir() / token
    return path if path.is_file() else None


def public_url(token: str) -> str:
    """URL por onde a Meta baixa a mídia."""
    return f"{settings.public_base_url.rstrip('/')}/media/{token}"


def public_base_url_problem() -> str | None:
    """Motivo pelo qual a Meta não conseguiria baixar a mídia, ou None."""
    base = settings.public_base_url.strip()
    if not base:
        return (
            "PUBLIC_BASE_URL não configurada: a Meta precisa de uma URL pública "
            "para baixar a mídia (ex: o domínio de produção ou um túnel ngrok)."
        )
    if not base.startswith("https://"):
        return "PUBLIC_BASE_URL precisa começar com https:// (exigência da Meta)."
    if any(host in base for host in ("localhost", "127.0.0.1", "0.0.0.0")):
        return "PUBLIC_BASE_URL aponta para localhost: a Meta não alcança."
    return None


def _new_token(ext: str) -> str:
    return f"{secrets.token_urlsafe(24)}{ext}"


def _is_video(head: bytes) -> bool:
    """MP4/MOV: caixa `ftyp` nos bytes 4-8 (ISO base media file format)."""
    return len(head) >= 12 and head[4:8] == b"ftyp"


def _video_content_type(head: bytes, declared: str | None) -> str:
    brand = head[8:12]
    if brand == b"qt  " or declared == "video/quicktime":
        return "video/quicktime"
    return "video/mp4"


def _normalize_image(data: bytes) -> tuple[bytes, int, int]:
    """Converte para JPEG RGB, aplica rotação EXIF e limita o tamanho."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                # Transparência vira fundo branco (JPEG não tem alfa)
                background = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                background.paste(rgba, mask=rgba.getchannel("A"))
                img = background
            else:
                img = img.convert("RGB")
            img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
            return out.getvalue(), img.width, img.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise MediaRejectedError("Imagem inválida ou corrompida.") from exc


def store_media(stream: BinaryIO, declared_type: str | None) -> StoredMedia:
    """Valida e grava a mídia. Devolve os metadados para o banco.

    Vídeo é copiado em blocos direto para o disco (pode ter centenas de MB);
    só imagem é lida inteira na memória, para converter.

    Raises:
        MediaRejectedError: Formato não suportado, vazio ou grande demais.
    """
    max_bytes = settings.media_max_upload_mb * 1024 * 1024
    head = stream.read(12)
    if not head:
        raise MediaRejectedError("Arquivo vazio.")

    if _is_video(head):
        content_type = _video_content_type(head, declared_type)
        token = _new_token(_VIDEO_TYPES[content_type])
        path = storage_dir() / token
        size = len(head)
        try:
            with path.open("wb") as out:
                out.write(head)
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise MediaRejectedError(
                            f"Arquivo passa de {settings.media_max_upload_mb} MB."
                        )
                    out.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return StoredMedia(token, "video", content_type, size, None, None)

    data = head + stream.read(MAX_RAW_IMAGE_BYTES)
    if stream.read(1):
        raise MediaRejectedError(
            "Imagem grande demais (máximo 50 MB antes de comprimir)."
        )

    jpeg, width, height = _normalize_image(data)
    if len(jpeg) > MAX_IMAGE_BYTES:
        raise MediaRejectedError("Imagem passa de 8 MB mesmo depois de comprimida.")
    token = _new_token(".jpg")
    (storage_dir() / token).write_bytes(jpeg)
    return StoredMedia(token, "image", "image/jpeg", len(jpeg), width, height)


def delete_media_file(token: str) -> None:
    path = media_path(token)
    if path is not None:
        path.unlink(missing_ok=True)


def read_media(token: str) -> bytes | None:
    path = media_path(token)
    return path.read_bytes() if path else None
