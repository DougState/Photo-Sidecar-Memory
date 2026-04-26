"""Style miner — discovers recurring post-processing styles from a PSD/PSB corpus.

Pipeline:
  Phase 1: walk the corpus, extract per-file Fingerprints to fingerprints.jsonl
  Phase 2: detect iteration chains (sibling-stem and folder-nested), diff
           save->save into chain_diffs.jsonl
  Phase 3: render thumbnails (embedded preview preferred, low-res composite
           fallback) into thumbs/
  Phase 4: vectorize fingerprints, cluster (HDBSCAN -> KMeans fallback) into
           candidate_styles.json
  Phase 5: send representative thumbnails per cluster to Claude for naming,
           write styles_draft.md

The phases are independently re-runnable. Outputs are append-only / cache-friendly
so an interrupted run resumes cleanly.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .psd_introspect import (
    ADJUSTMENT_KINDS,
    Fingerprint,
    already_fingerprinted_paths,
    extract_thumbnail,
    introspect,
    read_fingerprints_jsonl,
    write_fingerprint_jsonl,
)


# ---------------------------------------------------------------------------
# File system / corpus walking
# ---------------------------------------------------------------------------

PSD_SUFFIXES = {".psd", ".psb"}


def walk_psd_corpus(source: Path) -> list[Path]:
    """Find all PSD/PSB files under `source`, skipping macOS resource forks
    (`._*`) and hidden directories. Returned in deterministic sorted order
    so resume + run ordering is stable.
    """
    out: list[Path] = []
    for root, dirs, files in os.walk(source):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.startswith("._") or name.startswith("."):
                continue
            suffix = Path(name).suffix.lower()
            if suffix in PSD_SUFFIXES:
                out.append(Path(root) / name)
    return out


# ---------------------------------------------------------------------------
# Phase 1 — fingerprint extraction
# ---------------------------------------------------------------------------

def phase1_extract(
    source: Path,
    working_dir: Path,
    *,
    resume: bool = True,
    limit: int | None = None,
    partial_threshold_bytes: int = 1_000_000_000,
    timeout_seconds: int = 120,
    progress_every: int = 10,
    log: callable | None = None,
) -> Path:
    """Walk the corpus and append a Fingerprint per file to fingerprints.jsonl.

    Args:
        source: corpus root, e.g. /Volumes/Mauna Kea/PS Works
        working_dir: where to write .bridge-assist/styles/...
        resume: skip files already in fingerprints.jsonl
        limit: optional cap on new files processed
        partial_threshold_bytes: files larger than this are recorded as partial
            (size+mtime only, no layer walk) — protects against multi-GB PSBs
        timeout_seconds: per-file ceiling for psd_tools layer walk
        log: optional callable(str) for progress lines

    Returns the fingerprints.jsonl path.
    """
    log = log or (lambda s: None)
    styles_dir = working_dir / "styles"
    fingerprints_path = styles_dir / "fingerprints.jsonl"

    seen = already_fingerprinted_paths(fingerprints_path) if resume else set()
    paths = walk_psd_corpus(source)
    todo = [p for p in paths if str(p) not in seen]
    if limit is not None:
        todo = todo[:limit]

    log(f"Phase 1: {len(paths)} PSD/PSB files in corpus, {len(seen)} already fingerprinted, {len(todo)} to process.")

    started = time.time()
    partials = 0
    errors = 0
    for i, path in enumerate(todo, 1):
        try:
            fp = introspect(
                path,
                root=source,
                partial_threshold_bytes=partial_threshold_bytes,
                timeout_seconds=timeout_seconds,
            )
            write_fingerprint_jsonl(fp, fingerprints_path)
            if fp.partial_introspection:
                partials += 1
            if fp.error:
                errors += 1
            if i % progress_every == 0 or i == len(todo):
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                eta = (len(todo) - i) / rate if rate else 0
                log(f"  [{i}/{len(todo)}] {path.name}  ({rate:.1f} files/s, eta ~{int(eta)}s, partials={partials}, errors={errors})")
        except Exception as e:
            log(f"  [{i}/{len(todo)}] FAILED {path}: {type(e).__name__}: {e}")
            errors += 1

    log(f"Phase 1 done in {time.time()-started:.1f}s. partials={partials}, errors={errors}")
    return fingerprints_path


# ---------------------------------------------------------------------------
# Phase 2 — iteration chain detection + diffs
# ---------------------------------------------------------------------------

CAMERA_PREFIX_RE = re.compile(r"^(_?[A-Z]{2,4}\d{4,6})", re.IGNORECASE)


def _stem_normalized(stem: str) -> str:
    """Strip Photoshop iteration suffixes for chain grouping.

    Removes ' copy', ' copy 2', '_2', ' v3', '@0,25x', trailing digit suffixes,
    and leaves the canonical project stem.
    """
    s = stem
    s = re.sub(r"@[\d,.]+x$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+copy(?:\s*\d+)?$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[_\s\-]v?\d+$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+\(\d+\)$", "", s)
    s = s.strip()
    return s.lower()


@dataclass
class Chain:
    chain_id: str
    folder: str  # folder relpath
    chain_kind: str  # 'folder' (all PSDs in same folder) or 'camera_prefix'
    stem_seed: str
    members: list[Fingerprint] = field(default_factory=list)


def detect_chains(fingerprints: list[Fingerprint]) -> list[Chain]:
    """Group fingerprints into iteration chains.

    Heuristics applied in order:
      1. Folder + normalized-stem: PSDs in the same parent folder whose
         normalized stem matches form one chain.
      2. Camera-prefix: PSDs sharing a D800 prefix (e.g. _MT88026) inside the
         same project tree (top-level folder + subfolder) form a chain — even
         if they live in different leaf folders.

    A single fingerprint can only belong to one chain (camera-prefix wins
    when both apply, since it's the more specific signal).
    """
    by_path: dict[str, Fingerprint] = {fp.path: fp for fp in fingerprints}
    assigned: set[str] = set()
    chains: list[Chain] = []

    # Pass 1: camera-prefix chains across a tier+project root
    by_prefix: dict[tuple, list[Fingerprint]] = defaultdict(list)
    for fp in fingerprints:
        m = CAMERA_PREFIX_RE.match(Path(fp.path).stem)
        if not m:
            continue
        prefix = m.group(1).upper()
        # Use the first 2 levels of project_chain as the project bucket
        bucket = tuple(fp.project_chain[:2]) if len(fp.project_chain) >= 2 else tuple(fp.project_chain)
        by_prefix[(bucket, prefix)].append(fp)

    for (bucket, prefix), members in by_prefix.items():
        if len(members) < 2:
            continue
        chain_id = f"camera::{'/'.join(bucket)}::{prefix}"
        chain = Chain(
            chain_id=chain_id,
            folder="/".join(bucket),
            chain_kind="camera_prefix",
            stem_seed=prefix,
            members=sorted(members, key=lambda f: f.mtime),
        )
        chains.append(chain)
        for m in members:
            assigned.add(m.path)

    # Pass 2: folder + normalized-stem chains
    by_folder_stem: dict[tuple, list[Fingerprint]] = defaultdict(list)
    for fp in fingerprints:
        if fp.path in assigned:
            continue
        folder_key = "/".join(fp.project_chain) if fp.project_chain else Path(fp.path).parent.name
        stem = _stem_normalized(Path(fp.path).stem)
        by_folder_stem[(folder_key, stem)].append(fp)

    for (folder, stem), members in by_folder_stem.items():
        if len(members) < 2:
            # Singletons still get a chain entry so phase 4 sees them.
            for m in members:
                if m.path in assigned:
                    continue
                chain_id = f"single::{folder}::{Path(m.path).stem}"
                chains.append(
                    Chain(
                        chain_id=chain_id,
                        folder=folder,
                        chain_kind="single",
                        stem_seed=Path(m.path).stem,
                        members=[m],
                    )
                )
                assigned.add(m.path)
            continue
        chain_id = f"folder::{folder}::{stem or '_'}"
        chains.append(
            Chain(
                chain_id=chain_id,
                folder=folder,
                chain_kind="folder",
                stem_seed=stem,
                members=sorted(members, key=lambda f: f.mtime),
            )
        )
        for m in members:
            assigned.add(m.path)

    # Sort chains by folder for stable output
    chains.sort(key=lambda c: (c.folder, c.chain_id))
    return chains


def diff_chain(chain: Chain) -> dict:
    """Return a dict describing the save-to-save evolution of a chain."""
    if not chain.members or len(chain.members) < 2:
        return {
            "chain_id": chain.chain_id,
            "folder": chain.folder,
            "chain_kind": chain.chain_kind,
            "members": [_member_summary(m) for m in chain.members],
            "moves": [],
        }

    moves: list[dict] = []
    prev = chain.members[0]
    for cur in chain.members[1:]:
        prev_adj = set((prev.layers or {}).get("adjustment_breakdown", {}).keys())
        cur_adj = set((cur.layers or {}).get("adjustment_breakdown", {}).keys())
        prev_bm = set((prev.layers or {}).get("blend_mode_histogram", {}).keys())
        cur_bm = set((cur.layers or {}).get("blend_mode_histogram", {}).keys())

        moves.append(
            {
                "from": Path(prev.path).name,
                "to": Path(cur.path).name,
                "minutes_between": _minutes_between(prev.mtime, cur.mtime),
                "layer_count_delta": (cur.layers or {}).get("total", 0) - (prev.layers or {}).get("total", 0),
                "added_adjustments": sorted(cur_adj - prev_adj),
                "removed_adjustments": sorted(prev_adj - cur_adj),
                "added_blend_modes": sorted(cur_bm - prev_bm),
                "mask_count_delta": (cur.layers or {}).get("with_mask", 0) - (prev.layers or {}).get("with_mask", 0),
                "size_change_px": _size_change(prev, cur),
            }
        )
        prev = cur

    return {
        "chain_id": chain.chain_id,
        "folder": chain.folder,
        "chain_kind": chain.chain_kind,
        "members": [_member_summary(m) for m in chain.members],
        "moves": moves,
    }


def _member_summary(fp: Fingerprint) -> dict:
    return {
        "path": fp.path,
        "name": Path(fp.path).name,
        "mtime": fp.mtime,
        "size_bytes": fp.size_bytes,
        "layer_count": (fp.layers or {}).get("total", 0),
        "partial": fp.partial_introspection,
    }


def _minutes_between(a: str, b: str) -> int:
    try:
        ta = datetime.fromisoformat(a.replace("Z", "+00:00"))
        tb = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return int((tb - ta).total_seconds() / 60)
    except Exception:
        return 0


def _size_change(a: Fingerprint, b: Fingerprint) -> tuple[int, int]:
    aw = (a.image or {}).get("width", 0) or 0
    ah = (a.image or {}).get("height", 0) or 0
    bw = (b.image or {}).get("width", 0) or 0
    bh = (b.image or {}).get("height", 0) or 0
    return (bw - aw, bh - ah)


def phase2_chains(working_dir: Path, log: callable | None = None) -> Path:
    """Read fingerprints.jsonl, group into chains, write chain_diffs.jsonl."""
    log = log or (lambda s: None)
    styles_dir = working_dir / "styles"
    fp_path = styles_dir / "fingerprints.jsonl"
    out_path = styles_dir / "chain_diffs.jsonl"

    fps = read_fingerprints_jsonl(fp_path)
    chains = detect_chains(fps)
    log(f"Phase 2: {len(fps)} fingerprints -> {len(chains)} chains")

    if out_path.exists():
        out_path.unlink()

    for chain in chains:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(diff_chain(chain), ensure_ascii=False) + "\n")

    log(f"Phase 2 done. wrote {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Phase 3 — thumbnail generation
# ---------------------------------------------------------------------------

def _thumb_filename(fp: Fingerprint) -> str:
    h = hashlib.sha1(fp.path.encode("utf-8")).hexdigest()[:16]
    return f"{h}.jpg"


def phase3_thumbs(
    working_dir: Path,
    *,
    max_size: int = 512,
    composite_threshold_bytes: int = 500_000_000,
    only_for_paths: set[str] | None = None,
    skip_existing: bool = True,
    log: callable | None = None,
) -> Path:
    """Generate thumbnails for every (or a subset of) fingerprint."""
    log = log or (lambda s: None)
    styles_dir = working_dir / "styles"
    thumbs_dir = styles_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    fps = read_fingerprints_jsonl(styles_dir / "fingerprints.jsonl")
    if only_for_paths is not None:
        fps = [fp for fp in fps if fp.path in only_for_paths]

    methods: Counter = Counter()
    for i, fp in enumerate(fps, 1):
        out = thumbs_dir / _thumb_filename(fp)
        if skip_existing and out.exists():
            methods["cached"] += 1
            continue
        if fp.partial_introspection and fp.size_bytes > composite_threshold_bytes:
            methods["skip_size"] += 1
            continue
        ok, method = extract_thumbnail(
            Path(fp.path),
            out,
            max_size=max_size,
            composite_threshold_bytes=composite_threshold_bytes,
        )
        methods[method] += 1
        if i % 25 == 0 or i == len(fps):
            log(f"  thumbs [{i}/{len(fps)}]  {dict(methods)}")

    log(f"Phase 3 done. thumbs={dict(methods)}")
    return thumbs_dir


# ---------------------------------------------------------------------------
# Phase 4 — vectorize + cluster
# ---------------------------------------------------------------------------

# Stable feature ordering — matches the order we emit one-hot/normalized values.
ADJ_FEATURE_ORDER = sorted(set(ADJUSTMENT_KINDS.values()))
BLEND_FEATURE_ORDER = [
    "normal", "multiply", "screen", "overlay", "soft_light", "hard_light",
    "darken", "lighten", "color_dodge", "color_burn", "linear_dodge",
    "linear_burn", "difference", "exclusion", "hue", "saturation",
    "color", "luminosity", "pass_through",
]
STRUCTURAL_FEATURES = [
    "has_text", "has_smart_objects", "is_grayscale", "is_cmyk", "is_rgb",
    "is_high_layer_count", "has_groups", "has_masks_majority",
    "has_dark_blends", "has_light_blends",
]


def _featurize(fp: Fingerprint) -> list[float]:
    layers = fp.layers or {}
    image = fp.image or {}
    total = max(1, layers.get("total", 0))

    adj = layers.get("adjustment_breakdown", {})
    adj_vec = [adj.get(name, 0) / total for name in ADJ_FEATURE_ORDER]

    bm = layers.get("blend_mode_histogram", {})
    bm_vec = [bm.get(name, 0) / total for name in BLEND_FEATURE_ORDER]

    cm = (image.get("color_mode") or "").lower()
    structural = [
        1.0 if layers.get("type_layers", 0) > 0 else 0.0,
        1.0 if layers.get("smart_objects", 0) > 0 else 0.0,
        1.0 if cm == "grayscale" else 0.0,
        1.0 if cm == "cmyk" else 0.0,
        1.0 if cm == "rgb" else 0.0,
        1.0 if total >= 30 else 0.0,
        1.0 if layers.get("groups", 0) > 0 else 0.0,
        1.0 if layers.get("with_mask", 0) >= total / 2 else 0.0,
        1.0 if (bm.get("multiply", 0) + bm.get("color_burn", 0) + bm.get("linear_burn", 0)) >= 1 else 0.0,
        1.0 if (bm.get("screen", 0) + bm.get("color_dodge", 0) + bm.get("linear_dodge", 0)) >= 1 else 0.0,
    ]

    return adj_vec + bm_vec + structural


def feature_names() -> list[str]:
    return (
        [f"adj.{n}" for n in ADJ_FEATURE_ORDER]
        + [f"bm.{n}" for n in BLEND_FEATURE_ORDER]
        + STRUCTURAL_FEATURES
    )


@dataclass
class ClusterRecord:
    cluster_id: int
    label: str  # auto-named later; "" until phase 5
    size: int
    member_paths: list[str] = field(default_factory=list)
    centroid: list[float] = field(default_factory=list)
    feature_summary: dict = field(default_factory=dict)
    representatives: list[str] = field(default_factory=list)


def phase4_cluster(
    working_dir: Path,
    *,
    target_min_clusters: int = 6,
    target_max_clusters: int = 16,
    log: callable | None = None,
) -> Path:
    """Vectorize fingerprints, cluster, write candidate_styles.json.

    Strategy: try HDBSCAN first. If it produces too few clusters or marks
    almost everything as noise, fall back to KMeans with k chosen empirically.
    """
    log = log or (lambda s: None)
    styles_dir = working_dir / "styles"
    out_path = styles_dir / "candidate_styles.json"

    fps = [fp for fp in read_fingerprints_jsonl(styles_dir / "fingerprints.jsonl") if not fp.partial_introspection and fp.layers]
    if not fps:
        log("Phase 4: no fingerprints to cluster.")
        out_path.write_text(json.dumps({"clusters": [], "feature_names": feature_names()}, indent=2))
        return out_path

    import numpy as np
    from sklearn.cluster import HDBSCAN, KMeans

    X = np.array([_featurize(fp) for fp in fps], dtype=float)
    log(f"Phase 4: {X.shape[0]} fingerprints x {X.shape[1]} features")

    labels, algo = _cluster(X, target_min_clusters, target_max_clusters, log)

    clusters = _build_cluster_records(fps, X, labels, algo, log)

    out = {
        "algorithm": algo,
        "feature_names": feature_names(),
        "clusters": [_cluster_to_dict(c) for c in clusters],
    }
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    log(f"Phase 4 done. {len(clusters)} clusters via {algo} -> {out_path}")
    return out_path


def _cluster(X, target_min: int, target_max: int, log) -> tuple[list[int], str]:
    import numpy as np
    from sklearn.cluster import HDBSCAN, KMeans

    n = X.shape[0]
    if n < 8:
        # Too few rows for clustering — every row its own cluster.
        return list(range(n)), f"trivial(n={n})"

    # HDBSCAN attempt
    min_cluster_size = max(3, n // 40)
    h = HDBSCAN(min_cluster_size=min_cluster_size).fit(X)
    h_labels = list(h.labels_)
    h_uniq = {l for l in h_labels if l != -1}
    h_noise = sum(1 for l in h_labels if l == -1)

    if target_min <= len(h_uniq) <= target_max and h_noise < n * 0.5:
        log(f"  HDBSCAN: {len(h_uniq)} clusters, {h_noise} noise (min_cluster_size={min_cluster_size})")
        return h_labels, f"hdbscan(min_cluster_size={min_cluster_size})"

    log(f"  HDBSCAN gave {len(h_uniq)} clusters with {h_noise} noise -> falling back to KMeans")

    # KMeans fallback — pick k by simple silhouette sweep
    from sklearn.metrics import silhouette_score

    best_k = max(target_min, 8)
    best_score = -1.0
    best_labels: list[int] = [0] * n
    for k in range(target_min, min(target_max, max(target_min + 1, n // 10)) + 1):
        if k >= n:
            break
        km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(X)
        try:
            score = silhouette_score(X, km.labels_)
        except Exception:
            score = -1.0
        log(f"    KMeans k={k}: silhouette={score:.3f}")
        if score > best_score:
            best_score = score
            best_k = k
            best_labels = list(km.labels_)

    return best_labels, f"kmeans(k={best_k}, silhouette={best_score:.3f})"


def _build_cluster_records(fps, X, labels, algo, log) -> list[ClusterRecord]:
    import numpy as np

    by_label: dict[int, list[int]] = defaultdict(list)
    for i, l in enumerate(labels):
        by_label[int(l)].append(i)

    records: list[ClusterRecord] = []
    for label, indices in sorted(by_label.items()):
        if label == -1 and len(indices) < 3:
            continue  # ignore tiny noise clumps
        member_paths = [fps[i].path for i in indices]
        sub = X[indices]
        centroid = sub.mean(axis=0)

        # Representatives: members closest to centroid
        dists = np.linalg.norm(sub - centroid, axis=1)
        order = np.argsort(dists)
        reps = [member_paths[int(i)] for i in order[:12]]

        # Feature summary: top adjustment + blend mode names by centroid value
        names = feature_names()
        ranked = sorted(((float(centroid[i]), names[i]) for i in range(len(names))), reverse=True)
        top_features = [{"name": n, "weight": round(w, 3)} for w, n in ranked[:10] if w > 0]

        summary = {
            "top_features": top_features,
            "tier_breakdown": dict(Counter(fps[i].tier for i in indices)),
            "avg_layer_count": round(float(np.mean([fps[i].layers.get("total", 0) for i in indices])), 1),
            "avg_size_mb": round(float(np.mean([fps[i].size_bytes for i in indices]) / 1_000_000), 1),
            "year_range": _year_range(fps, indices),
            "noise": label == -1,
        }

        records.append(
            ClusterRecord(
                cluster_id=label,
                label="",
                size=len(indices),
                member_paths=member_paths,
                centroid=[round(float(c), 4) for c in centroid],
                feature_summary=summary,
                representatives=reps,
            )
        )

    # Sort clusters: noise last, otherwise largest first
    records.sort(key=lambda r: (r.feature_summary.get("noise", False), -r.size))
    return records


def _year_range(fps, indices) -> str:
    years = []
    for i in indices:
        try:
            years.append(int(fps[i].mtime[:4]))
        except Exception:
            pass
    if not years:
        return "unknown"
    return f"{min(years)}-{max(years)}"


def _cluster_to_dict(c: ClusterRecord) -> dict:
    return {
        "cluster_id": c.cluster_id,
        "label": c.label,
        "size": c.size,
        "feature_summary": c.feature_summary,
        "centroid": c.centroid,
        "representatives": c.representatives,
        "member_paths": c.member_paths,
    }


# ---------------------------------------------------------------------------
# Phase 5 — Claude naming pass + draft markdown
# ---------------------------------------------------------------------------

NAMING_PROMPT_TEMPLATE = """You are reviewing a cluster of finished Photoshop composites by photographer Doug Wagner. They were grouped automatically by their layer-stack fingerprints. Your job is to look at the images, read the mechanical signature, and propose a "style" — a recurring post-processing approach Doug applies.

CLUSTER MECHANICAL SIGNATURE:
{signature}

PROJECT NAMES IN THIS CLUSTER (sample):
{project_names}

REPRESENTATIVE ITERATION MOVES (what Doug typically did from one save to the next):
{moves}

YEAR RANGE: {year_range}
TYPICAL LAYER COUNT: {avg_layers}
TIER BREAKDOWN: {tier_breakdown}

Look at the {n_images} attached images. They are representative members of this cluster.

Return ONLY a JSON object with this shape:
{{
  "name": "short kebab-case style name (2-4 words, like 'tuscany-film-warm' or 'starry-night-composite')",
  "intent": "one or two sentences describing what kind of finished output this style produces and the creative goal",
  "signals": "what to look for in a fresh RAW that would predict it wants to become this style — composition, lighting, subject, color tone",
  "signature_moves": "the recurring post-processing moves that produce this look — describe in plain English the layer-stack pattern, e.g. 'curves shadow lift + selective color reds + photo filter warming + multiply texture overlay'",
  "example_outputs": "what kind of final output this style typically produces — print, web, social, video, archival; canvas size if relevant",
  "human_review_note": "one short sentence flagging anything uncertain or that the human should double-check"
}}

Do not include any text outside the JSON object."""


def phase5_name(
    working_dir: Path,
    *,
    backend: str = "claude",
    api_key: str | None = None,
    max_thumbs_per_cluster: int = 8,
    skip_vision: bool = False,
    log: callable | None = None,
) -> Path:
    """Send representative thumbnails per cluster to Claude, write styles_draft.md.

    If skip_vision=True, writes a draft populated from mechanical signatures
    only (no API calls, no creative names) — useful for smoke tests.
    """
    log = log or (lambda s: None)
    styles_dir = working_dir / "styles"
    candidates_path = styles_dir / "candidate_styles.json"
    chains_path = styles_dir / "chain_diffs.jsonl"
    thumbs_dir = styles_dir / "thumbs"
    out_path = styles_dir / "styles_draft.md"

    if not candidates_path.exists():
        raise RuntimeError(f"No candidate_styles.json — run mine-styles cluster phase first ({candidates_path})")

    candidates = json.loads(candidates_path.read_text())
    clusters = candidates.get("clusters", [])
    chain_diffs_by_member = _index_chain_diffs(chains_path)

    drafts: list[dict] = []
    for cluster in clusters:
        log(f"  cluster #{cluster['cluster_id']} (size={cluster['size']}, label so far='{cluster['label']}')")
        rep_thumbs = _gather_thumbnails(cluster, thumbs_dir, max_thumbs_per_cluster)
        moves_summary = _summarize_moves(cluster, chain_diffs_by_member)
        signature = _format_signature(cluster)
        names = _project_names(cluster)
        prompt = NAMING_PROMPT_TEMPLATE.format(
            signature=signature,
            project_names=names,
            moves=moves_summary,
            year_range=cluster["feature_summary"].get("year_range", "unknown"),
            avg_layers=cluster["feature_summary"].get("avg_layer_count", "?"),
            tier_breakdown=cluster["feature_summary"].get("tier_breakdown", {}),
            n_images=len(rep_thumbs),
        )

        if skip_vision or not rep_thumbs:
            naming = _fallback_name(cluster)
        else:
            try:
                naming = _claude_name_cluster(prompt, rep_thumbs, api_key=api_key)
            except Exception as e:
                log(f"    vision call failed: {type(e).__name__}: {e}; falling back")
                naming = _fallback_name(cluster)

        drafts.append({"cluster": cluster, "naming": naming, "thumbs_used": [str(t) for t in rep_thumbs]})

    out_path.write_text(_render_draft_markdown(candidates, drafts))
    log(f"Phase 5 done. {len(drafts)} cluster drafts -> {out_path}")
    return out_path


def _index_chain_diffs(chains_path: Path) -> dict[str, list[dict]]:
    """Map each member path to the moves of its chain."""
    if not chains_path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    with open(chains_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                ch = json.loads(line)
            except Exception:
                continue
            for m in ch.get("members", []):
                out[m["path"]] = ch.get("moves", [])
    return out


def _gather_thumbnails(cluster: dict, thumbs_dir: Path, max_n: int) -> list[Path]:
    out: list[Path] = []
    for path in cluster.get("representatives", [])[: max_n * 3]:
        h = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
        thumb = thumbs_dir / f"{h}.jpg"
        if thumb.exists():
            out.append(thumb)
        if len(out) >= max_n:
            break
    return out


def _format_signature(cluster: dict) -> str:
    fs = cluster.get("feature_summary", {})
    top = fs.get("top_features", [])
    lines = [f"  - {f['name']} (weight {f['weight']})" for f in top[:8]]
    return "\n".join(lines) if lines else "  (no dominant features)"


def _project_names(cluster: dict, max_n: int = 14) -> str:
    names = []
    seen = set()
    for path in cluster.get("member_paths", []):
        parts = Path(path).parts
        # Pick the deepest folder before the file as the "project name"
        name = parts[-2] if len(parts) >= 2 else parts[-1]
        if name not in seen:
            seen.add(name)
            names.append(name)
        if len(names) >= max_n:
            break
    return ", ".join(names)


def _summarize_moves(cluster: dict, by_member: dict[str, list[dict]]) -> str:
    """Produce 5-8 bullet examples of cross-save moves found in cluster members."""
    candidates: list[str] = []
    for path in cluster.get("representatives", []):
        moves = by_member.get(path, [])
        for mv in moves:
            added = mv.get("added_adjustments", [])
            added_bm = mv.get("added_blend_modes", [])
            mask_d = mv.get("mask_count_delta", 0)
            ldelta = mv.get("layer_count_delta", 0)
            if not (added or added_bm or mask_d or ldelta):
                continue
            parts: list[str] = []
            if added:
                parts.append(f"added adjustment(s): {', '.join(added)}")
            if added_bm:
                parts.append(f"introduced blend mode(s): {', '.join(added_bm)}")
            if mask_d:
                parts.append(f"masks +{mask_d}" if mask_d > 0 else f"masks {mask_d}")
            if ldelta:
                parts.append(f"layers {'+' if ldelta>0 else ''}{ldelta}")
            candidates.append(f"  - {mv.get('from')} -> {mv.get('to')}: " + "; ".join(parts))
            if len(candidates) >= 8:
                break
        if len(candidates) >= 8:
            break
    return "\n".join(candidates) if candidates else "  (no multi-save chains in this cluster)"


def _fallback_name(cluster: dict) -> dict:
    fs = cluster.get("feature_summary", {})
    top = fs.get("top_features", [])
    top_adj = [t["name"].replace("adj.", "") for t in top if t["name"].startswith("adj.")][:3]
    top_bm = [t["name"].replace("bm.", "") for t in top if t["name"].startswith("bm.")][:3]
    return {
        "name": f"cluster-{cluster['cluster_id']}-auto",
        "intent": "Auto-named from mechanical fingerprint only — vision pass skipped.",
        "signals": "Unknown (no vision pass).",
        "signature_moves": f"Top adjustment-types: {', '.join(top_adj) or 'none'}. Top blend modes: {', '.join(top_bm) or 'none'}.",
        "example_outputs": "Unknown (no vision pass).",
        "human_review_note": "This cluster needs a vision-naming pass to be useful.",
    }


def _claude_name_cluster(prompt: str, thumb_paths: list[Path], api_key: str | None = None) -> dict:
    """Call Claude with multiple image blocks + prompt, parse JSON response."""
    import anthropic

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("BRIDGE_ASSIST_API_KEY")
    if not api_key:
        raise RuntimeError("No ANTHROPIC_API_KEY set; cannot run vision naming pass")

    client = anthropic.Anthropic(api_key=api_key)
    content: list[dict] = []
    for thumb in thumb_paths:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": _encode_thumb(thumb),
            },
        })
    content.append({"type": "text", "text": prompt})

    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )
    text = msg.content[0].text
    return _parse_naming_json(text)


def _encode_thumb(path: Path) -> str:
    """Base64-encode a thumbnail, ensuring it stays under Claude's per-image limit."""
    from PIL import Image

    with Image.open(path) as img:
        if max(img.size) > 1024:
            img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=82)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


def _parse_naming_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse naming JSON from response: {text[:200]}")


def _render_draft_markdown(candidates: dict, drafts: list[dict]) -> str:
    n_clusters = len(drafts)
    n_chains = sum(1 for d in drafts for _ in d["cluster"]["member_paths"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    out = [
        "# Style Library: Doug Wagner (DRAFT)",
        "",
        f"> Discovered by mining PS Works/ on {today}.",
        f"> {n_clusters} candidate styles across {n_chains} files.",
        f"> Clustering: `{candidates.get('algorithm', 'unknown')}`.",
        f"> Review the names + intents below, edit in place, then promote to `STYLES.md`.",
        "",
        "## Styles",
        "",
    ]

    for d in drafts:
        cluster = d["cluster"]
        naming = d["naming"]
        fs = cluster.get("feature_summary", {})
        top_features = ", ".join(f"{f['name']} ({f['weight']})" for f in fs.get("top_features", [])[:6])
        examples = _project_names(cluster, max_n=10)
        default_name = f"cluster-{cluster['cluster_id']}"

        out.extend([
            f"### {naming.get('name') or default_name}",
            f"- Intent: {naming.get('intent', '')}",
            f"- Signals: {naming.get('signals', '')}",
            f"- Signature moves: {naming.get('signature_moves', '')}",
            f"- Example outputs: {naming.get('example_outputs', '')}",
            f"- Human review note: {naming.get('human_review_note', '')}",
            f"- Cluster size: {cluster['size']}",
            f"- Year range: {fs.get('year_range', '?')}",
            f"- Typical layer count: {fs.get('avg_layer_count', '?')}",
            f"- Tier breakdown: {fs.get('tier_breakdown', {})}",
            f"- Mechanical fingerprint: {top_features}",
            f"- Example projects: {examples}",
            f"- Cluster id (internal): `{cluster['cluster_id']}`",
            "",
        ])

    out.extend([
        "---",
        "",
        "## Notes for the human reviewer",
        "",
        "- Names are auto-suggested. Rename freely — the cluster_id is what links back to the source data.",
        "- If a cluster looks like multiple styles mashed together, split it manually into two ### sections.",
        "- If two clusters are really the same style, merge them by deleting one and combining example projects.",
        "- When happy, copy this file to `STYLES.md` at the project root.",
        "",
    ])
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def mine_styles(
    source: Path,
    working_dir: Path,
    *,
    resume: bool = True,
    limit: int | None = None,
    skip_thumbs: bool = False,
    skip_vision: bool = False,
    backend: str = "claude",
    api_key: str | None = None,
    log: callable | None = None,
) -> Path:
    """Run all five mining phases end-to-end.

    Returns the path to styles_draft.md.
    """
    log = log or (lambda s: None)
    (working_dir / "styles").mkdir(parents=True, exist_ok=True)

    log("=== Phase 1: extract fingerprints ===")
    phase1_extract(source, working_dir, resume=resume, limit=limit, log=log)

    log("=== Phase 2: detect chains + diff ===")
    phase2_chains(working_dir, log=log)

    if not skip_thumbs:
        log("=== Phase 3: render thumbnails ===")
        phase3_thumbs(working_dir, log=log)
    else:
        log("=== Phase 3: skipped (--skip-thumbs) ===")

    log("=== Phase 4: vectorize + cluster ===")
    phase4_cluster(working_dir, log=log)

    log("=== Phase 5: name clusters + write draft ===")
    return phase5_name(
        working_dir,
        backend=backend,
        api_key=api_key,
        skip_vision=skip_vision,
        log=log,
    )
