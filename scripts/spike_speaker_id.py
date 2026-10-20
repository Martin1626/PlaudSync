"""Speaker-ID spike — is the named history big enough to bootstrap a voice gallery?

Test 2 (read-only): walks recordings of the last N days (default 60), takes the best transcript
(`transaction_polish`, else `transaction`) and counts speaker labels the user
named by hand (`speaker` differs from `original_speaker` and is not a default
"Speaker N" label).

    python scripts/spike_speaker_id.py stats [--days 60] [--limit N] [--delay 1.0] [--refresh] [--show-names]
    python scripts/spike_speaker_id.py loo [--model campplus|resnet34] [--download N] [--days 60] [--show-names]
    python scripts/spike_speaker_id.py review [--model campplus] [--out DIR]
    python scripts/spike_speaker_id.py ready [--n 10] [--delay 1.0]

`review` (local only) writes DIR/index.html with audio clips of every doubtful
leave-one-out case — wrong person, stranger resembling a gallery person,
correct but below the production threshold — for manual listening. The page
holds voices and real names: keep it local, delete it after review.

Test 1 (`loo`): leave-one-recording-out. Each Plaud cluster (original_speaker)
of a recording gets one sherpa-onnx embedding; it is matched against
per-person centroids built from all OTHER recordings. Clusters whose person
appears in no other recording are impostors (must be rejected -> FAR). Uses
only cached transcripts + audio already on disk; --download N first fetches N
more recordings from the last --days, chosen to widen person coverage.

API budget: one listing page per 50 recordings, then /file/detail + one S3
download per recording NOT yet in the cache, spaced by --delay seconds.

Reports per person: recordings, segments, seconds of speech, plus the
consistency signals that matter for embedding enrollment (one name split over
several diarization clusters, one cluster carrying several names, short
segments).

Privacy: names are masked as P01, P02, ... unless --show-names. No titles are
printed. Transcript segments are cached outside the repo in
%LOCALAPPDATA%/plaudsync/spike_speaker_cache so later tests (leave-one-out
accuracy) reuse them without refetching.

Requires PLAUD_API_TOKEN in env (.env auto-loaded).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf
from dotenv import load_dotenv

from plaudsync.auth import load_token
from plaudsync.plaud_client import ContentItem, PlaudClient

TRANSCRIPT_TYPES = ("transaction_polish", "transaction")
DEFAULT_LABEL = re.compile(r"^Speaker \d+$")
CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "plaudsync" / "spike_speaker_cache"
SEGMENTS_DIR = CACHE_DIR / "segments"
# Rough lower bounds for a usable enrollment: embedding models degrade below
# ~1.5 s per segment, and a centroid wants tens of seconds of speech.
SHORT_SEGMENT_S = 1.5
MIN_ENROLL_S = 30.0


# ---------------------------------------------------------------- fetch + cache

def fetch_segments(client: PlaudClient, rec_id: str) -> list[dict] | None:
    detail = client.fetch_detail(rec_id)
    by_type: dict[str, ContentItem] = {
        it.data_type: it for it in detail.content_list if it.task_status == 1 and it.data_link
    }
    item = next((by_type[t] for t in TRANSCRIPT_TYPES if t in by_type), None)
    if item is None:
        return None
    data = json.loads(client.download_content_text(item))
    return data if isinstance(data, list) else None


def load_segments(client: PlaudClient, rec_id: str, refresh: bool, delay: float) -> list[dict] | None:
    path = SEGMENTS_DIR / f"{rec_id}.json"
    if path.exists() and not refresh:
        cached = json.loads(path.read_text(encoding="utf-8"))
        return cached.get("segments")
    time.sleep(delay)  # be gentle with Plaud: only uncached fetches cost API calls
    segments = fetch_segments(client, rec_id)
    path.write_text(json.dumps({"id": rec_id, "segments": segments}, ensure_ascii=False), encoding="utf-8")
    return segments


# ---------------------------------------------------------------- stats

def is_named(seg: dict) -> bool:
    speaker = str(seg.get("speaker") or "").strip()
    original = str(seg.get("original_speaker") or "").strip()
    return bool(speaker) and not DEFAULT_LABEL.match(speaker) and speaker != original


def seg_seconds(seg: dict) -> float:
    return max(0.0, ((seg.get("end_time") or 0) - (seg.get("start_time") or 0)) / 1000)


@dataclass
class Person:
    recordings: set[str] = field(default_factory=set)
    segments: int = 0
    seconds: float = 0.0
    short_segments: int = 0
    seconds_per_recording: dict[str, float] = field(default_factory=lambda: defaultdict(float))


@dataclass
class History:
    total: int = 0
    no_transcript: int = 0
    with_named: int = 0
    total_seconds: float = 0.0
    named_seconds: float = 0.0
    named_rec_seconds: float = 0.0       # all speech inside recordings that have >=1 name
    named_rec_named_seconds: float = 0.0
    split_names: int = 0                 # (recording, name) spread over >1 original cluster
    mixed_clusters: int = 0              # (recording, cluster) carrying >1 name
    persons: dict[str, Person] = field(default_factory=lambda: defaultdict(Person))
    segment_lengths: list[float] = field(default_factory=list)


def add_recording(h: History, rec_id: str, segments: list[dict]) -> None:
    rec_total = sum(seg_seconds(s) for s in segments)
    h.total_seconds += rec_total
    named = [s for s in segments if is_named(s)]
    if not named:
        return
    h.with_named += 1
    h.named_rec_seconds += rec_total
    clusters_of_name: dict[str, set[str]] = defaultdict(set)
    names_of_cluster: dict[str, set[str]] = defaultdict(set)
    for seg in named:
        name = str(seg["speaker"]).strip()
        secs = seg_seconds(seg)
        p = h.persons[name]
        p.recordings.add(rec_id)
        p.segments += 1
        p.seconds += secs
        p.seconds_per_recording[rec_id] += secs
        p.short_segments += secs < SHORT_SEGMENT_S
        h.named_seconds += secs
        h.named_rec_named_seconds += secs
        h.segment_lengths.append(secs)
        cluster = str(seg.get("original_speaker") or "").strip()
        clusters_of_name[name].add(cluster)
        names_of_cluster[cluster].add(name)
    h.split_names += sum(len(c) > 1 for c in clusters_of_name.values())
    h.mixed_clusters += sum(len(n) > 1 for n in names_of_cluster.values())


def pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:5.1f} %" if whole else "    - "


def report(h: History, show_names: bool) -> None:
    print("\n== Recordings")
    print(f"  total:                  {h.total}")
    print(f"  without transcript:     {h.no_transcript}")
    print(f"  with >=1 named speaker: {h.with_named}  ({pct(h.with_named, h.total - h.no_transcript).strip()} of transcribed)")
    print(f"  speech total:           {h.total_seconds / 3600:6.1f} h")
    print(f"  speech named:           {h.named_seconds / 3600:6.1f} h  ({pct(h.named_seconds, h.total_seconds).strip()})")
    print(f"  named share inside recordings with names: {pct(h.named_rec_named_seconds, h.named_rec_seconds).strip()}")

    print("\n== Consistency (KC5 signals)")
    print(f"  name split over >1 Plaud cluster in one recording: {h.split_names}")
    print(f"  Plaud cluster carrying >1 name in one recording:   {h.mixed_clusters}")
    if h.segment_lengths:
        lengths = sorted(h.segment_lengths)
        short = sum(x < SHORT_SEGMENT_S for x in lengths)
        print(f"  named segment length: median {statistics.median(lengths):.1f} s, "
              f"p10 {lengths[len(lengths) // 10]:.1f} s, <{SHORT_SEGMENT_S} s: {pct(short, len(lengths)).strip()}")

    ranked = sorted(h.persons.items(), key=lambda kv: kv[1].seconds, reverse=True)
    print(f"\n== Persons ({len(ranked)})")
    print(f"  {'person':<24} {'recs':>4} {'segs':>5} {'speech':>8} {'recs>=30s':>9} {'short':>6}")
    for i, (name, p) in enumerate(ranked, 1):
        label = name if show_names else f"P{i:02d}"
        enroll_recs = sum(s >= MIN_ENROLL_S for s in p.seconds_per_recording.values())
        print(f"  {label:<24} {len(p.recordings):>4} {p.segments:>5} {p.seconds / 60:7.1f}m "
              f"{enroll_recs:>9} {pct(p.short_segments, p.segments)}")

    # Leave-one-recording-out needs the person in >=2 recordings, each with enough speech.
    loo = [p for _, p in ranked if sum(s >= MIN_ENROLL_S for s in p.seconds_per_recording.values()) >= 2]
    print("\n== Readiness for test 1 (leave-one-recording-out)")
    print(f"  persons in >=2 recordings with >={MIN_ENROLL_S:.0f} s each: {len(loo)}")
    print(f"  persons in exactly 1 recording (no held-out test possible): "
          f"{sum(len(p.recordings) == 1 for _, p in ranked)}")
    verdict = "GO" if len(loo) >= 3 else "NO-GO"
    print(f"  verdict: {verdict} (needs >=3 testable persons for a meaningful precision/FAR estimate)")


# ---------------------------------------------------------------- test 1: leave-one-recording-out

AUDIO_DIR = CACHE_DIR / "audio"
MODELS_DIR = CACHE_DIR.parent / "spike_speaker_models"
MODELS = {
    "campplus": "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
    "resnet34": "wespeaker_en_voxceleb_resnet34.onnx",
}
MIN_CLUSTER_S = 10.0     # a Plaud cluster with less speech is neither enrolled nor tested
MAX_CLUSTER_S = 120.0    # longest segments first up to this cap; bounds CPU per cluster
THRESHOLDS = [x / 100 for x in range(20, 85, 5)]
KC = {"precision": 0.95, "coverage": 0.50, "cpu_per_h": 60.0, "far": 0.02}  # KC1, KC2, KC3, KC4


def named_recordings() -> dict[str, list[dict]]:
    out = {}
    for path in SEGMENTS_DIR.glob("*.json"):
        segments = json.loads(path.read_text(encoding="utf-8")).get("segments")
        if segments and any(is_named(s) for s in segments):
            out[path.stem] = segments
    return out


def local_audio() -> dict[str, Path]:
    """Audio the regular sync already put on disk (state.db) plus earlier spike downloads."""
    out = {p.stem: p for p in AUDIO_DIR.glob("*.ogg")}
    root = os.environ.get("PLAUDSYNC_STATE_ROOT")
    db = Path(root) / ".plaudsync" / "state.db" if root else None
    if root is None or db is None or not db.exists():
        return out
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        for rec_id, local in conn.execute("SELECT plaud_id, local_path FROM recordings"):
            if not local:
                continue
            path = Path(local) if Path(local).is_absolute() else Path(root) / local
            if path.suffix.lower() == ".mp3" and path.exists():  # Plaud ".mp3" is OGG Opus 16 kHz
                out.setdefault(rec_id, path)
    finally:
        conn.close()
    return out


def people_in(segments: list[dict]) -> set[str]:
    return {str(s["speaker"]).strip() for s in segments if is_named(s)}


def pick_downloads(named: dict[str, list[dict]], audio: dict[str, Path], allowed: set[str], n: int) -> list[str]:
    """Greedy: prefer recordings whose people have the fewest audio-backed recordings so far."""
    people = {rid: people_in(segs) for rid, segs in named.items()}
    have = Counter(p for rid in audio if rid in people for p in people[rid])
    candidates = [rid for rid in named if rid not in audio and rid in allowed]
    picked: list[str] = []
    while candidates and len(picked) < n:
        best = max(candidates, key=lambda r: sum(1 / (1 + have[p]) for p in people[r]))
        candidates.remove(best)
        picked.append(best)
        have.update(people[best])
    return picked


def download(client: PlaudClient, rec_ids: list[str], delay: float) -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for i, rec_id in enumerate(rec_ids, 1):
        time.sleep(delay)
        tmp = AUDIO_DIR / f"{rec_id}.part"
        with tmp.open("wb") as fh:
            for chunk in client.download_audio(rec_id):
                fh.write(chunk)
        tmp.replace(AUDIO_DIR / f"{rec_id}.ogg")
        print(f"  downloaded {i}/{len(rec_ids)}", flush=True)


@dataclass
class Trial:
    rec_id: str
    cluster: str             # Plaud original_speaker label inside that recording
    truth: str | None        # name the user gave this cluster; None = left as "Speaker N"
    seconds: float
    emb: np.ndarray


def cluster_segments(segments: list[dict]) -> dict[str, list[dict]]:
    """Usable segments (timed, >= SHORT_SEGMENT_S) grouped by Plaud diarization cluster."""
    clusters: dict[str, list[dict]] = defaultdict(list)
    for seg in segments:
        cluster = str(seg.get("original_speaker") or seg.get("speaker") or "").strip()
        timed = seg.get("start_time") is not None and seg.get("end_time") is not None
        if cluster and timed and seg_seconds(seg) >= SHORT_SEGMENT_S:
            clusters[cluster].append(seg)
    return clusters


def cluster_trials(extractor: sherpa_onnx.SpeakerEmbeddingExtractor, rec_id: str,
                   segments: list[dict], path: Path) -> tuple[list[Trial], float, float]:
    """Embed every Plaud cluster of one recording. Returns trials, CPU seconds, audio seconds."""
    cpu0 = time.process_time()
    # Seek per segment instead of decoding the whole file: a 2 h recording is ~0.5 GB as float32.
    audio_file = sf.SoundFile(str(path))
    sr = audio_file.samplerate
    audio_s = audio_file.frames / sr
    if max((s.get("end_time") or 0) for s in segments) / 1000 > audio_s + 5:
        print("  skip: transcript longer than audio")
        audio_file.close()
        return [], time.process_time() - cpu0, 0.0

    def read(seg: dict) -> np.ndarray:
        a = min(int(seg["start_time"] * sr / 1000), audio_file.frames)
        b = min(int(seg["end_time"] * sr / 1000), audio_file.frames)  # transcript may overrun audio by <=5 s
        if b <= a:
            return np.zeros(0, dtype=np.float32)
        audio_file.seek(a)
        return audio_file.read(b - a, dtype="float32", always_2d=True).mean(axis=1)

    trials = []
    for cluster, segs in cluster_segments(segments).items():
        total = sum(seg_seconds(s) for s in segs)
        if total < MIN_CLUSTER_S:
            continue
        names = Counter(str(s["speaker"]).strip() for s in segs if is_named(s))
        chosen, used = [], 0.0
        for seg in sorted(segs, key=seg_seconds, reverse=True):
            if used >= MAX_CLUSTER_S:
                break
            chunk = read(seg)
            if chunk.size:
                chosen.append(chunk)
                used += len(chunk) / sr
        if not chosen:
            continue
        stream = extractor.create_stream()
        stream.accept_waveform(sample_rate=sr, waveform=np.concatenate(chosen))
        stream.input_finished()
        emb = np.array(extractor.compute(stream), dtype=np.float32)
        trials.append(Trial(rec_id, cluster, names.most_common(1)[0][0] if names else None, total,
                            emb / (np.linalg.norm(emb) + 1e-9)))
    audio_file.close()
    return trials, time.process_time() - cpu0, audio_s


Scored = tuple[Trial, str, float, bool]  # trial, best gallery name, best score, truth is enrolled


def score_trials(trials: list[Trial]) -> list[Scored]:
    """Leave-one-recording-out: the gallery holds per-person centroids from every OTHER recording."""
    by_name: dict[str, list[Trial]] = defaultdict(list)
    for t in trials:
        if t.truth:
            by_name[t.truth].append(t)
    out = []
    for t in trials:
        names, centroids = [], []
        for name, ts in by_name.items():
            others = [x.emb for x in ts if x.rec_id != t.rec_id]
            if others:
                c = np.mean(others, axis=0)
                names.append(name)
                centroids.append(c / (np.linalg.norm(c) + 1e-9))
        if not names:
            continue
        scores = np.stack(centroids) @ t.emb
        best = int(np.argmax(scores))
        out.append((t, names[best], float(scores[best]), t.truth in names))
    return out


def metrics(scored: list[Scored], th: float) -> dict[str, float]:
    named = [x for x in scored if x[0].truth]
    genuine = [x for x in named if x[3]]
    impostor = [x for x in named if not x[3]]
    accepted = [x for x in named if x[2] >= th]
    tp = [x for x in accepted if x[3] and x[1] == x[0].truth]
    fa = [x for x in accepted if not x[3]]
    unnamed = [x for x in scored if not x[0].truth]
    return {
        "precision": len(tp) / len(accepted) if accepted else 1.0,
        "coverage": len(tp) / len(genuine) if genuine else 0.0,
        "coverage_s": sum(x[0].seconds for x in tp) / (sum(x[0].seconds for x in genuine) or 1),
        "far": len(fa) / len(impostor) if impostor else 0.0,
        "wrong": len(accepted) - len(tp) - len(fa),
        "fa": len(fa),
        "unnamed_labeled": sum(x[2] >= th for x in unnamed) / (len(unnamed) or 1),
    }


def embeddings_path(model: str) -> Path:
    return CACHE_DIR / f"embeddings_{model}.npz"


def embed_all(model: str, named: dict[str, list[dict]], audio: dict[str, Path]) -> tuple[list[Trial], float, float]:
    """Embed all usable recordings and cache the trials so `review` need not recompute them."""
    usable = sorted(rid for rid in named if rid in audio)
    print(f"  recordings with named speakers + local audio: {len(usable)}")
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(MODELS_DIR / MODELS[model]), num_threads=1, provider="cpu")
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
    trials: list[Trial] = []
    cpu_total = audio_total = 0.0
    for i, rid in enumerate(usable, 1):
        ts, cpu, audio_s = cluster_trials(extractor, rid, named[rid], audio[rid])
        trials += ts
        cpu_total += cpu
        audio_total += audio_s
        if i % 10 == 0:
            print(f"  ... {i}/{len(usable)} embedded", flush=True)
    if not trials:
        return trials, cpu_total, audio_total
    np.savez(embeddings_path(model),
             rec_id=np.array([t.rec_id for t in trials]), cluster=np.array([t.cluster for t in trials]),
             truth=np.array([t.truth or "" for t in trials]), seconds=np.array([t.seconds for t in trials]),
             emb=np.stack([t.emb for t in trials]))
    return trials, cpu_total, audio_total


def load_trials(model: str) -> list[Trial] | None:
    path = embeddings_path(model)
    if not path.exists():
        return None
    d = np.load(path)
    return [Trial(str(r), str(c), str(t) or None, float(s), e)
            for r, c, t, s, e in zip(d["rec_id"], d["cluster"], d["truth"], d["seconds"], d["emb"])]


def cmd_loo(client: PlaudClient | None, model: str, download_n: int, days: int, delay: float,
            show_names: bool) -> int:
    named = named_recordings()
    audio = local_audio()
    if download_n and client is not None:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        recent = {m.plaud_id for m in client.list_recordings(since=since)}
        download(client, pick_downloads(named, audio, recent, download_n), delay)
        audio = local_audio()
    trials, cpu_total, audio_total = embed_all(model, named, audio)
    scored = score_trials(trials)
    seconds_by_name: Counter[str] = Counter()
    for t in trials:
        if t.truth:
            seconds_by_name[t.truth] += t.seconds
    alias = {name: (name if show_names else f"Q{i:02d}")
             for i, (name, _) in enumerate(seconds_by_name.most_common(), 1)}
    named_scored = [x for x in scored if x[0].truth]
    cpu_per_h = cpu_total / (audio_total / 3600) if audio_total else 0.0
    print(f"\n== Data ({model})")
    print(f"  persons: {len(seconds_by_name)}, named clusters tested: {len(named_scored)} "
          f"(genuine {sum(x[3] for x in named_scored)}, impostor {sum(not x[3] for x in named_scored)}), "
          f"unnamed clusters: {len(scored) - len(named_scored)}")
    print(f"  CPU: {cpu_total:.1f} s for {audio_total / 3600:.1f} h audio = {cpu_per_h:.1f} s per audio hour (1 thread)")

    print("\n== Threshold sweep")
    print(f"  {'th':>4} {'precision':>9} {'coverage':>8} {'cov_s':>6} {'FAR':>6} {'wrong':>5} {'FA':>3} {'unnamed->name':>13}")
    best_th = None
    for th in THRESHOLDS:
        m = metrics(scored, th)
        print(f"  {th:4.2f} {m['precision']:9.1%} {m['coverage']:8.1%} {m['coverage_s']:6.1%} "
              f"{m['far']:6.1%} {m['wrong']:5d} {m['fa']:3d} {m['unnamed_labeled']:13.1%}")
        if best_th is None and m["precision"] >= KC["precision"] and m["far"] <= KC["far"]:
            best_th = th

    print("\n== Verdict vs kill criteria")
    if best_th is None:
        print("  no threshold reaches KC1 precision >= 95 % together with KC4 FAR <= 2 % -> FAIL")
        return 1
    m = metrics(scored, best_th)
    checks = {
        f"KC1 precision >= {KC['precision']:.0%}": m["precision"] >= KC["precision"],
        f"KC2 coverage >= {KC['coverage']:.0%}": m["coverage"] >= KC["coverage"],
        f"KC3 CPU <= {KC['cpu_per_h']:.0f} s/h": cpu_per_h <= KC["cpu_per_h"],
        f"KC4 FAR <= {KC['far']:.0%}": m["far"] <= KC["far"],
    }
    print(f"  operating threshold: {best_th:.2f} (lowest passing KC1+KC4)")
    for label, ok in checks.items():
        print(f"  {label}: {'PASS' if ok else 'FAIL'}")
    top = seconds_by_name.most_common(1)[0][0]
    rest = metrics([x for x in scored if x[0].truth != top], best_th)
    print(f"  without {alias[top]} (likely the account owner): precision {rest['precision']:.1%}, "
          f"coverage {rest['coverage']:.1%}")

    errors = [x for x in named_scored if x[2] >= best_th and x[1] != x[0].truth]
    if errors:
        print("\n== Errors at operating threshold (check for name variants with --show-names)")
        for t, pred, score, enrolled in sorted(errors, key=lambda x: -x[2]):
            kind = "wrong person" if enrolled else "stranger accepted"
            print(f"  {alias[t.truth or '']} -> {alias.get(pred, pred)}  score {score:.2f}  ({kind})")
    return 0 if all(checks.values()) else 1


# ---------------------------------------------------------------- manual review of mismatches

PROD_THRESHOLD = 0.75
CLIP_S = 12.0
KIND_TEXT = {
    "wrong": ("Model určil jinou osobu", "Poslechněte si, komu testovaný hlas patří."),
    "stranger": ("Neznámý hlas podobný osobě z galerie",
                 "Jméno z Plaudu je jen v této nahrávce. Nejde o stejného člověka pod jiným jménem?"),
    "low": ("Správně, ale s nízkou jistotou",
            "Model souhlasí s Plaudem, ale skóre je pod produkčním prahem. Je jméno v Plaudu správně?"),
}
VERDICTS = ["", "stejná osoba", "jiná osoba", "nejde poznat"]


def recording_info() -> dict[str, tuple[str, str]]:
    """plaud_id -> (date, title) from the sync state, so the reviewer can find the recording in Plaud."""
    root = os.environ.get("PLAUDSYNC_STATE_ROOT")
    db = Path(root) / ".plaudsync" / "state.db" if root else None
    if db is None or not db.exists():
        return {}
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        return {pid: ((created or "")[:10], title or "")
                for pid, created, title in conn.execute("SELECT plaud_id, created_at_plaud, title FROM recordings")}
    finally:
        conn.close()


def write_clip(audio_path: Path, segs: list[dict], out: Path) -> str:
    """Longest segments up to CLIP_S as a 16-bit WAV; returns where they start (m:ss) in the recording."""
    chosen, starts, used = [], [], 0.0
    with sf.SoundFile(str(audio_path)) as f:
        sr = f.samplerate
        for seg in sorted(segs, key=seg_seconds, reverse=True):
            if used >= CLIP_S:
                break
            a = min(int(seg["start_time"] * sr / 1000), f.frames)
            b = min(int(seg["end_time"] * sr / 1000), f.frames, a + int((CLIP_S - used) * sr))
            if b <= a:
                continue
            f.seek(a)
            chosen += [f.read(b - a, dtype="float32", always_2d=True).mean(axis=1), np.zeros(int(0.4 * sr), np.float32)]
            starts.append(seg["start_time"] // 1000)
            used += (b - a) / sr
    sf.write(str(out), np.concatenate(chosen) if chosen else np.zeros(1, np.float32), sr, subtype="PCM_16")
    return ", ".join(f"{s // 60}:{s % 60:02d}" for s in sorted(starts))


def review_cases(trials: list[Trial]) -> list[tuple[str, Trial, str, float]]:
    cases = []
    for t, pred, score, enrolled in score_trials(trials):
        if not t.truth:
            continue
        if enrolled and pred != t.truth and score >= 0.5:
            kind = "wrong"
        elif not enrolled and score >= 0.6:
            kind = "stranger"
        elif enrolled and pred == t.truth and score < PROD_THRESHOLD:
            kind = "low"
        else:
            continue
        cases.append((kind, t, pred, score))
    order = list(KIND_TEXT)
    return sorted(cases, key=lambda c: (order.index(c[0]), -c[3]))


def cmd_review(model: str, out_dir: Path, recompute: bool) -> int:
    trials = None if recompute else load_trials(model)
    if trials is None:
        print(f"  computing embeddings for {model} (no API calls)")
        trials, _, _ = embed_all(model, named_recordings(), local_audio())
    else:
        written = datetime.fromtimestamp(embeddings_path(model).stat().st_mtime)
        print(f"  using cached embeddings from {written:%Y-%m-%d %H:%M} (--recompute after new downloads)")
    named, audio, info = named_recordings(), local_audio(), recording_info()

    def available(t: Trial) -> bool:
        return t.rec_id in named and t.rec_id in audio and t.cluster in cluster_segments(named[t.rec_id])
    clips = out_dir / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    for old in clips.glob("*.wav"):
        old.unlink()

    def reference(name: str, test: Trial) -> Trial:
        others = [x for x in trials if x.truth == name and x.rec_id != test.rec_id]
        return max(others, key=lambda x: float(x.emb @ test.emb))

    def voice_block(label: str, t: Trial, file: str) -> str:
        segs = cluster_segments(named[t.rec_id])[t.cluster]
        at = write_clip(audio[t.rec_id], segs, clips / file)
        date, title = info.get(t.rec_id, ("", ""))
        return (f'<div class="voice"><div class="who">{html.escape(label)}</div>'
                f'<audio controls preload="none" src="clips/{file}"></audio>'
                f'<div class="meta">{html.escape(date)} · {html.escape(title) or html.escape(t.rec_id)}'
                f' · čas {at}</div></div>')

    # Cached trials can outlive their audio/transcript files; drop cases we cannot play.
    cases = []
    for kind, t, pred, score in review_cases(trials):
        refs = [reference(pred, t)] + ([reference(t.truth or "", t)] if kind == "wrong" else [])
        if all(available(x) for x in [t, *refs]):
            cases.append((kind, t, pred, score, refs))
        else:
            print("  skip case: audio or transcript no longer on disk")
    rows = []
    for i, (kind, t, pred, score, refs) in enumerate(cases, 1):
        heading, question = KIND_TEXT[kind]
        truth = t.truth or ""
        voices = [voice_block(f"Testovaný hlas — v Plaudu „{truth}“", t, f"{i:02d}_test.wav"),
                  voice_block(f"Referenční hlas — „{pred}“ (skóre {score:.2f})", refs[0], f"{i:02d}_pred.wav")]
        if kind == "wrong":
            voices.append(voice_block(f"Referenční hlas — „{truth}“", refs[1], f"{i:02d}_truth.wav"))
        options = "".join(f"<option>{v}</option>" for v in VERDICTS)
        rows.append(f'<section class="case"><h2>{i}. {heading}</h2><p>{question}</p>{"".join(voices)}'
                    f'<label>Testovaný a referenční hlas „{html.escape(pred)}“ jsou: '
                    f'<select data-case="{i}">{options}</select></label></section>')
        print(f"  case {i}: {kind} score {score:.2f}", flush=True)

    page = REVIEW_HTML.replace("{{COUNT}}", str(len(cases))).replace("{{CASES}}", "\n".join(rows))
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    print(f"\n  {len(cases)} cases -> {out_dir / 'index.html'}")
    return 0


REVIEW_HTML = """<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kontrola hlasů</title>
<style>
:root { --bg: #fafaf8; --fg: #1d1d1b; --muted: #6b6b66; --card: #fff; --line: #e2e1dc; --accent: #2f5d8a; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #1a1a19; --fg: #ebebe6; --muted: #a3a39c; --card: #242423; --line: #3a3a37; --accent: #8ab4dc; }
}
body { background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif; margin: 0 auto; max-width: 860px; padding: 24px 16px 64px; }
h1 { font-size: 1.4rem; margin: 0 0 4px; } h2 { font-size: 1.05rem; margin: 0 0 4px; }
p { color: var(--muted); margin: 0 0 12px; }
.case { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 16px; margin: 16px 0; }
.voice { border-top: 1px solid var(--line); padding: 10px 0; } .who { font-weight: 600; }
.meta { color: var(--muted); font-size: 0.85rem; overflow-wrap: anywhere; }
audio { width: 100%; margin: 6px 0 2px; }
select { font: inherit; margin-left: 4px; }
textarea { width: 100%; box-sizing: border-box; min-height: 140px; font: 13px/1.4 ui-monospace, monospace; background: var(--card); color: var(--fg); border: 1px solid var(--line); border-radius: 6px; padding: 8px; }
button { font: inherit; padding: 6px 14px; border-radius: 6px; border: 1px solid var(--accent); background: var(--accent); color: var(--bg); cursor: pointer; }
</style></head><body>
<h1>Kontrola hlasů ({{COUNT}} případů)</h1>
<p>Lokální stránka ze spike testu přesnosti. Obsahuje hlasové nahrávky — nesdílet, po kontrole smazat celou složku.
U každého případu si poslechněte hlasy a vyberte verdikt. Dole pak zkopírujte souhrn a pošlete ho Claudovi.</p>
{{CASES}}
<h2>Souhrn</h2>
<textarea id="summary" readonly></textarea>
<p><button id="copy">Zkopírovat souhrn</button></p>
<script>
const selects = [...document.querySelectorAll("select[data-case]")];
function update() {
  document.getElementById("summary").value = selects
    .map(s => `${s.dataset.case}: ${s.value || "(nevyplněno)"}`).join("\\n");
}
selects.forEach(s => s.addEventListener("change", update));
document.getElementById("copy").addEventListener("click", () => {
  const box = document.getElementById("summary"); box.select();
  navigator.clipboard ? navigator.clipboard.writeText(box.value) : document.execCommand("copy");
});
update();
</script></body></html>
"""


# ---------------------------------------------------------------- tests 4+5: readiness + summary label forms

# Any "speaker-ish word + number" so localized or reformatted labels show up too.
LABEL_FORMS = re.compile(r"\b(speaker|spk|mluvčí|řečník|účastník|participant)[\s_#-]*\d+\b", re.IGNORECASE)


def label_shape(match: str) -> str:
    return re.sub(r"\d+", "N", match)


def cmd_ready(client: PlaudClient, n: int, delay: float) -> int:
    """Read-only: listing flags vs. content task_status, and label shapes inside summaries."""
    body = client._session.get(f"{client._base_url}/file/simple/web",
                               params={"skip": 0, "limit": n, "is_trash": 0}, timeout=60).json()
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    shapes: Counter[str] = Counter()
    contexts: Counter[str] = Counter()
    print(f"  {'age':>7} {'trans':>5} {'summ':>4} {'pull':>4}  content task_status            notes")
    for raw in body.get("data_file_list") or []:
        time.sleep(delay)
        detail = client.fetch_detail(raw["id"])
        status = " ".join(f"{it.data_type}={it.task_status}" for it in detail.content_list)
        time.sleep(delay)
        notes = client._session.get(f"{client._base_url}/ai/query_note",
                                    headers={"file-id": raw["id"]}, timeout=60).json().get("data") or []
        note_info = []
        for note in notes:
            text = note.get("data_content") or ""
            if not isinstance(text, str):
                text = json.dumps(text, ensure_ascii=False)
            wrapped = text.lstrip().startswith("{")
            found = 0
            for m in LABEL_FORMS.finditer(text):
                found += 1
                shapes[label_shape(m.group(0))] += 1
                # Markup right around the label (bold, colon, list) decides how replace must match.
                before, after = text[max(0, m.start() - 2):m.start()], text[m.end():m.end() + 2]
                contexts[re.sub(r"[^\W\d_]", "a", before) + "<L>" + re.sub(r"[^\W\d_]", "a", after)] += 1
            note_info.append(f"{note.get('data_type')}{'(json)' if wrapped else ''}:{found}")
        age_h = (now_ms - (raw.get("start_time") or 0)) / 3_600_000
        print(f"  {age_h:6.0f}h {str(raw.get('is_trans')):>5} {str(raw.get('is_summary')):>4} "
              f"{raw.get('wait_pull')!s:>4}  {status:<30} {', '.join(note_info) or '-'}")
    print("\n== Label shapes in notes (test 5)")
    for shape, count in shapes.most_common():
        print(f"  {shape!r:<20} x{count}")
    print("\n== Markup around labels (a = letter, <L> = label)")
    for ctx, count in contexts.most_common(10):
        print(f"  {ctx!r:<20} x{count}")
    return 0


# ---------------------------------------------------------------- main

def cmd_stats(client: PlaudClient, days: int, limit: int | None, delay: float,
              refresh: bool, show_names: bool) -> int:
    SEGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    print(f"  scanning recordings since {since[:10]}")
    h = History()
    for i, meta in enumerate(client.list_recordings(since=since)):
        if limit is not None and i >= limit:
            break
        h.total += 1
        segments = load_segments(client, meta.plaud_id, refresh, delay)
        if not segments:
            h.no_transcript += 1
        else:
            add_recording(h, meta.plaud_id, segments)
        if h.total % 25 == 0:
            print(f"  ... {h.total} recordings scanned", flush=True)
    report(h, show_names)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_stats = sub.add_parser("stats")
    p_stats.add_argument("--days", type=int, default=60)
    p_stats.add_argument("--limit", type=int)
    p_stats.add_argument("--delay", type=float, default=1.0, help="seconds between uncached fetches")
    p_stats.add_argument("--refresh", action="store_true", help="ignore cached segments")
    p_stats.add_argument("--show-names", action="store_true")
    p_loo = sub.add_parser("loo")
    p_loo.add_argument("--model", choices=sorted(MODELS), default="campplus")
    p_loo.add_argument("--download", type=int, default=0, help="fetch N more recordings' audio first")
    p_loo.add_argument("--days", type=int, default=60)
    p_loo.add_argument("--delay", type=float, default=1.0, help="seconds between downloads")
    p_loo.add_argument("--show-names", action="store_true")
    p_review = sub.add_parser("review")
    p_review.add_argument("--model", choices=sorted(MODELS), default="campplus")
    p_review.add_argument("--out", type=Path, default=CACHE_DIR / "review")
    p_review.add_argument("--recompute", action="store_true", help="ignore cached embeddings")
    p_ready = sub.add_parser("ready")
    p_ready.add_argument("--n", type=int, default=10, help="newest N recordings")
    p_ready.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    load_dotenv()
    if args.cmd == "review":
        return cmd_review(args.model, args.out, args.recompute)  # local only
    if args.cmd == "loo" and not args.download:
        return cmd_loo(None, args.model, 0, args.days, args.delay, args.show_names)  # no API calls at all
    with PlaudClient(load_token()) as client:
        if args.cmd == "loo":
            return cmd_loo(client, args.model, args.download, args.days, args.delay, args.show_names)
        if args.cmd == "ready":
            return cmd_ready(client, args.n, args.delay)
        return cmd_stats(client, args.days, args.limit, args.delay, args.refresh, args.show_names)


if __name__ == "__main__":
    sys.exit(main())
