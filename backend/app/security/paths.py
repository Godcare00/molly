from pathlib import Path
import os


def canonicalize_path(path: str) -> Path:
    """Canonicalize a path: expand user, resolve symlinks, make absolute."""
    expanded = os.path.expanduser(path)
    path_obj = Path(expanded)
    return path_obj.resolve(strict=False)


def validate_path_safety(path: Path) -> None:
    """
    Validate path safety.
    These are correctness protections, not a project sandbox.
    """
    path_str = str(path)

    # Prevent null bytes
    if "\x00" in path_str:
        raise ValueError("Path contains null bytes")

    # Prevent path traversal attempts that would escape
    # Note: We allow absolute paths anywhere on the server
    # This is just basic sanity checking
    if path_str != os.path.normpath(path_str):
        raise ValueError("Path contains traversal sequences")

    # Ensure it's an absolute path after resolution
    if not path.is_absolute():
        raise ValueError("Path must be absolute")


def is_within(path: Path, parent: Path) -> bool:
    """Check if path is within parent directory."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def get_safe_temp_path(base: Path, prefix: str = "molly_") -> Path:
    """Generate a safe temporary path within a base directory."""
    import tempfile
    import uuid

    base.mkdir(parents=True, exist_ok=True)
    unique_name = f"{prefix}{uuid.uuid4().hex[:8]}"
    return base / unique_name