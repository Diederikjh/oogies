# Publication checks

Recorder settings and credentials belong in ignored `.local/`. Captures,
extracted SDK files, APK analysis, native logs and private backups also stay
there. Source and investigation notes use `192.0.2.10`, a documentation-only
example; it is not the installation's recorder address. All current diagnostic
entry points read the private recorder configuration.

Before publishing:

```sh
python3 tools/check_publication.py --history
```

This checks tracked files, publishable untracked files and the full history of local branches and tags. It rejects private IPv4/IPv6 network addresses, personal home-directory
paths and tracked private directories. When private credentials/configuration
exist locally, it also checks for their known values, including the effective
login-password prefix and URL/base64/UTF-16 forms. ZIP entries are checked for
those exact private values. Generic vendor example addresses inside the original
SDK archive are not treated as the owner's device addresses.

Findings print file/object locations and categories, never matched values. The
check exits nonzero on findings or an incomplete scan. Common account names can
also be ordinary technical vocabulary; they are not treated as secret substrings.
Synthetic fixtures and loopback/documentation addresses remain usable.

The repository's pre-push hook runs this check before the existing Docker Git
LFS upload. Configure that hook with `python3 tools/setup_git_lfs.py` after
cloning. GitHub CI also checks branch/tag history. The local check can compare
known private values; CI has no recorder credentials to compare.

For a general token/password-pattern scan, run Gitleaks in Docker. Keep its
fully redacted reports private:

```sh
mkdir -p .local/publication-audit
chmod 700 .local/publication-audit
docker run --rm --network none --read-only \
  --user "$(id -u):$(id -g)" --cap-drop=ALL --security-opt=no-new-privileges \
  --cpus=2 --memory=1g --pids-limit=128 --tmpfs /tmp:rw,nosuid,size=64m \
  --mount "type=bind,source=$PWD,target=/repo,readonly" \
  --mount "type=bind,source=$PWD/.local/publication-audit,target=/reports" \
  ghcr.io/gitleaks/gitleaks:latest git /repo --log-opts=--all \
  --redact=100 --no-banner --report-format=json \
  --report-path=/reports/gitleaks-history.json
```

These scans combine known-value checks with common secret patterns; they cannot
prove that every possible secret format is absent. Review staged paths and keep
private artifacts out of Git. The original SDK archive remains unchanged in Git
LFS and is checked for the owner's known private values before publication.

## Initial cleanup

Before the first remote was configured, the current files and unpublished history
were sanitized to remove the installation's addresses and personal home paths.
The original history and LFS objects are backed up under ignored
`.local/publication-backup/`. Commit hashes changed; any older hashes mentioned
in historical notes refer to the original local history. Private configuration
and the running service were retained.

No push is made until the owner supplies the GitHub repository. When ready,
push the cleaned branch through the configured pre-push/LFS hook. Do not publish
private backups or reintroduce their original commits through another branch.

Tool references: [Gitleaks](https://github.com/gitleaks/gitleaks) and
[git-filter-repo](https://github.com/newren/git-filter-repo). Address examples use
[IANA's documentation ranges](https://www.iana.org/assignments/iana-ipv4-special-registry/iana-ipv4-special-registry.xhtml).

Local tool checkpoint refs and reflogs remain private metadata. History scanning
selects branches/tags and HEAD; the pre-push hook rejects other ref types, including
checkpoint refs. The initial rewrite preserves those local checkpoints and rewrites
only publication history. Use a normal branch push when publishing.
