import hashlib
import os
from pathlib import Path

import numpy as np
import pytest
import requests
import soundfile as sf

from plaudsync.speakers import embedder
from plaudsync.speakers.embedder import ModelDownloadFailed, embed_clusters, ensure_model

SR = 16000


class _Stream:
    def __init__(self):
        self.waveform = np.zeros(0, dtype=np.float32)

    def accept_waveform(self, sample_rate, waveform):
        assert sample_rate == SR
        self.waveform = waveform

    def input_finished(self):
        pass


class _FakeExtractor:
    def __init__(self):
        self.lengths = []

    def create_stream(self):
        return _Stream()

    def compute(self, stream):
        self.lengths.append(len(stream.waveform))
        return [float(len(stream.waveform)), 1.0, 0.0]


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "a.ogg"
    data = np.random.default_rng(0).standard_normal(SR * 40).astype("float32") * 0.1
    sf.write(path, data, SR, format="OGG", subtype="OPUS")
    return path


def _seg(speaker, start_s, end_s):
    return {
        "speaker": speaker,
        "original_speaker": speaker,
        "start_time": int(start_s * 1000),
        "end_time": int(end_s * 1000),
        "content": "x",
    }


def test_cluster_below_10s_ignored(audio):
    segs = [_seg("Speaker 1", 0, 5), _seg("Speaker 2", 5, 20)]
    out = embed_clusters(audio, segs, _FakeExtractor())
    assert [c.cluster for c in out] == ["Speaker 2"]


def test_cap_120s_and_longest_first(tmp_path):
    path = tmp_path / "long.ogg"
    data = np.random.default_rng(1).standard_normal(SR * 300).astype("float32") * 0.1
    sf.write(path, data, SR, format="OGG", subtype="OPUS")
    segs = [_seg("Speaker 1", i * 10, i * 10 + 9) for i in range(28)]  # 252 s
    ext = _FakeExtractor()
    out = embed_clusters(path, segs, ext)
    assert len(out) == 1
    assert ext.lengths[0] <= 120 * SR
    assert ext.lengths[0] >= 110 * SR
    assert out[0].seconds == pytest.approx(252.0)


def test_longest_first_picks_long_segment(tmp_path):
    path = tmp_path / "long.ogg"
    data = np.random.default_rng(1).standard_normal(SR * 300).astype("float32") * 0.1
    sf.write(path, data, SR, format="OGG", subtype="OPUS")
    segs = [_seg("Speaker 1", 0, 2)] + [_seg("Speaker 1", 10 + i * 10, 10 + i * 10 + 9) for i in range(13)]
    out = embed_clusters(path, segs, _FakeExtractor())
    assert (0, 2000) not in out[0].clip_segments


def test_segment_past_audio_end_skipped_no_crash(audio):
    segs = [_seg("Speaker 1", 0, 12), _seg("Speaker 1", 50, 60), _seg("Speaker 2", 12, 30)]
    ext = _FakeExtractor()
    out = embed_clusters(audio, segs, ext)
    assert [c.cluster for c in out] == ["Speaker 1", "Speaker 2"]
    assert ext.lengths[0] == 12 * SR  # past-end segment contributed nothing


def test_clip_segments_at_most_15s(audio):
    segs = [_seg("Speaker 1", i * 4, i * 4 + 3) for i in range(9)]  # 27 s
    out = embed_clusters(audio, segs, _FakeExtractor())
    clips = out[0].clip_segments
    assert clips and all(isinstance(a, int) and isinstance(b, int) for a, b in clips)
    assert sum(b - a for a, b in clips) <= 15000


def test_embedding_is_l2_normalised_and_labelled(audio):
    segs = [_seg("Speaker 1", 0, 12)]
    segs[0]["speaker"] = "Jan"
    out = embed_clusters(audio, segs, _FakeExtractor())
    assert out[0].label == "Jan"
    assert np.linalg.norm(out[0].embedding) == pytest.approx(1.0, abs=1e-5)


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        yield self._data

    def close(self):
        pass


def test_ensure_model_hash_mismatch_raises_and_cleans(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(b"wrong bytes"))
    with pytest.raises(ModelDownloadFailed):
        ensure_model(tmp_path)
    models = tmp_path / ".plaudsync" / "models"
    assert not list(models.glob("*.part"))
    assert not (models / embedder.MODEL_FILE).exists()


def test_ensure_model_downloads_and_verifies(tmp_path, monkeypatch):
    payload = b"model-bytes"
    monkeypatch.setattr(embedder, "MODEL_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(embedder, "MODEL_SIZE", len(payload))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(payload))
    path = ensure_model(tmp_path)
    assert path == tmp_path / ".plaudsync" / "models" / embedder.MODEL_FILE
    assert path.read_bytes() == payload


def test_ensure_model_existing_valid_no_network(tmp_path, monkeypatch):
    payload = b"model-bytes"
    monkeypatch.setattr(embedder, "MODEL_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(embedder, "MODEL_SIZE", len(payload))
    target = tmp_path / ".plaudsync" / "models" / embedder.MODEL_FILE
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)

    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(requests, "get", boom)
    assert ensure_model(tmp_path) == target


def test_ensure_model_rejects_non_https(tmp_path, monkeypatch):
    monkeypatch.setattr(embedder, "MODEL_URL", "http://example.com/m.onnx")
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("network used"))
    with pytest.raises(ModelDownloadFailed):
        ensure_model(tmp_path)


_REAL = Path(os.environ.get("LOCALAPPDATA", "")) / "plaudsync" / "spike_speaker_models" / (
    "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
)


@pytest.mark.slow
@pytest.mark.skipif(not _REAL.exists(), reason="spike model not present")
def test_real_model_two_clusters(audio):
    segs = [_seg("Speaker 1", 0, 14), _seg("Speaker 2", 15, 30)]
    out = embed_clusters(audio, segs, embedder.load_extractor(_REAL))
    assert len(out) == 2
    assert all(c.embedding.shape[0] > 100 for c in out)
