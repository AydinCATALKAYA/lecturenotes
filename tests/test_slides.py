"""Slide detection on a small synthetic video: three slides, the second one built up in two steps."""
from pathlib import Path

import av
import numpy as np

from lecturenotes import slides

FPS = 5
WIDTH, HEIGHT = 320, 240


def _frame(boxes):
    image = np.full((HEIGHT, WIDTH, 3), 250, np.uint8)
    for x0, y0, x1, y1 in boxes:
        image[y0:y1, x0:x1] = 20
    return image


def _write_video(path: Path, states):
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=FPS)
        stream.width, stream.height, stream.pix_fmt = WIDTH, HEIGHT, "yuv420p"
        for boxes, seconds in states:
            for _ in range(int(seconds * FPS)):
                frame = av.VideoFrame.from_ndarray(_frame(boxes), format="rgb24")
                for packet in stream.encode(frame):
                    container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_detects_slides_and_merges_builds(tmp_path: Path):
    title = [(40, 40, 280, 70)]
    bullet_1 = [(40, 30, 200, 45), (40, 80, 260, 95)]
    bullet_2 = bullet_1 + [(40, 120, 260, 135)]
    figure = [(100, 60, 220, 180)]
    video = tmp_path / "lecture.mp4"
    _write_video(video, [(title, 6), (bullet_1, 6), (bullet_2, 6), (figure, 6)])

    doc = slides.detect(video, tmp_path, duration=24.0, log=lambda message: None)

    assert doc["kind"] == "slides"
    assert doc["overlay"] is None
    assert [slide["states"] for slide in doc["slides"]] == [1, 2, 1]
    assert [round(slide["start"]) for slide in doc["slides"]] == [0, 6, 18]
    assert all((tmp_path / slide["image"]).exists() for slide in doc["slides"])
