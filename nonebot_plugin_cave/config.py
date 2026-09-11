from pathlib import Path

from pydantic import BaseModel, Field


class CaveConfig(BaseModel):
    cave_data_dir: Path = Path("data/cave")
    cave_reviewers: set[str] = Field(default_factory=set, alias="white_b_owner")
    cave_default_cooldown: int = 1
    cave_default_cooldown_unit: str = "sec"
    cave_download_timeout: float = 15.0
    cave_max_image_bytes: int = 10 * 1024 * 1024
