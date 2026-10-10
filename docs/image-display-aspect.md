# Camera picture proportions

Date: 10 October 2026. The Python adapter work preceding this investigation was
committed as `b949ef9`. Initial display checks used saved media only. After the
owner supplied a Hik-Connect screenshot, the actual service was restarted and
one brief live session verified the correction. Stream settings and source
frames were not changed or cropped.

## Evidence

Saved SDK live frames are 352 × 288. Saved historical frames and the extracted
MP4 are 960 × 1088. The browser originally used `object-fit: contain`, faithfully
preserving these raster proportions, which made the recorded picture especially
tall and narrow.

Raster dimensions are not always the intended display dimensions. Hikvision's
[compression reference](https://open.hikvision.com/hardware/structures/NET_DVR_COMPRESSION_INFO_V30.html)
documents CIF dimensions and 960 × 1080 as 1080p Lite. Its
[DVR manual](https://us-legacy.hikvision.com/en/system/files_force/um_ds-72xxhui-kx_ds-7216hqi-kx_062817na.pdf?download=1)
also describes the latter mode. These support the explanation of reduced raster
width, but do not establish this camera's exact sample/display aspect metadata.
The decoder callback currently gives us dimensions, and the frame JSON passes
only dimensions/sequence; the browser-ready path does not carry a display ratio.
FFprobe found no sample/display aspect fields in our re-encoded MP4.

The owner confirmed that this camera looks correct as widescreen (16:9) in
Hik-Connect, so 16:9 is the expected display setting for this camera. It is not
a measured stream metadata value or a rule for every Hikvision camera. The extra
eight decoded
rows in the historical frame may be coding alignment; their meaning has not
been verified, so they are retained.

## Implementation

[MediaDisplay](../web/shared/media-player.js) fits the entire picture inside the
viewer using a chosen display ratio. It calculates a centered rectangle bounded
by the available width/height, then fills that rectangle with the raster. This
permits non-square-pixel correction while retaining letterboxing and all source
pixels; it does not fill the whole viewport by cropping edges.

The same helper handles the live image and historical video. It reacts to media
metadata and container resizing. The frontend now uses native JavaScript modules;
the backend explicitly serves the shared module as an allowed asset.

Scaling uses the browser's normal image/video renderer. JPEGs retain their
original decoded dimensions, so this introduces no backend resampling or
larger JPEG transfers. Preset ratios skip per-frame metadata sizing; Original
recalculates only when dimensions change. Repeated fits with identical geometry
do not write CSS sizes again. Layout work is limited to actual size/ratio changes
rather than a polling or per-frame resize loop.

An **Aspect ratio** control offers Widescreen (16:9), Standard (4:3) and Original.
Original uses the browser's natural media proportions. The selection is remembered
for camera 1 in this browser's local storage and applies to both views. It does
not change the recorder or another browser's choice. A future grid should retain
separate camera preferences and consume confirmed display-ratio metadata when
the backend can supply it.

The preference key is now versioned. Old choices made during the comparison
revision are ignored once so the confirmed 16:9 default takes effect; subsequent
explicit selections remain remembered.

This fixes presentation in this viewer. The saved JPEG/MP4 files remain unchanged;
opening the historical MP4 elsewhere still depends on its original metadata.
Future exports should carry a confirmed display ratio rather than silently
assuming square pixels during raw-frame re-encoding.

## Verification

The existing ten offline unit tests passed. The
[browser aspect check](../tools/check_media_aspect.py) served saved JPEG/MP4
fixtures inside Docker Chromium with networking disabled and no credentials.
Eight cases passed: three live ratios, mobile live/history, desktop history,
original history proportions, and switching back to live. The selected ratio
survived a refresh, media stayed inside its viewer, and no camera-start POST or
browser error occurred. Screenshots and measurements are private under
`.local/aspect-check/`.

The optimized revision passed the same eight offline fixture cases, including
legacy-preference migration and remembered new selections. The
[actual-service browser check](../tools/check_browser_viewer.py) then confirmed
16:9 presentation for recorded playback and changing live frames. It observed
49 live JPEGs, unchanged 352 × 288 source dimensions and zero style mutations
during steady frames. Refresh reused the session and Stop completed cleanup.
The native report confirmed one login, 84 decoded frames, 50 JPEGs and zero SDK,
preview or decoder errors. Private screenshots/report are under
`.local/browser-aspect-live/`.

The web service remains running with the camera stopped for the owner's next
Start. The supplied Android screenshot corroborates the preferred 16:9 display;
source aspect metadata remains an investigation item.
