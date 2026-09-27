---
name: video-to-game-sprites
description: Generate character animation videos from reference views using Volcengine Seedance, or convert existing videos into timed transparent PNG sequences, sprite sheets and Godot resources. Use for reference-to-animation workflows, video extraction, background cleanup and reusable sprite exports.
---

# Video to game sprites

Use the bundled `scripts/video_to_sprite.py`. It provides three separately reproducible stages: `extract`, `prepare`, `build`. See [workflow.md](references/workflow.md) for configuration examples, setup, and output formats.

## Reference image input

When the input is a character design view and video generation is requested, read [ark-workflow.md](references/ark-workflow.md). Use `scripts/ark_video.py` for persistent generation jobs, then pass the downloaded video into the workflow below. Inspect the selected view and adapt the prompt to the requested action, facing and character identity before submission. Read the cost-control section before submission: show the estimate, obtain the user’s budget if none was supplied, and require one shared ledger for the work. Never interpret the example budget as authorization. Cloud balance is not connected; local budget is separate. Current preset: doubao-seedance-2-0-mini-260615, 480p, 1:1, 4 seconds, silent. Do not silently upgrade the model or generate extra paid variants. A request to build this workflow alone is not a request to spend on generation.

## Chroma-background generation

For new character videos, default to a uniform magenta (#FF00FF) reference and background prompt. Follow [chroma workflow](references/chroma-workflow.md) to prepare the reference and use the matching matte preset. If the character contains magenta, select a contrasting key instead. Existing gray-background videos retain their original settings; do not regenerate them automatically.

## Workflow

1. Inspect the actual video and current character identity. Preserve the source. Extract all decoded frames and their presentation timestamps before choosing a rate or cycle. Do not infer the full sequence timing solely from nominal FPS.
2. Inspect the labeled overview. Use `prepare` for a nearly uniform background. Border-connected matting protects enclosed similarly colored character regions, but can still damage armor at the silhouette: inspect edges and thin fingers. Enable shadow removal only after examining the video's lower region. Keep raw frames. For complex backgrounds use externally produced masks through `mask_directory`; do not claim the simple keyer is universal segmentation.
3. Loop scores only suggest candidate boundaries. Inspect a complete left/right stride with the original asymmetrical arm identities. Reject half-strides, costume drift, wrong hand/leg coordination, and excessive body deformation. Exclude the matching endpoint frame from the loop. For non-looping actions choose the action range and set `loop: false`.
4. Export using one shared union crop, scale and placement for the whole selected range. Do not align each frame to its lowest foot: this erases flight and vertical bounce. Preserve timestamps when reducing frames. Preserve asymmetry unless the user explicitly authorizes mirroring; follow project-level direction preferences.
5. Inspect the frame contact sheet and play the loop at native size and enlarged size. Export PNGs, a sheet, animation metadata, GIF and HTML previews, and a Godot 4 SpriteFrames resource. Source defects cannot be fixed by extraction. Mark visual approval separately from structural checks; do not call a low seam score proof of natural motion.
6. Deliver a preview, saved paths, exact reusable config/command, and limitations. Integrate into the live game only when requested. Installation of this skill does not authorize cloud generation or uploading video.

## Operational details

- Output directories must be new or empty; keep candidate iterations versioned.
- Configuration paths for external masks are relative to the config file. Other input/output paths are CLI paths.
- For source provenance retain the video hash, source indices and frame times in exported metadata.
- Use local dependencies in a virtual environment; `imageio-ffmpeg` provides the decoder without requiring a system-wide FFmpeg installation.
- PNGs preserve alpha. GIF is a convenience preview with centisecond timing; HTML and JSON use source timing. The Godot resource uses speed 1 and per-frame durations in seconds.
