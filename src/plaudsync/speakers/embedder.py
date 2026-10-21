"""CAM++ voice embeddings per Plaud speaker cluster. Reads audio only; no Plaud/network code
except the one-time pinned model download."""

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import requests
import soundfile as sf
from loguru import logger

from plaudsync.speakers.transcript import cluster_key, cluster_labels

MODEL_FILE = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/" + MODEL_FILE
)
MODEL_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"
MODEL_SIZE = 28_281_164

MIN_SEGMENT_S = 1.5
MIN_CLUSTER_S = 10.0
MAX_CLUSTER_S = 120.0
MAX_CLIP_S = 15.0


class ModelDownloadFailed(Exception):
    pass


@dataclass(frozen=True)
class ClusterEmbedding:
    cluster: str
    label: str
    embedding: np.ndarray
    seconds: float
    clip_segments: list[tuple[int, int]]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _valid(path: Path) -> bool:
    return path.is_file() and path.stat().st_size == MODEL_SIZE and _sha256(path) == MODEL_SHA256


def ensure_model(state_root: Path) -> Path:
    target = state_root / ".plaudsync" / "models" / MODEL_FILE
    if _valid(target):
        return target
    if urlparse(MODEL_URL).scheme != "https":
        raise ModelDownloadFailed("model URL must use https")
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    resp = None
    try:
        resp = requests.get(MODEL_URL, stream=True, timeout=60, allow_redirects=True)
        resp.raise_for_status()
        with part.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
        if part.stat().st_size != MODEL_SIZE or _sha256(part) != MODEL_SHA256:
            raise ModelDownloadFailed("model checksum mismatch")
        part.replace(target)
    except ModelDownloadFailed:
        raise
    except (requests.RequestException, OSError) as exc:
        raise ModelDownloadFailed(f"model download failed: {type(exc).__name__}") from exc
    finally:
        if resp is not None:
            resp.close()
        part.unlink(missing_ok=True)
    logger.info("speaker model downloaded")
    return target


def load_extractor(model_path: Path) -> Any:
    import sherpa_onnx

    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(model_path), num_threads=1, provider="cpu"
    )
    return sherpa_onnx.SpeakerEmbeddingExtractor(config)


def cut_clip(
    path: Path, segments: list[list[int]] | list[tuple[int, int]], *,
    format: str = "OGG", subtype: str | None = "VORBIS",
) -> bytes | None:
    """Concatenate the [start_ms, end_ms] segments as mono audio. Vorbis by default: unlike
    Opus it takes any sample rate (local recordings may be 44.1 kHz MP3)."""
    parts: list[np.ndarray] = []
    with sf.SoundFile(str(path)) as f:
        sr = f.samplerate
        total = f.frames
        for start_ms, end_ms in segments:
            start = max(0, int(start_ms * sr / 1000))
            end = min(total, int(end_ms * sr / 1000))
            if end <= start:
                continue
            f.seek(start)
            data = f.read(end - start, dtype="float32", always_2d=True)
            if data.shape[0]:
                parts.append(data.mean(axis=1))
    if not parts:
        return None
    buf = io.BytesIO()
    sf.write(buf, np.concatenate(parts), sr, format=format, subtype=subtype)
    return buf.getvalue()


def _seg_seconds(seg: dict) -> float:
    return (seg["end_time"] - seg["start_time"]) / 1000


def embed_clusters(audio_path: Path, segments: list[dict], extractor: Any) -> list[ClusterEmbedding]:
    clusters: dict[str, list[dict]] = {}
    for seg in segments:
        key = cluster_key(seg)
        if (
            key
            and seg.get("start_time") is not None
            and seg.get("end_time") is not None
            and _seg_seconds(seg) >= MIN_SEGMENT_S
        ):
            clusters.setdefault(key, []).append(seg)

    labels = cluster_labels(segments)
    out: list[ClusterEmbedding] = []
    # Seek per segment: decoding a multi-hour recording at once would need GBs of RAM.
    with sf.SoundFile(str(audio_path)) as audio:
        sr = audio.samplerate
        frames = audio.frames

        def _readable_s(seg: dict) -> float:
            a = int(seg["start_time"] * sr / 1000)
            b = min(int(seg["end_time"] * sr / 1000), frames)
            return max(b - a, 0) / sr

        def read(seg: dict, max_s: float) -> tuple[np.ndarray, int, int] | None:
            a = int(seg["start_time"] * sr / 1000)
            if a >= frames:
                return None  # transcript overruns audio: skip this segment only
            b = min(int(seg["end_time"] * sr / 1000), frames, a + int(max_s * sr))
            if b <= a:
                return None
            audio.seek(a)
            wav = audio.read(b - a, dtype="float32", always_2d=True).mean(axis=1)
            return wav, a * 1000 // sr, b * 1000 // sr

        for key, segs in clusters.items():
            total = sum(_readable_s(s) for s in segs)
            if total < MIN_CLUSTER_S:
                continue
            ordered = sorted(segs, key=_seg_seconds, reverse=True)
            chunks: list[np.ndarray] = []
            used = 0.0
            clip: list[tuple[int, int]] = []
            clip_used = 0.0
            for seg in ordered:
                if used >= MAX_CLUSTER_S:
                    break
                got = read(seg, MAX_CLUSTER_S - used)
                if got is None:
                    continue
                wav, start_ms, end_ms = got
                chunks.append(wav)
                used += len(wav) / sr
                remaining = MAX_CLIP_S - clip_used
                if remaining > 0:
                    clip_end = min(end_ms, start_ms + int(remaining * 1000))
                    if clip_end > start_ms:
                        clip.append((start_ms, clip_end))
                        clip_used += (clip_end - start_ms) / 1000
            if not chunks:
                continue
            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate=sr, waveform=np.concatenate(chunks))
            stream.input_finished()
            emb = np.array(extractor.compute(stream), dtype=np.float32)
            emb = emb / (np.linalg.norm(emb) + 1e-9)
            out.append(ClusterEmbedding(key, labels.get(key, key), emb, total, clip))
    return out
