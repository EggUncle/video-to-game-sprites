# Setup and commands

Use Python 3.11+ and create a virtual environment in the consuming project. Install `scripts/requirements.txt` from the skill directory. The FFmpeg wheel normally includes a suitable binary; `IMAGEIO_FFMPEG_EXE` can select an existing compatible decoder. No GPU or paid API is required.

```sh
python3 -m venv .venv-video
.venv-video/bin/python -m pip install -r /absolute/path/to/skill/scripts/requirements.txt
.venv-video/bin/python /absolute/path/to/skill/scripts/video_to_sprite.py extract input.mp4 --out output/source
.venv-video/bin/python /absolute/path/to/skill/scripts/video_to_sprite.py prepare output/source --config matte.json --out output/matte
.venv-video/bin/python /absolute/path/to/skill/scripts/video_to_sprite.py build output/matte --config clip.json --out output/run-v1
```

`extract` preserves every decoded frame, writes `source.json` and `decode.log`, and makes `overview.jpg`. Inspect metadata and overview before processing long videos; extraction is not a streaming storage service.

# Matte configuration

For new magenta-background video, start with `assets/matte-magenta.json` and follow [chroma-workflow.md](chroma-workflow.md). Keep the gray-background settings below for legacy sources.

```json
{
  "matte": {
    "threshold": 32,
    "edge_softness": 18,
    "largest_component": true,
    "shadow": {"enabled": false}
  },
  "loop_min_frames": 14,
  "loop_max_frames": 32,
  "loop_margin_frames": 6
}
```

Automatic key color is the per-frame median of corner patches. For a specific color add `key_color: [R,G,B]`. Color thresholds use Euclidean RGB distance on 0–255 values. Shadow removal optionally uses `start_y` (source pixels), `max_chroma` (max channel minus min channel) and `min_luma` (mean channel) to classify low-saturation light ground pixels. It can erase gray clothing at the bottom: inspect before accepting. Lower `max_chroma` or move `start_y` down if boots lose pixels. `largest_component` works for one connected character, but may discard detached props or isolated fingers; set false to retain components above `min_component_area` (default 80).

Instead of automatic matting, provide `mask_directory` relative to this JSON file. The directory must contain a same-size grayscale alpha mask named `000000.png`, etc., for every source frame.

# Selection/export configuration

```json
{
  "name": "run_right",
  "start": 24,
  "end_exclusive": 48,
  "loop": true,
  "cell": [128,128],
  "padding": 8,
  "columns": 6,
  "resample": "nearest"
}
```

Indices are zero-based. `end_exclusive` must identify a real decoded endpoint frame so timing is known; the endpoint itself is omitted. For a smaller sequence use `indices: [24,26,28,30,32,34,36,38,40,42,44,46]`. Each selected frame lasts until the next selected source timestamp or the endpoint, preserving the total duration. Defaults retain every frame.

`nearest` preserves existing pixel clusters but may alias detailed video. Use `lanczos` for smooth art or compare both after downscaling. Both use one identical transform across all selected frames. No per-frame stabilization or generative in-betweening is performed.

# Deliverables and checks

- `frames/*.png`: transparent full-cell frames.
- `spritesheet.png`: fixed grid, trailing cells may be empty.
- `animation.json`: frame times, source provenance, shared transform, and structural QC.
- `animation.tres`: Godot 4 SpriteFrames with relative PNG dependencies. Copy the resource **together with** its `frames` directory into a Godot project; import textures before loading.
- `contact.png`, `preview.gif`, `preview.html`: visual review. Open HTML using an allowed local preview; respect any browser access restrictions.

QA metrics flag clipping and seam differences; they cannot identify left/right anatomy or physically correct foot contacts. A video can pass all numeric tests yet remain unsuitable. Do not silently set `production_approved` true. When validating .tres, use a temporary Godot project so current gameplay is unchanged.

## Gray/white edge contamination

For video backgrounds mixed into anti-aliased edges, enable `decontaminate_radius` (e.g. 3 source pixels), `decontaminate_tolerance` (32–50 RGB distance), and `alpha_floor` (0.12–0.2). The algorithm estimates foreground color from the nearest interior pixel and solves for background mixing only in this boundary band. Check on dark, gray and light backgrounds at runtime alpha cutoff, not only against the original gray backdrop.

Small enclosed gaps between limbs may retain background. Optional `enclosed_key_threshold` (e.g. 14) and `enclosed_min_area` (12 source pixels) remove enclosed patches very close to the key color. This is opt-in: a costume region exactly matching the key cannot be distinguished automatically. Verify pale prostheses, fingers, hair and clothing patches before accepting.

`neutral_fringe_cleanup: true` additionally targets bright, nearly neutral boundary pixels next to a dark interior when compression artifacts prevent a reliable color fit. It can suppress genuine tiny highlights; leave it off for reflective/chrome designs unless visually checked. After nearest-neighbor downscaling, inspect at the engine's alpha cutoff: new isolated 1–2 pixel islands may need a separate connected-component cleanup at final resolution, not broad erosion of the character.
