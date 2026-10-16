"""Stable live source names; overview names preserve the existing diagnostics."""


def source_key(camera_id, quality="overview"):
    if quality not in ("overview", "high"):
        raise ValueError("Unknown live quality")
    return camera_id if quality == "overview" else camera_id + "-high"


def source_identity(key):
    return (key[:-5], "high") if key.endswith("-high") else (key, "overview")
