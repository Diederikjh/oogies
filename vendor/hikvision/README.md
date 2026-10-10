# Preserved Hikvision SDK

`EN-HCNetSDKV6.1.9.48_build20230410_linux64.zip` is the unchanged original
Linux64 vendor package, tracked with Git LFS. This preserves all bundled
binaries, headers, examples, documentation and license material without
duplicating the extracted SDK in Git.

- Official download page: <https://www.hikvision.com/en/support/tools/hitools/clf4633a00e385d6ea/>
- Downloaded manually for this investigation; automated access was blocked.
- Size: 67,235,848 bytes.
- SHA-256: `8de553fb2e8dbb0ac441ee1bd73c5ecb73d720c1359396750479a6e169abf93f`.

The working extracted copy is `.local/hik-sdk/sdk/` and is ignored. Restore it
from this archive as described in the root [README](../../README.md).

LFS keeps a small pointer in Git and the ZIP in the local LFS object store.
A future remote backup must upload both Git history and its LFS objects;
the initial local commit alone is not an off-machine backup.
