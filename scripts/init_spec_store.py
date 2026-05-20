"""Initialize spec store SQLite database."""

import argparse

from scraper.ats.spec_store import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the spec store database")
    parser.add_argument("--db-path", default=None, help="Optional SQLite file path")
    args = parser.parse_args()
    init_db(args.db_path)
    print("Spec store initialized")


if __name__ == "__main__":
    main()
