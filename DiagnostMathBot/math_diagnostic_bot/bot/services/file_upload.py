import hashlib
import logging
from pathlib import Path

import aiosqlite
from aiogram import Bot
from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)


class FileUploadService:
    """Download HTTP URLs and local files → upload to Telegram → cache file_ids.

    resolve(url):
      - local path  → Telegram file_id (from file_cache)
      - http URL    → Telegram file_id (from url_cache, if downloaded) or original URL
      - None        → None
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}      # local_path → file_id
        self._url_cache: dict[str, str] = {}  # original_url → file_id
        self._db_path: Path | None = None
        self._data_dir: Path | None = None
        self._bot: Bot | None = None
        self._admin_chat_id: int | None = None

    async def init(self, bot: Bot, db_path: Path, admin_chat_id: int) -> None:
        self._bot = bot
        self._db_path = db_path
        self._admin_chat_id = admin_chat_id
        self._data_dir = db_path.parent / "downloads"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        await self._load_cache_from_db()

    # ──────────────────────────────────────────────
    # Public upload API (local files)
    # ──────────────────────────────────────────────

    async def upload_paths(self, paths: list[str]) -> int:
        """Upload local paths not yet cached. Returns count newly uploaded."""
        uploaded = 0
        for path in paths:
            if not path or path.startswith("http"):
                continue
            if path in self._cache:
                continue
            if await self._upload_one(path):
                uploaded += 1
        return uploaded

    async def re_upload_paths(self, paths: list[str]) -> int:
        """Force re-upload local paths. Returns count uploaded."""
        uploaded = 0
        for path in paths:
            if not path or path.startswith("http"):
                continue
            if await self._upload_one(path):
                uploaded += 1
        return uploaded

    # ──────────────────────────────────────────────
    # Public download+upload API (HTTP URLs)
    # ──────────────────────────────────────────────

    async def download_and_upload_urls(self, urls: list[str]) -> int:
        """Download HTTP URLs to local files, upload to Telegram (skip if already cached).
        Returns count successfully processed."""
        return await self._process_urls(urls, force=False)

    async def re_download_and_upload_urls(self, urls: list[str]) -> int:
        """Force re-download + re-upload HTTP URLs. Returns count processed."""
        return await self._process_urls(urls, force=True)

    async def _process_urls(self, urls: list[str], force: bool) -> int:
        count = 0
        seen: set[str] = set()
        for url in urls:
            if not url or not url.startswith("http"):
                continue
            if url in seen:
                continue
            seen.add(url)
            if not force and url in self._url_cache:
                continue
            local_path = await self._download_url_to_file(url)
            if not local_path:
                logger.warning("Failed to download URL: %s", url)
                continue
            if await self._upload_one(local_path):
                file_id = self._cache.get(local_path)
                if file_id:
                    self._url_cache[url] = file_id
                    await self._save_url_to_db(url, file_id)
                    count += 1
        return count

    # ──────────────────────────────────────────────
    # Resolve
    # ──────────────────────────────────────────────

    def resolve(self, url: str | None) -> str | None:
        """Return Telegram file_id if cached, else original URL/path."""
        if not url:
            return None
        if url.startswith("http"):
            return self._url_cache.get(url, url)
        return self._cache.get(url, url)

    # ──────────────────────────────────────────────
    # Download helpers
    # ──────────────────────────────────────────────

    async def _resolve_yandex_disk(self, url: str) -> str | None:
        import aiohttp
        api = f"https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={url}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("href")
                    logger.warning("Yandex Disk API HTTP %d url=%s", resp.status, url)
        except Exception as e:
            logger.warning("Yandex Disk resolve failed url=%s: %s", url, e)
        return None

    async def _download_url_to_file(self, url: str) -> str | None:
        import aiohttp

        download_url = url
        if "disk.yandex.ru" in url or "yadi.sk" in url:
            resolved = await self._resolve_yandex_disk(url)
            if resolved:
                logger.info("Yandex Disk resolved: %s → %s…", url[:50], resolved[:50])
                download_url = resolved
            else:
                logger.warning("Could not resolve Yandex Disk URL, trying original: %s", url)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    download_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        logger.warning("HTTP %d downloading url=%s", resp.status, download_url)
                        return None
                    content_type = resp.headers.get("Content-Type", "")
                    if "html" in content_type.lower():
                        logger.warning(
                            "URL returns HTML (not a direct file). Update URL in Notion Config. url=%s", url
                        )
                        return None
                    data = await resp.read()
        except Exception as e:
            logger.warning("Download failed url=%s: %s", url, e)
            return None

        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        raw_name = download_url.split("?")[0].split("/")[-1]
        if raw_name and "." in raw_name:
            ext = raw_name.rsplit(".", 1)[-1].split("&")[0][:10]
            filename = f"{url_hash}.{ext}"
        else:
            filename = f"{url_hash}.pdf"

        local_path = self._data_dir / filename
        local_path.write_bytes(data)
        logger.info("Downloaded %s → %s (%d bytes)", url[:50], local_path.name, len(data))
        return str(local_path)

    # ──────────────────────────────────────────────
    # Upload helpers
    # ──────────────────────────────────────────────

    async def _upload_one(self, local_path: str) -> bool:
        p = Path(local_path)
        if not p.exists():
            logger.warning("File not found for upload: %s", local_path)
            return False
        try:
            msg = await self._bot.send_document(self._admin_chat_id, FSInputFile(str(p)))
            file_id = msg.document.file_id
            self._cache[local_path] = file_id
            await self._save_file_to_db(local_path, file_id)
            logger.info("Uploaded %s → file_id=%s…", local_path, file_id[:12])
            return True
        except Exception as e:
            logger.error("Upload failed %s: %s", local_path, e)
            return False

    # ──────────────────────────────────────────────
    # DB persistence
    # ──────────────────────────────────────────────

    async def _load_cache_from_db(self) -> None:
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT local_path, file_id FROM file_cache") as cur:
                for row in await cur.fetchall():
                    self._cache[row["local_path"]] = row["file_id"]
            async with conn.execute("SELECT url, file_id FROM url_cache") as cur:
                for row in await cur.fetchall():
                    self._url_cache[row["url"]] = row["file_id"]
        logger.info(
            "FileUpload cache loaded: %d local, %d url", len(self._cache), len(self._url_cache)
        )

    async def _save_file_to_db(self, local_path: str, file_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO file_cache (local_path, file_id) VALUES (?, ?)",
                (local_path, file_id),
            )
            await conn.commit()

    async def _save_url_to_db(self, url: str, file_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO url_cache (url, file_id) VALUES (?, ?)",
                (url, file_id),
            )
            await conn.commit()
