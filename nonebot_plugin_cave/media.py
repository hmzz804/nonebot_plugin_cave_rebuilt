import mimetypes
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


class MediaStore:
    def __init__(self, image_dir: Path, timeout: float, max_bytes: int) -> None:
        self.image_dir = image_dir
        self.timeout = timeout
        self.max_bytes = max_bytes

    async def persist(self, message: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stored: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for segment in message:
                if segment.get("type") != "image":
                    stored.append(segment)
                    continue
                url = segment.get("data", {}).get("url")
                if not url:
                    continue
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
                if len(content) > self.max_bytes:
                    raise ValueError("图片超过大小限制。")
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                extension = mimetypes.guess_extension(content_type) or ".img"
                path = self.image_dir / f"{uuid4().hex}{extension}"
                path.write_bytes(content)
                stored.append({"type": "image", "data": {"file": str(path)}})
        return stored

    @staticmethod
    def delete_files(message: list[dict[str, Any]]) -> None:
        for segment in message:
            if segment.get("type") == "image":
                file = segment.get("data", {}).get("file") or segment.get("path")
                if file:
                    Path(file).unlink(missing_ok=True)

