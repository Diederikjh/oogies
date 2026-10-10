# Desktop freeze: initial investigation

Date: 9 October 2026. All times below are South Africa time.
SDK setup and recorder probing were held while investigating. No system
configuration was changed and no heavy build was restarted.

## Main findings

The strongest recorded evidence is a kernel memory-management failure before
the Docker build. Storage contention is an additional plausible contributor.
The exact cause of the reported desktop/audio freeze remains unproven.

| Time | Recorded event |
| --- | --- |
| 19:23:57–58 | Kernel page fault in `should_skip_vma`, process `kswapd0`; kernel oops on `6.8.0-146-generic` |
| 19:23:58 | Kernel reports `kswapd0` exited with interrupts disabled and `preempt_count 1` |
| 19:27:13–16 | Four further kernel oops events involving `fuser` and `show_map_vma` |
| 20:58:14 | Debian base image pull logged by Docker |
| 21:00:19–21 | Docker build networking starts |
| 21:06:26–27 | Browser dependency build stage starts |
| 21:08:26 | That stage's build network interface is removed |
| 21:09:01 | Last retained previous-boot journal record |
| 21:30:29 | Current boot begins |

The user recalls the freeze around 21:35. That differs from the retained
previous-boot/reboot timeline, so the exact event time and whether there was
a second freeze after restarting need clarification before firm correlation.

`kswapd0` is part of memory reclaim. The trace includes the multi-generation
LRU/page-walking path. These faults show that the previous boot had already
experienced serious kernel errors; they do not establish whether the underlying
problem was a kernel bug, a driver interaction or hardware corruption.
The module list includes NVIDIA and VirtualBox modules, but their presence
does not establish that either caused the fault.

Sources for interpretation: [Linux memory-reclaim documentation](https://docs.kernel.org/admin-guide/mm/multigen_lru.html),
[kernel oops/taint documentation](https://docs.kernel.org/admin-guide/tainted-kernels.html).

## Storage and resource observations

- `/var`, including `/var/lib/docker` and system journals, is on `/dev/sdc1`,
  a mechanical disk. The NVMe SSD holds `/` and `/tmp` instead.
- The build installed compiler, media and browser dependencies, downloaded
  approximately 340 MB of packages and accumulated multiple GB of build cache.
  Its many filesystem operations and final image export plausibly added I/O load.
- Initial post-reboot sampling showed substantial I/O pressure and 10–15% I/O
  wait in two one-second intervals. Later sampling was substantially quieter.
  These measurements describe the rebooted system, not conditions at the freeze.
- Memory after reboot was approximately 3.4 GiB used out of 15 GiB, with 12 GiB
  available and no swap used. That does not prove memory availability before
  the freeze. No OOM-kill record or NVIDIA Xid was found in the checked logs.
- `/var` has approximately 704 GiB free; Docker storage was not full.
- No containers are running. The browser image was not completed/tagged;
  intermediate build cache remains. No SDK login was attempted.
- ZoneMinder repeatedly fails to start because its MySQL socket is unavailable.
  This was present before and after the restart; no evidence ties it to the freeze.
- SMART health could not be read: the tool environment cannot open `/dev/sdc`.

## Next steps

Keep heavy builds stopped until the kernel-fault timeline is reviewed. A focused
kernel/driver investigation is more informative than assuming the SDK or browser
application caused the whole-machine freeze. For later SDK work, use a smaller
runtime, bound its CPU/memory use and consider SSD-backed build storage. These
are proposed mitigations, not changes already made or a demonstrated kernel fix.

The full kernel-fault excerpt is preserved privately at
`.local/freeze-diagnostics/previous-kernel-faults.log`.
