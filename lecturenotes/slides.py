"""Visual segmentation: split a lecture video into segments, each with its best image.

Slide videos (the frame is still between changes):
1. Sample small greyscale frames (2 per second).
2. Find a live overlay: pixels that keep moving while slides stay still. A picture-in-picture webcam has a
   fixed border and is painted over; a presenter keyed over the slides has none and is removed with person
   segmentation instead, so slide content under them survives.
3. Split the video into visually stable runs; short unstable stretches are transitions.
4. Merge consecutive runs that show the same slide, or an incremental build of it
   (new content drawn only onto empty background, e.g. bullet points or code being typed).
5. For each slide, export a clean full-resolution image of its final state.

Camera footage (blackboard, operated camera, classroom): most of the frame moves, so there are no stable
runs. The video is cut into time windows and each window keeps the frame with the most readable content
(chalk or ink strokes), skipping close-ups of the speaker. Windows without readable content become
text-only segments; if no window has any, the video is a talking head.
"""
from __future__ import annotations

import time
import warnings
from pathlib import Path

import av
import cv2
import numpy as np

from .util import clock, imwrite, save_json

SAMPLE_FPS = 2.0
SMALL_WIDTH = 320
SCORE_WIDTH = 640
PIXEL_DIFF = 25            # grey-level difference that counts as a changed pixel
CHANGE_FRAC = 0.004        # share of changed pixels that marks a visual change
BUILD_ADDED = 0.9          # share of changes on former background that makes a change a "build"
MIN_STABLE_S = 2.0         # stable runs shorter than this are treated as transitions
OVERLAY_PIXEL_DIFF = 8
OVERLAY_MOTION = 0.10      # pixels changing in at least this share of samples belong to an overlay
CAMERA_SHARE = 0.35        # if this much of the frame moves, the video is camera footage, not slides
SMALL_CORNER_BOX = 0.08    # a corner overlay up to this share of the frame is a webcam box, even without a border
CLEAN_FRAMES = 5
PRESENTER_FRAMES = 9
FINAL_STATE_S = 10.0
KEYFRAME_WINDOW_S = 60.0   # camera footage: shortest window that gets its own keyframe
KEYFRAME_TARGET = 30       # camera footage: aim for at most this many windows
STROKE_CONTRAST = 40       # top-hat response that counts as a chalk/ink stroke pixel
# Best stroke share per window: MIT 18.06 blackboard 0.11–0.20, TED stage 0.02–0.04 (0.12–0.14 on title cards),
# Yale blackboard at 320x180 0.03–0.06 — low-resolution chalk is indistinguishable from a stage, so it goes text-only.
MIN_CONTENT = 0.05         # share of stroke pixels below which a frame has nothing readable
DUPLICATE_FRAC = 0.02      # consecutive keyframes differing less than this are the same view
CLOSE_UP_PERSON = 0.18     # a person covering at least this share of a sample makes it a close-up
PROP_NEAR_PRESENTER = 0.6  # a solid blob with at least this share within the presenter's reach is their prop

_STROKE_KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))


def _content_score(grey) -> float:
    """Share of thin, high-contrast strokes: light on dark (chalk) or dark on light (ink, slide text)."""
    light = cv2.morphologyEx(grey, cv2.MORPH_TOPHAT, _STROKE_KERNEL)
    dark = cv2.morphologyEx(grey, cv2.MORPH_BLACKHAT, _STROKE_KERNEL)
    return max(float((light > STROKE_CONTRAST).mean()), float((dark > STROKE_CONTRAST).mean()))


def _is_close_up(grey) -> bool:
    # Imported here so slide videos never load MediaPipe. On 320 px greyscale samples close-ups of the
    # speaker covered 0.19–0.32 of the frame and wide board shots 0–0.16 (MIT 18.06, Yale RLST 145).
    from .person import person_mask

    return float(person_mask(grey).mean()) >= CLOSE_UP_PERSON


def _sample(video: Path, log):
    times, frames, scores = [], [], []
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        width, height = stream.codec_context.width, stream.codec_context.height
        small_height = max(2, round(SMALL_WIDTH * height / width / 2) * 2)
        score_height = max(2, round(SCORE_WIDTH * height / width / 2) * 2)
        step, next_t, next_report = 1.0 / SAMPLE_FPS, 0.0, 120.0
        for frame in container.decode(stream):
            t = frame.time
            if t is None or t < next_t - 1e-3:
                continue
            grey = frame.reformat(width=SMALL_WIDTH, height=small_height, format="gray").to_ndarray()
            frames.append(cv2.GaussianBlur(grey, (3, 3), 0))
            scores.append(_content_score(
                frame.reformat(width=SCORE_WIDTH, height=score_height, format="gray").to_ndarray()))
            times.append(t)
            while next_t <= t:
                next_t += step
            if t >= next_report:
                log(f"  scanned {clock(t)}")
                next_report += 120.0
    if not frames:
        raise RuntimeError(f"No video frames could be decoded from {video}")
    return np.array(times), np.stack(frames), np.array(scores)


def _border_samples(frames):
    return frames[np.linspace(0, len(frames) - 1, min(len(frames), 200)).astype(int)].astype(np.int16)


def _persistent_edge(step) -> bool:
    """step: (samples, pixels along a line) differences across the line. True if the line is a sharp edge
    in almost every sample."""
    return (np.abs(step).mean(axis=1) > 12).mean() >= 0.8


def _detect_overlay(frames: np.ndarray):
    """Returns (box, motion_share, boxed). boxed is True for a picture-in-picture with a fixed border."""
    counts = np.zeros(frames.shape[1:], np.uint32)
    for i in range(1, len(frames)):
        counts += np.abs(frames[i].astype(np.int16) - frames[i - 1]) > OVERLAY_PIXEL_DIFF
    moving = (counts / max(1, len(frames) - 1) > OVERLAY_MOTION).astype(np.uint8)
    moving = cv2.morphologyEx(moving, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    height, width = moving.shape
    _, _, stats, _ = cv2.connectedComponentsWithStats(moving)
    box, best = None, 0
    for x, y, w, h, area in stats[1:]:
        if 0.004 <= w * h / (width * height) <= 0.35 and area > best:
            best, box = area, (int(x), int(y), int(w), int(h))
    boxed = False
    if box:
        samples = _border_samples(frames)
        box = _grow_to_border(samples, _snap_to_edges(box, width, height))
        x, y, w, h = box
        in_corner = (x == 0 or x + w == width) and (y == 0 or y + h == height)
        if in_corner:
            box = _extend_by_tint(samples, box)
            x, y, w, h = box
        # A small corner webcam often has no drawn border; a keyed presenter is larger (CS50: 25% of the frame).
        boxed = _has_border(samples, box) or (in_corner and w * h / (width * height) <= SMALL_CORNER_BOX)
    return box, float(moving.mean()), boxed


def _extend_by_tint(samples, box, tolerance=8, share=0.7):
    """A webcam's room can be only slightly darker than a white slide — too faint for an edge. Keep extending a
    corner box away from its frame edges while the next column or row is off the slide background in most
    samples (Human Psychophysics: room 233 on a 252 slide)."""
    x, y, w, h = box
    x1, y1 = x + w, y + h
    _, height, width = samples.shape
    background = np.array([np.bincount(s.ravel().clip(0, 255)).argmax() for s in samples])[:, None]

    def off_background(values):  # values: (samples, pixels along a line)
        return (np.abs(np.median(values, axis=1, keepdims=True) - background) > tolerance).mean() >= share

    limit_x, limit_y = int(width * 0.25), int(height * 0.25)
    if x1 == width:
        while x > width - (x1 - x) - limit_x and x > 0 and off_background(samples[:, y:y1, x - 1]):
            x -= 1
    elif x == 0:
        while x1 < limit_x + w and x1 < width and off_background(samples[:, y:y1, x1]):
            x1 += 1
    if y == 0:
        while y1 < limit_y + h and y1 < height and off_background(samples[:, y1, x:x1]):
            y1 += 1
    elif y1 == height:
        while y > height - h - limit_y and y > 0 and off_background(samples[:, y - 1, x:x1]):
            y -= 1
    return x, y, x1 - x, y1 - y


def _snap_to_edges(box, width, height, margin=0.08):
    """Overlays sit in corners; the moving person rarely fills the whole box, so extend it to nearby edges."""
    x, y, w, h = box
    x1, y1 = x + w, y + h
    if x <= width * margin:
        x = 0
    if y <= height * margin:
        y = 0
    if x1 >= width * (1 - margin):
        x1 = width
    if y1 >= height * (1 - margin):
        y1 = height
    return x, y, x1 - x, y1 - y


def _grow_to_border(samples, box):
    """Motion only covers the person, not the still room behind them. Grow the box to the overlay's real
    border: the outermost nearby line that is a sharp edge in almost every sample."""
    x, y, w, h = box
    x1, y1 = x + w, y + h
    _, height, width = samples.shape
    reach_x, reach_y = int(width * 0.15), int(height * 0.15)
    if x1 == width:
        for col in range(max(1, x - reach_x), x):
            if _persistent_edge(samples[:, y:y1, col] - samples[:, y:y1, col - 1]):
                x = col
                break
    elif x == 0:
        for col in range(min(width - 1, x1 + reach_x), x1, -1):
            if _persistent_edge(samples[:, y:y1, col] - samples[:, y:y1, col - 1]):
                x1 = col
                break
    if y == 0:
        for row in range(min(height - 1, y1 + reach_y), y1, -1):
            if _persistent_edge(samples[:, row, x:x1] - samples[:, row - 1, x:x1]):
                y1 = row
                break
    elif y1 == height:
        for row in range(max(1, y - reach_y), y):
            if _persistent_edge(samples[:, row, x:x1] - samples[:, row - 1, x:x1]):
                y = row
                break
    return x, y, x1 - x, y1 - y


def _has_border(samples, box) -> bool:
    """A picture-in-picture box has a fixed edge on every side that is not a frame edge (within 2 px)."""
    x, y, w, h = box
    x1, y1 = x + w, y + h
    _, height, width = samples.shape

    def column_edge(col):
        return any(_persistent_edge(samples[:, y:y1, k] - samples[:, y:y1, k - 1])
                   for k in range(max(1, col - 2), min(width - 1, col + 2) + 1))

    def row_edge(row):
        return any(_persistent_edge(samples[:, k, x:x1] - samples[:, k - 1, x:x1])
                   for k in range(max(1, row - 2), min(height - 1, row + 2) + 1))

    checks = []
    if x > 0:
        checks.append(column_edge(x))
    if x1 < width:
        checks.append(column_edge(x1))
    if y > 0:
        checks.append(row_edge(y))
    if y1 < height:
        checks.append(row_edge(y1))
    return bool(checks) and all(checks)


def _stable_runs(frames, times, valid):
    n_valid = max(1, int(valid.sum()))
    runs, start = [], 0
    for i in range(1, len(frames)):
        changed = (np.abs(frames[i].astype(np.int16) - frames[i - 1]) > PIXEL_DIFF) & valid
        if changed.sum() / n_valid > CHANGE_FRAC:
            runs.append((start, i - 1))
            start = i
    runs.append((start, len(frames) - 1))
    step = 1.0 / SAMPLE_FPS
    return [(a, b) for a, b in runs if times[b] - times[a] + step >= MIN_STABLE_S]


def _state(frames, run):
    a, b = run
    return np.median(frames[max(a, b - 9):b + 1], axis=0).astype(np.uint8)


def _relation(before, after, valid) -> str:
    changed = (np.abs(before.astype(np.int16) - after) > PIXEL_DIFF) & valid
    n_changed = int(changed.sum())
    if n_changed / max(1, int(valid.sum())) < CHANGE_FRAC:
        return "same"
    background_level = int(np.bincount(before[valid], minlength=256).argmax())
    background = np.abs(before.astype(np.int16) - background_level) <= 20
    return "build" if (changed & background).sum() / n_changed >= BUILD_ADDED else "new"


def _slide_plan(frames, times, overlay, duration):
    """(start, end, window_start, window_end, states, final_run_start) per slide; [] if nothing is stable."""
    valid = np.ones(frames.shape[1:], bool)
    if overlay:
        x, y, w, h = overlay
        valid[max(0, y - 2):y + h + 2, max(0, x - 2):x + w + 2] = False
    groups = []
    for run in _stable_runs(frames, times, valid):
        state = _state(frames, run)
        if groups and _relation(groups[-1]["state"], state, valid) != "new":
            groups[-1]["runs"].append(run)
            groups[-1]["state"] = state
        else:
            groups.append({"runs": [run], "state": state})
    plan = []
    for k, group in enumerate(groups):
        start = 0.0 if k == 0 else float(times[group["runs"][0][0]])
        end = duration if k == len(groups) - 1 else float(times[groups[k + 1]["runs"][0][0]])
        a, b = group["runs"][-1]
        w1 = float(times[b]) - 0.25
        run_start = min(w1, float(times[a]) + 0.25)
        plan.append((start, end, max(run_start, w1 - FINAL_STATE_S), w1, len(group["runs"]), run_start))
    return plan


def _keyframe_plan(frames, times, scores, duration):
    """Camera footage: per time window, the frame with the most readable content that is not a close-up of the
    speaker (window start None if nothing is readable)."""
    window = max(KEYFRAME_WINDOW_S, duration / KEYFRAME_TARGET)
    plan, previous = [], None
    for i in range(max(1, int(np.ceil(duration / window)))):
        start, end = i * window, min(duration, (i + 1) * window)
        idx = np.flatnonzero((times >= start) & (times < end))
        if idx.size == 0:
            continue
        ranked = [int(j) for j in idx[np.argsort(scores[idx])[::-1]] if scores[j] >= MIN_CONTENT]
        # A window whose only textured frames are close-ups or crowd shots has nothing worth showing.
        best = next((j for j in ranked if not _is_close_up(frames[j])), None)
        if best is None:
            plan.append((start, end, None, None, 0, None))
            previous = None
            continue
        t = float(times[best])
        if previous is not None and \
                (np.abs(frames[best].astype(np.int16) - frames[previous]) > PIXEL_DIFF).mean() < DUPLICATE_FRAC:
            prev_start, _, _, _, states, _ = plan[-1]
            plan[-1] = (prev_start, end, t, t, states + 1, None)
        else:
            plan.append((start, end, t, t, 1, None))
        previous = best
    return plan


def _grab(container, stream, t0: float, t1: float, count: int) -> list:
    targets = [float(t) for t in np.linspace(t0, t1, count)]
    container.seek(int(max(0.0, t0 - 0.05) / stream.time_base), stream=stream, backward=True)
    grabbed = []
    for frame in container.decode(stream):
        t = frame.time
        if t is None or t + 1e-3 < targets[0]:
            continue
        grabbed.append(frame.to_ndarray(format="bgr24"))
        while targets and targets[0] <= t + 1e-3:
            targets.pop(0)
        if not targets:
            break
    return grabbed


def _background_color(image):
    pixels = image[::4, ::4].reshape(-1, 3)
    keys = (pixels[:, 0] // 16).astype(np.int32) * 256 + (pixels[:, 1] // 16) * 16 + pixels[:, 2] // 16
    mode = np.bincount(keys).argmax()
    return pixels[keys == mode].mean(axis=0)


def _trim_bands(image, background):
    """Remove uniform edge bands (letterboxing) whose colour differs from the slide background."""
    def is_band(line):
        # Tolerate a few odd pixels, e.g. a laser pointer parked on the band.
        median = np.median(line, axis=0)
        uniform = (np.abs(line - median).max(axis=1) <= 6).mean() >= 0.98
        return uniform and np.abs(median - background).max() > 6

    height, width = image.shape[:2]
    top, bottom, left, right = 0, height - 1, 0, width - 1
    while top < height // 4 and is_band(image[top].astype(np.float32)):
        top += 1
    while bottom > height * 3 // 4 and is_band(image[bottom].astype(np.float32)):
        bottom -= 1
    while left < width // 4 and is_band(image[:, left].astype(np.float32)):
        left += 1
    while right > width * 3 // 4 and is_band(image[:, right].astype(np.float32)):
        right -= 1
    return image[top:bottom + 1, left:right + 1]


def _full_box(overlay, small_size, width, height, pad=6):
    sx, sy = width / small_size[0], height / small_size[1]
    x, y, w, h = overlay
    return (max(0, int(x * sx) - pad), max(0, int(y * sy) - pad),
            min(width, int((x + w) * sx) + pad), min(height, int((y + h) * sy) + pad))


def _remove_presenter(frames, overlay, small_size):
    """Rebuild the slide under a presenter keyed over it.

    Inside the presenter's area each pixel takes the median of the frames in which no person covers it.
    What is left is inpainted: pixels covered in every frame, and props the presenter brings along (laptop,
    lectern) — solid blobs lying mostly within the presenter's reach, which never move and are not people.
    Person masks are limited to that area, so people pictured on the slide itself stay untouched."""
    from .person import person_mask

    image = frames[-1].copy()
    height, width = image.shape[:2]
    x0, y0, x1, y1 = _full_box(overlay, small_size, width, height, pad=int(0.05 * width))
    grow = np.ones((max(9, width // 60),) * 2, np.uint8)
    covered = np.stack([cv2.dilate(person_mask(f).astype(np.uint8), grow)[y0:y1, x0:x1] > 0 for f in frames])
    if not covered.any():
        return _trim_bands(image, _background_color(image))

    crops = np.stack([f[y0:y1, x0:x1] for f in frames]).astype(np.float32)
    crops[covered] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN pixels are inpainted below
        crop = np.nan_to_num(np.nanmedian(crops, axis=0)).astype(np.uint8)
    always = covered.all(axis=0)
    if always.any():
        # Inpaint these first: left black, the holes would merge with bars and tables into one big "prop".
        crop = cv2.inpaint(crop, always.astype(np.uint8) * 255, 5, cv2.INPAINT_TELEA)

    # Blobs are judged on the whole slide: a bar or table running across it is mostly outside the presenter's
    # reach and stays, while a laptop in front of them lies within reach and touches their silhouette.
    background = _background_color(image)
    composed = image.copy()
    composed[y0:y1, x0:x1] = crop
    ink = (np.abs(composed.astype(np.int16) - background).max(axis=2) > 40).astype(np.uint8)
    solid = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(9, width // 85),) * 2, np.uint8))  # drops text
    touch = np.zeros((height, width), bool)
    touch[y0:y1, x0:x1] = covered.any(axis=0)
    reach = cv2.dilate(touch.astype(np.uint8), np.ones((max(9, width // 20),) * 2, np.uint8)) > 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid)
    near = np.bincount(labels[reach], minlength=count)
    touching = np.bincount(labels[touch], minlength=count)
    props = (near >= PROP_NEAR_PRESENTER * stats[:, cv2.CC_STAT_AREA]) & (touching > 0)
    props[0] = False
    fill = props[labels][y0:y1, x0:x1]
    if fill.any():
        crop = cv2.inpaint(crop, fill.astype(np.uint8) * 255, 5, cv2.INPAINT_TELEA)
    image[y0:y1, x0:x1] = crop
    return _trim_bands(image, background)


def _clean(frames, overlay, boxed, small_size):
    if overlay and not boxed:
        return _remove_presenter(frames, overlay, small_size)
    image = frames[0].copy() if len(frames) == 1 else np.median(np.stack(frames), axis=0).astype(np.uint8)
    background = _background_color(image)
    if overlay:
        x0, y0, x1, y1 = _full_box(overlay, small_size, image.shape[1], image.shape[0])
        image[y0:y1, x0:x1] = background.astype(np.uint8)
    return _trim_bands(image, background)


def detect(video: Path, out: Path, duration: float, log=print) -> dict:
    started = time.time()
    times, frames, scores = _sample(video, log)
    small_size = (frames.shape[2], frames.shape[1])
    duration = duration or float(times[-1])
    overlay, motion_share, boxed = _detect_overlay(frames)

    kind = "slides"
    plan = _slide_plan(frames, times, overlay, duration) if motion_share <= CAMERA_SHARE else []
    if not plan:
        kind, overlay, boxed = "camera", None, False
        plan = _keyframe_plan(frames, times, scores, duration)
        if all(step[2] is None for step in plan):
            kind = "talking_head"

    slides_dir = out / "slides"
    slides_dir.mkdir(exist_ok=True)
    for old in slides_dir.glob("slide_*.jpg"):
        old.unlink()
    entries = []
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        for start, end, w0, w1, states, run_start in plan:
            number = len(entries) + 1
            entry = {"no": number, "start": round(start, 2), "end": round(end, 2), "image": None, "states": states}
            if w0 is not None:
                if kind != "slides":
                    grabbed = _grab(container, stream, w0, w1, 1)
                    image = grabbed[0] if grabbed else None
                elif overlay and not boxed:
                    grabbed = _grab(container, stream, run_start, w1, PRESENTER_FRAMES)
                    image = _clean(grabbed, overlay, boxed, small_size) if grabbed else None
                else:
                    grabbed = _grab(container, stream, w0, w1, CLEAN_FRAMES)
                    image = _clean(grabbed, overlay, boxed, small_size) if grabbed else None
                if image is not None:
                    name = f"slides/slide_{number:02d}.jpg"
                    imwrite(out / name, image, quality=90)
                    entry["image"] = name
            entries.append(entry)

    doc = {
        "kind": kind,
        "overlay": None if overlay is None else [round(v / s, 4) for v, s in zip(overlay, small_size * 2)],
        "overlay_type": None if overlay is None else ("box" if boxed else "presenter"),
        "motion_share": round(motion_share, 4),
        "content_score": {name: round(float(np.percentile(scores, q)), 4)
                          for name, q in (("p10", 10), ("p50", 50), ("p90", 90), ("max", 100))},
        "seconds": round(time.time() - started, 1),
        "slides": entries,
    }
    save_json(out / "slides.json", doc)
    return doc
