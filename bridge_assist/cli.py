"""Click-based CLI entry point for bridge-assist."""

import re
import sys
from pathlib import Path

import click


WORKING_DIR_NAME = ".bridge-assist"


def _resolve_working_dir(source_dir: str | None = None) -> Path:
    """Resolve the .bridge-assist working directory.

    Always uses cwd/.bridge-assist. The source_dir argument is accepted
    for backward compatibility but ignored for path resolution — the
    working directory is always relative to where you run the command.
    """
    cwd = Path.cwd()

    for parent in [cwd] + list(cwd.parents):
        candidate = parent / WORKING_DIR_NAME
        if candidate.is_dir():
            return candidate

    return cwd / WORKING_DIR_NAME


def _resolve_taste(taste: str | None) -> Path:
    """Find taste.md: explicit path, or search cwd and parent dirs."""
    if taste:
        p = Path(taste).resolve()
        if not p.exists():
            click.echo(f"Error: taste file not found: {p}", err=True)
            sys.exit(1)
        return p

    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / "taste.md"
        if candidate.exists():
            return candidate

    click.echo("Error: No taste.md found. Specify with --taste or create one in your project.", err=True)
    sys.exit(1)


def _slugify(name: str) -> str:
    """Convert a folder name to a clean tag slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def tagged_filename(base: str, tag: str | None) -> str:
    """Return 'base-tag.ext' if tag is set, otherwise 'base.ext'."""
    if not tag:
        return base
    stem, ext = base.rsplit(".", 1)
    return f"{stem}-{tag}.{ext}"


@click.group()
@click.version_option(package_name="bridge-assist")
def cli():
    """Bridge-Assist: Taste-driven RAW photo router.

    Sort and route RAW photos into workflow channels based on
    post-process intent defined in taste.md.
    """
    pass


@cli.command()
@click.argument("source_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--tag", default=None, help="Tag for this run. Auto-derived from folder name if omitted.")
def ingest(source_dir: str, tag: str | None):
    """Extract previews and EXIF metadata from a folder of NEF files."""
    from .ingest import ingest_folder

    if tag is None:
        tag = _slugify(Path(source_dir).resolve().name)
        click.echo(f"Auto-tag: {tag}")

    working_dir = _resolve_working_dir(source_dir)
    click.echo(f"Working directory: {working_dir}")
    manifest_name = tagged_filename("manifest.json", tag)
    ingest_folder(Path(source_dir), working_dir, manifest_name=manifest_name)
    click.echo(f"Tag: {tag} (use --tag {tag} for score/route/report)")


@cli.command()
@click.option("--taste", type=click.Path(), default=None, help="Path to taste.md")
@click.option("--backend", type=click.Choice(["claude", "openai"]), default="claude", help="Vision API backend")
@click.option("--api-key", envvar="BRIDGE_ASSIST_API_KEY", default=None, help="API key (or set env var)")
@click.option("--only-unscored", is_flag=True, help="Skip already-scored images")
@click.option("--tag", default=None, help="Run tag (matches ingest tag)")
def score(taste: str | None, backend: str, api_key: str | None, only_unscored: bool, tag: str | None):
    """Score images against taste.md channels via vision API."""
    from .score import score_all

    taste_path = _resolve_taste(taste)
    working_dir = _resolve_working_dir()
    click.echo(f"Taste: {taste_path}")
    click.echo(f"Working directory: {working_dir}")
    if tag:
        click.echo(f"Tag: {tag}")

    manifest_name = tagged_filename("manifest.json", tag)
    scores_name = tagged_filename("scores.json", tag)
    score_all(
        working_dir, taste_path,
        backend=backend, api_key=api_key, only_unscored=only_unscored,
        manifest_name=manifest_name, scores_name=scores_name,
    )


@cli.command()
@click.option("--taste", type=click.Path(), default=None, help="Path to taste.md")
@click.option("--threshold", type=float, default=None, help="Override all channel thresholds")
@click.option("--dry-run", is_flag=True, help="Show routing plan without creating files")
@click.option("--clean", is_flag=True, help="Remove previous routing outputs first")
@click.option("--tag", default=None, help="Run tag (matches ingest/score tag)")
def route(taste: str | None, threshold: float | None, dry_run: bool, clean: bool, tag: str | None):
    """Route scored images into channel directories with symlinks and derivatives."""
    from .route import route_all

    taste_path = _resolve_taste(taste)
    working_dir = _resolve_working_dir()
    click.echo(f"Taste: {taste_path}")
    click.echo(f"Working directory: {working_dir}")
    if tag:
        click.echo(f"Tag: {tag}")

    scores_name = tagged_filename("scores.json", tag)
    manifest_name = tagged_filename("manifest.json", tag)
    routes_name = tagged_filename("routes.json", tag)
    route_all(
        working_dir, taste_path,
        threshold_override=threshold, dry_run=dry_run, clean=clean,
        scores_name=scores_name, manifest_name=manifest_name, routes_name=routes_name,
    )


@cli.command()
@click.option("--taste", type=click.Path(), default=None, help="Path to taste.md")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output markdown file path")
@click.option("--tag", default=None, help="Run tag (matches ingest/score/route tag)")
def report(taste: str | None, output: str | None, tag: str | None):
    """Generate a markdown report with thumbnails and scores."""
    from .report import generate_report

    taste_path = _resolve_taste(taste)
    working_dir = _resolve_working_dir()
    if tag:
        click.echo(f"Tag: {tag}")

    output_path = Path(output) if output else None
    manifest_name = tagged_filename("manifest.json", tag)
    scores_name = tagged_filename("scores.json", tag)
    routes_name = tagged_filename("routes.json", tag)
    report_name = tagged_filename("sort-report.md", tag)
    generate_report(
        working_dir, taste_path,
        output_path=output_path,
        manifest_name=manifest_name, scores_name=scores_name,
        routes_name=routes_name, report_name=report_name,
    )


@cli.command()
@click.option("--tag", default=None, help="Run tag (matches ingest/score tag)")
@click.option("--dry-run", is_flag=True, help="Show what would be written without writing")
@click.option("--clean", is_flag=True, help="Remove existing .xmp sidecars before writing")
def xmp(tag: str | None, dry_run: bool, clean: bool):
    """Write XMP sidecar files so Adobe Bridge shows AI scores.

    Places a .xmp file next to each NEF in the source directory.
    Bridge reads these automatically: star ratings from confidence,
    color labels from primary channel, keywords for filtering.
    """
    from .xmp import write_xmp_sidecars

    working_dir = _resolve_working_dir()
    scores_path = working_dir / tagged_filename("scores.json", tag)
    manifest_path = working_dir / tagged_filename("manifest.json", tag)

    if not scores_path.exists():
        click.echo(f"Error: scores file not found: {scores_path}", err=True)
        click.echo("Run 'bridge-assist score' first.", err=True)
        sys.exit(1)
    if not manifest_path.exists():
        click.echo(f"Error: manifest not found: {manifest_path}", err=True)
        sys.exit(1)

    click.echo(f"Scores: {scores_path}")
    click.echo(f"Manifest: {manifest_path}")
    if dry_run:
        click.echo("Mode: DRY RUN")

    result = write_xmp_sidecars(
        scores_path, manifest_path,
        dry_run=dry_run, clean=clean,
    )

    click.echo(f"\nSource: {result['source_dir']}")
    click.echo(f"Written: {result['written']} XMP sidecars")
    if result['skipped']:
        click.echo(f"Skipped: {result['skipped']} (no scores)")
    if result['cleaned']:
        click.echo(f"Cleaned: {result['cleaned']} old sidecars")
    if result['errors']:
        click.echo(f"Errors: {len(result['errors'])}")
        for err in result['errors']:
            click.echo(f"  - {err}")

    if not dry_run and result['written'] > 0:
        click.echo("\nOpen Adobe Bridge and navigate to the source folder.")
        click.echo("Stars, labels, and keywords should appear automatically.")


@cli.command()
@click.option("--taste", type=click.Path(), default=None, help="Path to taste.md")
def validate(taste: str | None):
    """Validate a taste.md file for required fields and structure."""
    from .taste_parser import validate_taste_file

    taste_path = _resolve_taste(taste)
    errors = validate_taste_file(taste_path)

    if errors:
        click.echo(f"Validation FAILED for {taste_path}:")
        for err in errors:
            click.echo(f"  - {err}")
        sys.exit(1)
    else:
        click.echo(f"Validation OK: {taste_path}")
        click.echo(f"  Channels: {', '.join(_get_channel_names(taste_path))}")


# ---------------------------------------------------------------------------
# Taste Engine (V2) commands
# ---------------------------------------------------------------------------

@cli.command("record")
@click.argument("processed_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--tag", default=None, help="Run tag (matches ingest/score tag)")
def record_feedback(processed_file: str, tag: str | None):
    """Record feedback for a processed file (PSD/TIFF).

    Matches the file back to its source NEF, infers which channel the
    output belongs to, and records the result in the feedback database.
    """
    from .matcher import load_manifest, load_scores, match_to_nef, get_original_scores
    from .inferrer import infer_channel
    from .feedback_db import FeedbackDB

    working_dir = _resolve_working_dir()
    manifest_path = working_dir / tagged_filename("manifest.json", tag)
    scores_path = working_dir / tagged_filename("scores.json", tag)

    if not manifest_path.exists():
        click.echo(f"Error: manifest not found: {manifest_path}", err=True)
        sys.exit(1)
    if not scores_path.exists():
        click.echo(f"Error: scores not found: {scores_path}", err=True)
        sys.exit(1)

    manifest = load_manifest(manifest_path)
    scores_data = load_scores(scores_path)
    processed_path = Path(processed_file).resolve()

    click.echo(f"File: {processed_path.name}")

    match = match_to_nef(processed_path, manifest)
    if match.nef_filename:
        click.echo(f"Matched: {match.nef_filename} ({match.match_method}, {match.confidence:.0%})")
    else:
        click.echo(f"No NEF match found ({match.match_method})")

    original_scores = []
    if match.nef_filename:
        original_scores = get_original_scores(match.nef_filename, scores_data)
        if original_scores:
            top = max(original_scores, key=lambda s: s["confidence"])
            click.echo(f"AI scored: {top['channel']} ({top['confidence']:.0%})")

    inference = infer_channel(processed_path, original_scores or None)
    click.echo(f"Inferred:  {inference.channel} ({inference.method}, {inference.confidence:.0%})")

    if original_scores:
        top = max(original_scores, key=lambda s: s["confidence"])
        if inference.channel == top["channel"]:
            click.echo("Result: CONFIRMED (AI was right)")
        else:
            click.echo(f"Result: CORRECTION (AI said {top['channel']}, actual {inference.channel})")

    db = FeedbackDB(working_dir / "feedback.db")
    row_id = db.record(
        processed_path=processed_path,
        nef_filename=match.nef_filename,
        nef_path=match.nef_path,
        match_method=match.match_method,
        match_confidence=match.confidence,
        inferred_channel=inference.channel,
        inference_method=inference.method,
        inference_confidence=inference.confidence,
        inference_signals=inference.signals,
        original_scores=original_scores,
        tag=tag,
    )
    db.close()
    click.echo(f"Recorded: feedback #{row_id}")


@cli.command("record-dir")
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--tag", default=None, help="Run tag (matches ingest/score tag)")
def record_dir(directory: str, tag: str | None):
    """Record feedback for all PSD/TIFF files in a directory."""
    from .matcher import load_manifest, load_scores, match_to_nef, get_original_scores, WATCHED_EXTENSIONS
    from .inferrer import infer_channel
    from .feedback_db import FeedbackDB

    working_dir = _resolve_working_dir()
    manifest_path = working_dir / tagged_filename("manifest.json", tag)
    scores_path = working_dir / tagged_filename("scores.json", tag)

    if not manifest_path.exists():
        click.echo(f"Error: manifest not found: {manifest_path}", err=True)
        sys.exit(1)
    if not scores_path.exists():
        click.echo(f"Error: scores not found: {scores_path}", err=True)
        sys.exit(1)

    manifest = load_manifest(manifest_path)
    scores_data = load_scores(scores_path)
    db = FeedbackDB(working_dir / "feedback.db")

    dir_path = Path(directory).resolve()
    files = [
        f for f in dir_path.iterdir()
        if f.is_file() and f.suffix.lower() in WATCHED_EXTENSIONS and not f.name.startswith(".")
    ]

    if not files:
        click.echo(f"No PSD/TIFF files found in {dir_path}")
        db.close()
        return

    click.echo(f"Scanning {len(files)} files in {dir_path.name}/")
    confirmed = 0
    corrected = 0
    unmatched = 0

    for f in sorted(files):
        match = match_to_nef(f, manifest)
        original_scores = []
        if match.nef_filename:
            original_scores = get_original_scores(match.nef_filename, scores_data)

        inference = infer_channel(f, original_scores or None)

        is_conf = None
        if original_scores and inference.channel != "unknown":
            top = max(original_scores, key=lambda s: s["confidence"])
            is_conf = inference.channel == top["channel"]

        status = "?" if is_conf is None else ("ok" if is_conf else "CORRECTED")
        if is_conf is True:
            confirmed += 1
        elif is_conf is False:
            corrected += 1
        else:
            unmatched += 1

        nef_str = match.nef_filename or "no match"
        click.echo(f"  {f.name} -> {nef_str} -> {inference.channel} [{status}]")

        db.record(
            processed_path=f,
            nef_filename=match.nef_filename,
            nef_path=match.nef_path,
            match_method=match.match_method,
            match_confidence=match.confidence,
            inferred_channel=inference.channel,
            inference_method=inference.method,
            inference_confidence=inference.confidence,
            inference_signals=inference.signals,
            original_scores=original_scores,
            tag=tag,
        )

    db.close()
    click.echo(f"\nRecorded {len(files)} entries: {confirmed} confirmed, {corrected} corrected, {unmatched} unmatched")


@cli.command()
@click.option("--tag", default=None, help="Filter by run tag")
@click.option("--summary", "mode", flag_value="summary", help="Show aggregated channel stats")
@click.option("--accuracy", "mode", flag_value="accuracy", help="Show AI accuracy metrics")
@click.option("--recent", "mode", flag_value="recent", default=True, help="Show recent entries (default)")
@click.option("--limit", default=20, help="Number of recent entries to show")
def feedback(tag: str | None, mode: str, limit: int):
    """Query the feedback database.

    Shows recent feedback entries by default. Use --summary for aggregated
    channel stats, or --accuracy for the AI learning curve metric.
    """
    from .feedback_db import FeedbackDB

    working_dir = _resolve_working_dir()
    db_path = working_dir / "feedback.db"

    if not db_path.exists():
        click.echo("No feedback recorded yet. Run 'bridge-assist record' first.")
        return

    db = FeedbackDB(db_path)

    if mode == "summary":
        data = db.summary(tag=tag)
        click.echo(f"Feedback summary ({data['total']} total entries)")
        if tag:
            click.echo(f"Tag: {tag}")
        click.echo()
        click.echo(f"{'Channel':<20} {'Total':>6} {'Confirmed':>10} {'Corrected':>10} {'Unmatched':>10} {'Avg Conf':>9}")
        click.echo("-" * 75)
        for ch in data["channels"]:
            click.echo(
                f"{ch['inferred_channel']:<20} {ch['total']:>6} "
                f"{ch['confirmations']:>10} {ch['corrections']:>10} "
                f"{ch['unmatched']:>10} {ch['avg_confidence']:>8.0%}"
            )

    elif mode == "accuracy":
        data = db.accuracy(tag=tag)
        click.echo("AI Accuracy Report")
        if tag:
            click.echo(f"Tag: {tag}")
        click.echo(f"\nTotal matched: {data['total']}")
        click.echo(f"Correct:       {data['correct']}")
        click.echo(f"Incorrect:     {data['incorrect']}")
        click.echo(f"Accuracy:      {data['accuracy_rate']:.1%}")

        if data["common_corrections"]:
            click.echo(f"\nCommon corrections (AI said X, actual was Y):")
            for c in data["common_corrections"]:
                click.echo(f"  {c['original_top_channel']} -> {c['inferred_channel']} ({c['count']}x)")

    else:
        entries = db.recent(limit=limit, tag=tag)
        if not entries:
            click.echo("No feedback entries found.")
            db.close()
            return

        click.echo(f"Recent feedback ({len(entries)} entries)")
        if tag:
            click.echo(f"Tag: {tag}")
        click.echo()
        for e in entries:
            ts = e["timestamp"][:16].replace("T", " ")
            nef = e["nef_filename"] or "no match"
            conf = "ok" if e["is_confirmation"] == 1 else ("CORRECTED" if e["is_confirmation"] == 0 else "?")
            name = Path(e["processed_path"]).name
            click.echo(f"  {ts}  {name} -> {nef} -> {e['inferred_channel']} [{conf}]")

    db.close()


def _get_channel_names(taste_path: Path) -> list[str]:
    from .taste_parser import parse_taste_file
    profile = parse_taste_file(taste_path)
    return profile.channel_names()


# ---------------------------------------------------------------------------
# Style mining commands (PSD/PSB corpus -> STYLES.md)
# ---------------------------------------------------------------------------

@cli.command("mine-styles")
@click.argument("source_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--limit", type=int, default=None, help="Cap the number of new files processed (smoke test).")
@click.option("--no-resume", is_flag=True, help="Re-extract every fingerprint (ignore existing JSONL).")
@click.option("--skip-thumbs", is_flag=True, help="Skip Phase 3 thumbnail generation.")
@click.option("--skip-vision", is_flag=True, help="Skip Phase 5 Claude naming pass; produce mechanical-only draft.")
@click.option("--phase", type=click.Choice(["all", "extract", "chains", "thumbs", "cluster", "name"]), default="all", help="Run only one phase (for re-runs).")
@click.option("--backend", type=click.Choice(["claude", "openai"]), default="claude", help="Vision API backend (Phase 5 only; openai not yet implemented).")
@click.option("--api-key", envvar="BRIDGE_ASSIST_API_KEY", default=None, help="Vision API key (or set ANTHROPIC_API_KEY).")
@click.option("--partial-threshold-mb", type=int, default=1000, help="Files above this size (MB) are recorded as partial — skips layer walk.")
@click.option("--timeout", type=int, default=120, help="Per-file PSD parse timeout (seconds).")
def mine_styles_cmd(
    source_dir: str,
    limit: int | None,
    no_resume: bool,
    skip_thumbs: bool,
    skip_vision: bool,
    phase: str,
    backend: str,
    api_key: str | None,
    partial_threshold_mb: int,
    timeout: int,
):
    """Mine styles from a PSD/PSB corpus and produce styles_draft.md.

    Walks SOURCE_DIR, fingerprints every PSD/PSB without decoding pixels,
    detects iteration chains, clusters fingerprints by mechanical signature,
    and asks Claude to name each cluster. Output: .bridge-assist/styles/styles_draft.md.

    Re-runnable. Resume-safe. Use --limit for quick smoke tests.
    """
    from .style_miner import (
        mine_styles,
        phase1_extract,
        phase2_chains,
        phase3_thumbs,
        phase4_cluster,
        phase5_name,
    )

    source = Path(source_dir).resolve()
    working_dir = _resolve_working_dir(source_dir)
    working_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"Source: {source}")
    click.echo(f"Working: {working_dir}")

    log = lambda msg: click.echo(msg)

    if phase == "all":
        draft = mine_styles(
            source,
            working_dir,
            resume=not no_resume,
            limit=limit,
            skip_thumbs=skip_thumbs,
            skip_vision=skip_vision,
            backend=backend,
            api_key=api_key,
            partial_threshold_bytes=partial_threshold_mb * 1_000_000,
            timeout_seconds=timeout,
            log=log,
        )
        click.echo(f"\nDraft style library: {draft}")
        click.echo("Review and edit, then copy to STYLES.md when ready.")
        return

    if phase == "extract":
        phase1_extract(
            source,
            working_dir,
            resume=not no_resume,
            limit=limit,
            partial_threshold_bytes=partial_threshold_mb * 1_000_000,
            timeout_seconds=timeout,
            log=log,
        )
    elif phase == "chains":
        phase2_chains(working_dir, log=log)
    elif phase == "thumbs":
        phase3_thumbs(working_dir, log=log)
    elif phase == "cluster":
        phase4_cluster(working_dir, log=log)
    elif phase == "name":
        phase5_name(
            working_dir,
            backend=backend,
            api_key=api_key,
            skip_vision=skip_vision,
            log=log,
        )


@cli.command("styles-report")
@click.option("--source-dir", type=click.Path(exists=True, file_okay=False), default=None, help="Used only for working-dir resolution; not re-walked.")
def styles_report_cmd(source_dir: str | None):
    """Print a one-screen summary of the latest mining run."""
    import json as _json
    from .psd_introspect import read_fingerprints_jsonl

    working_dir = _resolve_working_dir(source_dir)
    styles_dir = working_dir / "styles"

    fps_path = styles_dir / "fingerprints.jsonl"
    chains_path = styles_dir / "chain_diffs.jsonl"
    candidates_path = styles_dir / "candidate_styles.json"
    draft_path = styles_dir / "styles_draft.md"

    if not fps_path.exists():
        click.echo(f"No fingerprints found in {styles_dir}. Run 'bridge-assist mine-styles SOURCE' first.")
        return

    fps = read_fingerprints_jsonl(fps_path)
    partials = sum(1 for f in fps if f.partial_introspection)
    errors = sum(1 for f in fps if f.error)

    click.echo(f"Working directory: {working_dir}")
    click.echo()
    click.echo(f"Fingerprints: {len(fps)} total ({partials} partial, {errors} with errors)")

    by_tier: dict[str, int] = {}
    for f in fps:
        by_tier[f.tier] = by_tier.get(f.tier, 0) + 1
    click.echo("Tier breakdown:")
    for tier, n in sorted(by_tier.items(), key=lambda x: -x[1]):
        click.echo(f"  {tier:<20} {n}")

    if chains_path.exists():
        with open(chains_path) as f:
            n_chains = sum(1 for _ in f)
        click.echo(f"\nChains: {n_chains}")

    if candidates_path.exists():
        cand = _json.loads(candidates_path.read_text())
        click.echo(f"\nClustering: {cand.get('algorithm', 'unknown')}")
        for c in cand.get("clusters", []):
            label = c.get("label") or f"cluster-{c['cluster_id']}"
            top = ", ".join(f["name"] for f in c.get("feature_summary", {}).get("top_features", [])[:4])
            click.echo(f"  #{c['cluster_id']:>3} size={c['size']:>4}  {label:<30} top: {top}")

    if draft_path.exists():
        click.echo(f"\nDraft library: {draft_path}")


@cli.command("styles-inspect")
@click.argument("cluster_id", type=int)
@click.option("--source-dir", type=click.Path(exists=True, file_okay=False), default=None)
@click.option("--limit", type=int, default=20, help="Max members to print.")
def styles_inspect_cmd(cluster_id: int, source_dir: str | None, limit: int):
    """Show the members of a single cluster from the latest mining run."""
    import json as _json

    working_dir = _resolve_working_dir(source_dir)
    candidates_path = working_dir / "styles" / "candidate_styles.json"

    if not candidates_path.exists():
        click.echo(f"No candidate_styles.json — run 'bridge-assist mine-styles SOURCE' first.")
        sys.exit(1)

    cand = _json.loads(candidates_path.read_text())
    target = next((c for c in cand.get("clusters", []) if c["cluster_id"] == cluster_id), None)
    if not target:
        click.echo(f"Cluster {cluster_id} not found. Available: {[c['cluster_id'] for c in cand.get('clusters', [])]}")
        sys.exit(1)

    click.echo(f"Cluster {cluster_id}  size={target['size']}  label={target.get('label') or '(unnamed)'}")
    fs = target.get("feature_summary", {})
    click.echo(f"  year_range: {fs.get('year_range')}")
    click.echo(f"  avg_layer_count: {fs.get('avg_layer_count')}")
    click.echo(f"  tier_breakdown: {fs.get('tier_breakdown')}")
    click.echo(f"  top features:")
    for f in fs.get("top_features", [])[:10]:
        click.echo(f"    - {f['name']:<30} {f['weight']}")

    click.echo(f"\nMembers ({min(limit, len(target['member_paths']))} of {len(target['member_paths'])}):")
    for path in target["member_paths"][:limit]:
        click.echo(f"  {path}")


def main():
    cli()


if __name__ == "__main__":
    main()
