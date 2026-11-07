"""Safely rebuild the FAISS index from active completed document chunks."""

import argparse
import os
from pathlib import Path
import json

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
os.environ.setdefault("VECTOR_STORE_DISABLE_GLOBAL_INIT", "1")

from core.config import config
from core.mysql_client import mysql_client
from core.reindex import rebuild_from_mysql
from core.vector_store import create_embeddings


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild the VigilDocs FAISS index. The command is a dry-run "
            "unless --apply is provided."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="validate and atomically activate the rebuilt index",
    )
    parser.add_argument(
        "--index-dir",
        default=config.VECTOR_STORE_PERSIST_DIR,
        help="target FAISS index directory",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    embeddings, provider, model = create_embeddings()
    report = rebuild_from_mysql(
        mysql_client,
        embeddings=embeddings,
        target_dir=Path(args.index_dir),
        apply=args.apply,
        embedding_provider=provider,
        embedding_model=model,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
