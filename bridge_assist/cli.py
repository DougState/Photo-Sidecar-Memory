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


def _get_channel_names(taste_path: Path) -> list[str]:
    from .taste_parser import parse_taste_file
    profile = parse_taste_file(taste_path)
    return profile.channel_names()


def main():
    cli()


if __name__ == "__main__":
    main()
