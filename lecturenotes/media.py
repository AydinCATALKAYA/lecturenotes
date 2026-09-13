"""Video probing and audio extraction with PyAV (bundles FFmpeg, so nothing else needs installing)."""
from __future__ import annotations

from pathlib import Path

import av


def probe(path: Path) -> dict:
    with av.open(str(path)) as container:
        video = container.streams.video[0] if container.streams.video else None
        audio = container.streams.audio[0] if container.streams.audio else None
        if container.duration:
            duration = container.duration / av.time_base
        elif video is not None and video.duration:
            duration = float(video.duration * video.time_base)
        else:
            duration = 0.0
        return {
            "name": Path(path).name,
            "duration": round(duration, 2),
            "width": video.codec_context.width if video else None,
            "height": video.codec_context.height if video else None,
            "fps": round(float(video.average_rate), 3) if video is not None and video.average_rate else None,
            "has_audio": audio is not None,
            "audio_codec": audio.codec_context.name if audio else None,
        }


def extract_audio(src: Path, dst: Path) -> None:
    """Write the soundtrack as .m4a. AAC is copied untouched; any other codec is re-encoded to AAC."""
    tmp = dst.with_suffix(".part.m4a")
    with av.open(str(src)) as inp, av.open(str(tmp), "w", format="mp4") as out:
        in_stream = inp.streams.audio[0]
        if in_stream.codec_context.name == "aac":
            out_stream = out.add_stream_from_template(in_stream)
            for packet in inp.demux(in_stream):
                if packet.dts is None:
                    continue
                packet.stream = out_stream
                out.mux(packet)
        else:
            rate = in_stream.codec_context.sample_rate or 44100
            out_stream = out.add_stream("aac", rate=rate, layout="stereo")
            out_stream.bit_rate = 128_000
            resampler = av.AudioResampler(format="fltp", layout="stereo", rate=rate)
            for frame in inp.decode(in_stream):
                frame.pts = None
                for chunk in resampler.resample(frame):
                    out.mux(out_stream.encode(chunk))
            for chunk in resampler.resample(None):
                out.mux(out_stream.encode(chunk))
            out.mux(out_stream.encode(None))
    tmp.replace(dst)
