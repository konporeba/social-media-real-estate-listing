from pathlib import Path

from db.client import get_client

_PROMPTS_DIR = Path(__file__).parent

_SEEDS = [
    {"name": "content", "version": "v1", "file": "content_v1.md"},
]


def load_active_prompt(name: str) -> tuple[str, str]:
    """Return (content, version) for the active prompt by name."""
    client = get_client()
    row = (
        client.table("prompts")
        .select("content, version")
        .eq("name", name)
        .eq("is_active", True)
        .single()
        .execute()
    )
    return row.data["content"], row.data["version"]


def seed_prompts_if_empty() -> None:
    """Insert seed prompts from disk on first startup if the table is empty."""
    client = get_client()
    existing = client.table("prompts").select("id", count="exact").limit(1).execute()
    if existing.count:
        return
    for seed in _SEEDS:
        content = (_PROMPTS_DIR / seed["file"]).read_text(encoding="utf-8")
        client.table("prompts").insert(
            {
                "name": seed["name"],
                "version": seed["version"],
                "content": content,
                "is_active": True,
            }
        ).execute()
