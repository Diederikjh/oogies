#!/usr/bin/env python3
"""Configure native Git LFS while preserving the publication pre-push hook."""
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    available = subprocess.run(["git", "lfs", "version"], cwd=root, capture_output=True)
    if available.returncode:
        raise SystemExit("Install native Git LFS first (Ubuntu/Debian: sudo apt-get install git-lfs).")
    # Force replaces this checkout's old Docker filter commands. Skip-repo
    # prevents LFS from overwriting the committed publication guard hook.
    subprocess.run(["git", "lfs", "install", "--local", "--force", "--skip-repo"], cwd=root, check=True)
    subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=root, check=True)
    print("Repository configured for native Git LFS and publication checks.")


if __name__ == "__main__":
    main()
