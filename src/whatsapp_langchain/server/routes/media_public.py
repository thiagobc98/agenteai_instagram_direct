"""Serve a mídia das publicações para a Meta baixar (sem login).

A Content Publishing API recebe `image_url`/`video_url` e baixa o arquivo
de lá. O token no caminho é aleatório (192 bits) e validado contra o formato
gerado em `shared/media_storage.py`, então não dá para listar nem sair da
pasta. Suporta HEAD e Range (FileResponse do Starlette), usados pela Meta
para vídeo.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from whatsapp_langchain.shared.media_storage import media_path

router = APIRouter(tags=["media"])

_CONTENT_TYPES = {"jpg": "image/jpeg", "mp4": "video/mp4", "mov": "video/quicktime"}


@router.api_route("/media/{token}", methods=["GET", "HEAD"])
async def get_media(token: str) -> FileResponse:
    path = media_path(token)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(
        path,
        media_type=_CONTENT_TYPES[token.rsplit(".", 1)[1]],
        headers={
            "Cache-Control": "public, max-age=86400, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
