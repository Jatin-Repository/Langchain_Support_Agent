"""Shared paths, independent of the process working directory."""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

def checkpoint_path():
    path = Path(os.getenv("CHECKPOINTS_DB_PATH", "checkpoints.sqlite"))
    return path if path.is_absolute() else PROJECT_ROOT / path
