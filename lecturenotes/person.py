"""Person segmentation with MediaPipe's selfie segmenter. Runs locally on the CPU (~15 ms per 720p frame)."""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import cv2
import numpy as np

MODEL = Path(__file__).parent / "models" / "selfie_segmenter.tflite"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/image_segmenter/"
             "selfie_segmenter/float16/latest/selfie_segmenter.tflite")
_loaded = None


def _segmenter():
    global _loaded
    if _loaded is None:
        if not MODEL.exists():
            MODEL.parent.mkdir(exist_ok=True)
            urllib.request.urlretrieve(MODEL_URL, MODEL)
        os.environ.setdefault("GLOG_minloglevel", "2")
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        options = vision.ImageSegmenterOptions(base_options=BaseOptions(model_asset_path=str(MODEL)),
                                               output_confidence_masks=True)
        _loaded = (mp, vision.ImageSegmenter.create_from_options(options))
    return _loaded


def person_mask(image) -> np.ndarray:
    """Boolean mask of the pixels that belong to a person. Accepts BGR or greyscale images."""
    mp, segmenter = _segmenter()
    rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB if image.ndim == 2 else cv2.COLOR_BGR2RGB)
    result = segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    confidence = result.confidence_masks[0].numpy_view()
    return (confidence[..., 0] if confidence.ndim == 3 else confidence) > 0.5
