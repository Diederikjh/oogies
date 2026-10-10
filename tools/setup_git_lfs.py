#!/usr/bin/env python3
"""Configure this repository to use Docker for Git LFS; no host install."""
from pathlib import Path
import shlex
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    wrapper = shlex.quote(str(root / "tools/git_lfs_docker.sh"))
    settings = {
        "filter.lfs.clean": f"{wrapper} clean -- %f",
        "filter.lfs.smudge": f"{wrapper} smudge -- %f",
        "filter.lfs.process": f"{wrapper} filter-process",
        "filter.lfs.required": "true",
        "core.hooksPath": ".githooks",
    }
    for key, value in settings.items():
        subprocess.run(["git", "config", "--local", key, value], cwd=root, check=True)
    print("Repository configured for containerized Git LFS.")


if __name__ == "__main__":
    main()
