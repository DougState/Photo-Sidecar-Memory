"""Click-based CLI entry point for bridge-assist."""

import sys
from pathlib import Path

import click


# Default working directory name (created inside the source folder)
WORKING_DIR_NAME = ".bridge-assist"


def _resolve_working_dir(source_dir: str | None = None) -> Path:
    """Resolve the .bridge-assist working directory.

    If source_dir is given, use source_dir/.bridge-assist.
    Otherwise, look for .bridge-assist in cwd or parent dirs.
    """
    if source_dir:
        return Path(source_dir).resolve() / WORKING_DIR_NAME

    # Walk up from cwd looking for existing .bridge-assist
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / WORKING_DIR_NAME
        if candidate.is_dir():
            return candidate

    # Default: cwd/.bridge-assist
    return cwd / WORKING_DIR_NAME


def _resolve_taste(taste: str | None) -> Path:
    """Find taste.md: explicit path, or search cwd and parent dirs."""
    if taste:
        p = Path(taste).resolve()
        if not p.exists():
            click.echo(f"Error: taste file not found: {p}", err=True)
            sys.exit(1)
        return p

    # Search cwd and parents for taste.md
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / "taste.md"
        if candidate.exists():
            return candidate

    click.echo("Error: No taste.md found. Specify with --taste or create one in your project.", err=True)
    sys.exit(1)


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
def ingest(source_dir: str):
    """Extract previews and EXIF metadata from a folder of NEF files."""
    from .ingest import ingest_folder

    working_dir = _resolve_working_dir(source_dir)
    click.echo(f"Working directory: {working_dir}")
    ingest_folder(Path(source_dir), working_dir)


@cli.command()
@click.option("--taste", type=click.Path(), default=None, help="Path to taste.md")
@click.option("--backend", type=click.Choice(["claude", "openai"]), default="claude", help="Vision API backend")
@click.option("--api-key", envvar="BRIDGE_ASSIST_API_KEY", default=None, help="API key (or set env var)")
@click.option("--only-unscored", is_flag=True, help="Skip already-scored images")
def score(taste: str | None, backend: str, api_key: str | None, only_unscored: bool):
    """Score images against taste.md channels via vision API."""
    from .score import score_all

    taste_path = _resolve_taste(taste)
    working_dir = _resolve_working_dir()
    click.echo(f"Taste: {taste_path}")
    click.echo(f"Working directory: {working_dir}")
    score_all(working_dir, taste_path, backend=backend, api_key=api_key, only_unscored=only_unscored)


@cli.command()
@click.option("--taste", type=click.Path(), default=None, help="Path to taste.md")
@click.option("--threshold", type=float, default=None, help="Override all channel thresholds")
@click.option("--dry-run", is_flag=True, help="Show routing plan without creating files")
@click.option("--clean", is_flag=True, help="Remove previous routing outputs first")
def route(taste: str | None, threshold: float | None, dry_run: bool, clean: bool):
    """Route scored images into channel directories with symlinks and derivatives."""
    from .route import route_all

    taste_path = _resolve_taste(taste)
    working_dir = _resolve_working_dir()
    click.echo(f"Taste: {taste_path}")
    click.echo(f"Working directory: {working_dir}")
    route_all(working_dir, taste_path, threshold_override=threshold, dry_run=dry_run, clean=clean)


@cli.command()
@click.option("--taste", type=click.Path(), default=None, help="Path to taste.md")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output markdown file path")
def report(taste: str | None, output: str | None):
    """Generate a markdown report with thumbnails and scores."""
    from .report import generate_report

    taste_path = _resolve_taste(taste)
    working_dir = _resolve_working_dir()
    output_path = Path(output) if output else None
    generate_report(working_dir, taste_path, output_path=output_path)


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
