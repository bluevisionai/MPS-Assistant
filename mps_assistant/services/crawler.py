from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse, urlunparse

import requests

from ..config import Settings
from ..schemas import ExtractedDocument
from .application_metadata import build_application_metadata_documents
from .extractors import extract_file_document, extract_html_document
from .browser_renderer import BrowserRenderer


class SiteCrawler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent})

    def crawl(self) -> Dict[str, List[ExtractedDocument]]:
        timestamp = datetime.now(timezone.utc).isoformat()
        html_documents: List[ExtractedDocument] = []
        resource_documents: List[ExtractedDocument] = []

        queue = deque(self.settings.crawl_start_urls)
        seen_html: Set[str] = set()
        seen_resource: Set[str] = set()

        with BrowserRenderer(self.settings) as renderer:
            while queue and len(seen_html) < self.settings.crawl_max_pages:
                url = queue.popleft()
                normalized = normalize_url(url)
                if normalized in seen_html:
                    continue
                seen_html.add(normalized)

                document_links = self._extract_html_documents(normalized, timestamp, renderer)
                if document_links is None:
                    continue

                documents, links = document_links
                for document in documents:
                    if document.sections:
                        html_documents.append(document)

                for href in links:
                    next_url = normalize_url(urljoin(normalized, href))
                    if not next_url:
                        continue
                    if is_allowed_html_url(next_url, self.settings):
                        if next_url not in seen_html:
                            queue.append(next_url)
                    elif is_allowed_resource_url(next_url, self.settings):
                        if next_url not in seen_resource:
                            seen_resource.add(next_url)

        for resource_url in sorted(seen_resource):
            response = self._safe_get(resource_url, stream=True)
            if response is None:
                continue
            file_path = self._store_resource_file(resource_url, response.content)
            response.close()
            try:
                document = extract_file_document(
                    source_key=resource_url,
                    origin="website",
                    path=file_path,
                    downloaded_at=timestamp,
                    url=resource_url,
                    content_type=response.headers.get("Content-Type"),
                )
            except Exception:
                continue
            if document.sections:
                resource_documents.append(document)

        return {"website_documents": html_documents + resource_documents, "seen_source_keys": [doc.source_key for doc in html_documents + resource_documents]}

    def _extract_html_documents(
        self,
        url: str,
        timestamp: str,
        renderer: BrowserRenderer,
    ) -> Optional[tuple]:
        if should_render_html_url(url, self.settings):
            try:
                rendered = renderer.render(url)
            except Exception:
                return None
            document, links = extract_html_document(
                rendered.final_url,
                rendered.html,
                timestamp,
                page_title_override=rendered.title,
                document_title_override=rendered.visible_title,
                source_format="rendered-html",
            )
            documents = [document]
            documents.extend(
                build_application_metadata_documents(
                    rendered_page=rendered,
                    downloaded_at=timestamp,
                    settings=self.settings,
                    session=self.session,
                )
            )
            return documents, links

        response = self._safe_get(url)
        if response is None or not _is_html_response(response):
            return None
        document, links = extract_html_document(url, response.text, timestamp)
        return [document], links

    def _safe_get(self, url: str, stream: bool = False) -> Optional[requests.Response]:
        try:
            response = self.session.get(url, timeout=self.settings.crawl_timeout_seconds, stream=stream)
            response.raise_for_status()
            return response
        except requests.RequestException:
            return None

    def _store_resource_file(self, url: str, content: bytes) -> Path:
        parsed = urlparse(url)
        name = Path(parsed.path).name or "downloaded-resource"
        target = self.settings.raw_download_dir / name
        suffix = target.suffix
        stem = target.stem
        counter = 1
        while target.exists() and target.read_bytes() != content:
            target = self.settings.raw_download_dir / f"{stem}-{counter}{suffix}"
            counter += 1
        target.write_bytes(content)
        return target


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    cleaned = parsed._replace(fragment="")
    if cleaned.query.startswith("utm_"):
        cleaned = cleaned._replace(query="")
    if cleaned.path.endswith("/"):
        cleaned = cleaned._replace(path=cleaned.path.rstrip("/"))
    return urlunparse(cleaned)


def is_allowed_html_url(url: str, settings: Settings) -> bool:
    parsed = urlparse(url)
    if parsed.netloc in settings.rendered_application_hosts:
        return bool(parsed.path and parsed.path != "/")
    if not parsed.netloc.endswith(settings.allowed_domain):
        return False
    if parsed.netloc != "www.medicalprotection.org":
        return False
    return parsed.path.startswith("/southafrica")


def is_allowed_resource_url(url: str, settings: Settings) -> bool:
    parsed = urlparse(url)
    if not parsed.netloc.endswith(settings.allowed_domain):
        return False
    path = parsed.path.lower()
    disallowed_region_tokens = [
        "/hongkong/",
        "/hk/",
        "/ireland/",
        "/malaysia/",
        "/newzealand/",
        "/singapore/",
        "/caribbean-and-bermuda/",
        "/world/",
        "/uk/",
    ]
    if any(token in path for token in disallowed_region_tokens):
        return False
    return any(path.endswith(extension) for extension in settings.resource_extensions)


def _is_html_response(response: requests.Response) -> bool:
    content_type = (response.headers.get("Content-Type") or "").lower()
    return "text/html" in content_type or "application/xhtml" in content_type


def should_render_html_url(url: str, settings: Settings) -> bool:
    parsed = urlparse(url)
    return parsed.netloc in settings.rendered_application_hosts
