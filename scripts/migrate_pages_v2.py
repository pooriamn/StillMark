from __future__ import annotations

from pathlib import Path

try:
    from helpers_content import available_page_keys, load_page_model, load_page_payload, save_page_payload
    from page_blocks import page_model_to_payload
except ImportError:  # pragma: no cover
    from scripts.helpers_content import available_page_keys, load_page_model, load_page_payload, save_page_payload  # type: ignore
    from scripts.page_blocks import page_model_to_payload  # type: ignore


def migrate_page(page_key: str, *, dry_run: bool = True) -> dict[str, str]:
    model = load_page_model(page_key)
    payload = page_model_to_payload(model, load_page_payload(page_key))
    if not dry_run:
        save_page_payload(page_key, payload)
    return {'page': page_key, 'status': 'dry-run' if dry_run else 'written'}


def migrate_all_pages(*, dry_run: bool = True) -> list[dict[str, str]]:
    return [migrate_page(page_key, dry_run=dry_run) for page_key in available_page_keys()]


def main() -> None:
    for row in migrate_all_pages(dry_run=True):
        print(f"{row['page']}: {row['status']}")


if __name__ == '__main__':
    main()
