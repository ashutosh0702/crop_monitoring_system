"""
Small shared utilities used across API response formatting.
"""

import base64
from pathlib import Path
from typing import Optional


def file_to_data_url(file_path: Optional[str], media_type: str) -> Optional[str]:
    """Convert a local file path to a data URL for direct browser display."""
    if not file_path:
        return None

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None

    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None

    return f"data:{media_type};base64,{encoded}"
