from __future__ import annotations

import argparse

from .config import Settings, get_settings
from .database import Database
from .services.knowledge_base import KnowledgeBaseService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the MPS Assistant knowledge base.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh_parser = subparsers.add_parser("refresh", help="Crawl and refresh the official MPS website.")
    refresh_parser.add_argument("--max-pages", type=int, default=None, help="Override the crawl page limit for this run.")

    walkthrough_parser = subparsers.add_parser(
        "harvest-application",
        help="Run a safe dummy walkthrough of a supported application entry page and store the observed schema.",
    )
    walkthrough_parser.add_argument("url", help="Application URL to inspect, for example https://apply.medicalprotection.org/20")

    subparsers.add_parser("status", help="Show knowledge base status.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = get_settings()
    if args.command == "refresh" and args.max_pages:
        settings = Settings(
            openai_api_key=settings.openai_api_key,
            openai_model=settings.openai_model,
            openai_fallback_models=settings.openai_fallback_models,
            embedding_model=settings.embedding_model,
            refresh_interval_hours=settings.refresh_interval_hours,
            enable_scheduler=settings.enable_scheduler,
            auto_refresh_on_startup=settings.auto_refresh_on_startup,
            sqlite_journal_mode=settings.sqlite_journal_mode,
            crawl_max_pages=args.max_pages,
            crawl_timeout_seconds=settings.crawl_timeout_seconds,
            render_timeout_seconds=settings.render_timeout_seconds,
            user_agent=settings.user_agent,
            chrome_binary_path=settings.chrome_binary_path,
            retrieval_top_k=settings.retrieval_top_k,
            lexical_top_k=settings.lexical_top_k,
            semantic_top_k=settings.semantic_top_k,
            max_chunk_chars=settings.max_chunk_chars,
            chunk_overlap_chars=settings.chunk_overlap_chars,
            seed_url=settings.seed_url,
            allowed_domain=settings.allowed_domain,
            data_dir=settings.data_dir,
            database_path=settings.database_path,
            raw_download_dir=settings.raw_download_dir,
            upload_dir=settings.upload_dir,
            resource_extensions=settings.resource_extensions,
            crawl_start_urls=settings.crawl_start_urls,
            rendered_application_hosts=settings.rendered_application_hosts,
        )
        settings.ensure_directories()

    database = Database(settings.database_path, journal_mode=settings.sqlite_journal_mode)
    kb = KnowledgeBaseService(settings, database)
    kb.initialize()

    if args.command == "refresh":
        kb.refresh_site_now()
        print(kb.status())
    elif args.command == "harvest-application":
        source_keys = kb.harvest_application_walkthrough(args.url)
        print({"ingested_source_keys": source_keys, "count": len(source_keys)})
    elif args.command == "status":
        print(kb.status())


if __name__ == "__main__":
    main()
