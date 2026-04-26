"""Tests for the PSD style miner pipeline.

Covers the pure-logic helpers (chain detection, featurization, normalization)
plus an integration smoke test that runs phases 1+2+4 against a tmp dir of
synthetic PSDs built via psd-tools.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from bridge_assist.psd_introspect import (
    Fingerprint,
    _normalize_kind,
    _opacity_bucket,
    introspect,
    project_chain_for,
    read_fingerprints_jsonl,
    tier_for,
    write_fingerprint_jsonl,
)
from bridge_assist.style_miner import (
    Chain,
    _featurize,
    _stem_normalized,
    detect_chains,
    diff_chain,
    feature_names,
    mine_styles,
    walk_psd_corpus,
)


def make_fingerprint(
    path: str,
    *,
    project_chain=("Top Cuts", "Project"),
    mtime_offset_minutes: int = 0,
    layers=None,
    image=None,
) -> Fingerprint:
    base_mtime = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=mtime_offset_minutes)
    return Fingerprint(
        path=path,
        relpath="/".join([*project_chain, Path(path).name]),
        tier=tier_for(list(project_chain)),
        project_chain=list(project_chain),
        size_bytes=10_000_000,
        mtime=base_mtime.isoformat(),
        suffix=Path(path).suffix.lower(),
        image=image or {"width": 6000, "height": 4000, "color_mode": "rgb", "bit_depth": 8},
        layers=layers
        or {
            "total": 5,
            "groups": 1,
            "smart_objects": 0,
            "type_layers": 0,
            "pixel_layers": 2,
            "fill_layers": 0,
            "shape_layers": 0,
            "with_mask": 1,
            "adjustment_breakdown": {"curves": 1, "color_balance": 1},
            "blend_mode_histogram": {"normal": 4, "multiply": 1},
            "opacity_buckets": {"100": 4, "70-99": 1, "30-69": 0, "<30": 0, "unknown": 0},
        },
        text_snippets=[],
        tree_signature="G[A,A,P,P]",
        partial_introspection=False,
    )


class HelperTests(unittest.TestCase):
    def test_normalize_kind_buckets_adjustments(self):
        self.assertEqual(_normalize_kind("curves"), "adjustment")
        self.assertEqual(_normalize_kind("colorbalance"), "adjustment")
        self.assertEqual(_normalize_kind("huesaturation"), "adjustment")
        self.assertEqual(_normalize_kind("group"), "group")
        self.assertEqual(_normalize_kind("type"), "text")
        self.assertEqual(_normalize_kind("smartobject"), "smart_object")
        self.assertEqual(_normalize_kind("pixel"), "pixel")
        self.assertEqual(_normalize_kind("solidcolorfill"), "fill")

    def test_opacity_bucket_maps_correctly(self):
        self.assertEqual(_opacity_bucket(255), "100")
        self.assertEqual(_opacity_bucket(200), "70-99")
        self.assertEqual(_opacity_bucket(100), "30-69")
        self.assertEqual(_opacity_bucket(50), "<30")
        self.assertEqual(_opacity_bucket(None), "unknown")

    def test_stem_normalized_strips_iteration_suffixes(self):
        self.assertEqual(_stem_normalized("Project copy"), "project")
        self.assertEqual(_stem_normalized("Project copy 3"), "project")
        self.assertEqual(_stem_normalized("Project_v2"), "project")
        self.assertEqual(_stem_normalized("Project (2)"), "project")
        self.assertEqual(_stem_normalized("Final@0,25x"), "final")
        self.assertEqual(_stem_normalized("Plain Stem"), "plain stem")

    def test_project_chain_for_uses_root(self):
        root = Path("/works")
        path = root / "Top Cuts" / "Aquamatic" / "Final.psb"
        self.assertEqual(project_chain_for(path, root), ["Top Cuts", "Aquamatic"])

    def test_tier_for_known_top_levels(self):
        self.assertEqual(tier_for(["Top Cuts", "Project"]), "top_cuts")
        self.assertEqual(tier_for(["Mugsy & Tigger"]), "mugsy_tigger")
        self.assertEqual(tier_for([]), "unknown")


class ChainDetectionTests(unittest.TestCase):
    def test_camera_prefix_groups_across_subfolders(self):
        fps = [
            make_fingerprint("/works/Top Cuts/A/_MT88026.psd", project_chain=("Top Cuts", "A"), mtime_offset_minutes=0),
            make_fingerprint("/works/Top Cuts/A/_MT88026 v2.psd", project_chain=("Top Cuts", "A"), mtime_offset_minutes=10),
            make_fingerprint("/works/Top Cuts/A/sub/_MT88026 final.psd", project_chain=("Top Cuts", "A"), mtime_offset_minutes=30),
        ]
        chains = detect_chains(fps)
        camera_chains = [c for c in chains if c.chain_kind == "camera_prefix"]
        self.assertEqual(len(camera_chains), 1)
        self.assertEqual(len(camera_chains[0].members), 3)
        # Members must be ordered by mtime
        mtimes = [m.mtime for m in camera_chains[0].members]
        self.assertEqual(mtimes, sorted(mtimes))

    def test_folder_stem_groups_iteration_copies(self):
        fps = [
            make_fingerprint("/works/Top Cuts/X/Project.psd", project_chain=("Top Cuts", "X"), mtime_offset_minutes=0),
            make_fingerprint("/works/Top Cuts/X/Project copy.psd", project_chain=("Top Cuts", "X"), mtime_offset_minutes=20),
            make_fingerprint("/works/Top Cuts/X/Project copy 2.psd", project_chain=("Top Cuts", "X"), mtime_offset_minutes=45),
        ]
        chains = detect_chains(fps)
        folder_chains = [c for c in chains if c.chain_kind == "folder"]
        self.assertEqual(len(folder_chains), 1)
        self.assertEqual(len(folder_chains[0].members), 3)

    def test_singletons_get_their_own_chain(self):
        fps = [make_fingerprint("/works/Top Cuts/Y/Lonely.psd", project_chain=("Top Cuts", "Y"))]
        chains = detect_chains(fps)
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0].chain_kind, "single")

    def test_diff_chain_records_added_adjustments(self):
        fp1 = make_fingerprint(
            "/works/A/Project.psd",
            mtime_offset_minutes=0,
            layers={
                **make_fingerprint("/x").layers,
                "adjustment_breakdown": {"curves": 1},
                "blend_mode_histogram": {"normal": 3},
                "with_mask": 0,
                "total": 3,
            },
        )
        fp2 = make_fingerprint(
            "/works/A/Project copy.psd",
            mtime_offset_minutes=15,
            layers={
                **make_fingerprint("/x").layers,
                "adjustment_breakdown": {"curves": 1, "color_balance": 1, "vibrance": 1},
                "blend_mode_histogram": {"normal": 3, "multiply": 1},
                "with_mask": 2,
                "total": 6,
            },
        )
        chain = Chain(chain_id="t", folder="A", chain_kind="folder", stem_seed="project", members=[fp1, fp2])
        d = diff_chain(chain)
        self.assertEqual(len(d["moves"]), 1)
        move = d["moves"][0]
        self.assertEqual(sorted(move["added_adjustments"]), ["color_balance", "vibrance"])
        self.assertIn("multiply", move["added_blend_modes"])
        self.assertEqual(move["mask_count_delta"], 2)
        self.assertEqual(move["layer_count_delta"], 3)
        self.assertEqual(move["minutes_between"], 15)


class FeaturizationTests(unittest.TestCase):
    def test_featurize_returns_stable_length(self):
        fp = make_fingerprint("/x.psd")
        vec = _featurize(fp)
        self.assertEqual(len(vec), len(feature_names()))
        # All adjustment + blend feature values are normalized into [0, 1]
        for v in vec[:-10]:  # non-structural slice
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_featurize_flags_structural_signals(self):
        fp = make_fingerprint(
            "/x.psd",
            image={"width": 6000, "height": 4000, "color_mode": "grayscale", "bit_depth": 8},
            layers={
                "total": 35, "groups": 2, "smart_objects": 1, "type_layers": 2,
                "pixel_layers": 10, "fill_layers": 0, "shape_layers": 0, "with_mask": 20,
                "adjustment_breakdown": {"curves": 2},
                "blend_mode_histogram": {"normal": 30, "multiply": 1, "screen": 1, "color_dodge": 1},
                "opacity_buckets": {"100": 30, "70-99": 5, "30-69": 0, "<30": 0, "unknown": 0},
            },
        )
        vec = _featurize(fp)
        names = feature_names()
        d = dict(zip(names, vec))
        self.assertEqual(d["has_text"], 1.0)
        self.assertEqual(d["has_smart_objects"], 1.0)
        self.assertEqual(d["is_grayscale"], 1.0)
        self.assertEqual(d["is_rgb"], 0.0)
        self.assertEqual(d["is_high_layer_count"], 1.0)
        self.assertEqual(d["has_dark_blends"], 1.0)
        self.assertEqual(d["has_light_blends"], 1.0)


class IntrospectionRoundTripTests(unittest.TestCase):
    def test_introspect_minimal_psd_via_frompil(self):
        from psd_tools import PSDImage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Top Cuts" / "TestProject").mkdir(parents=True)
            psd_path = root / "Top Cuts" / "TestProject" / "Sample.psd"
            img = Image.new("RGB", (64, 48), (200, 150, 100))
            PSDImage.frompil(img).save(psd_path)

            fp = introspect(psd_path, root=root)

        self.assertFalse(fp.partial_introspection, msg=fp.error)
        self.assertEqual(fp.tier, "top_cuts")
        self.assertEqual(fp.project_chain, ["Top Cuts", "TestProject"])
        self.assertEqual(fp.image.get("width"), 64)
        self.assertEqual(fp.image.get("color_mode"), "rgb")
        self.assertIn("total", fp.layers)

    def test_partial_introspection_for_oversize_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            psd_path = root / "huge.psd"
            psd_path.write_bytes(b"x" * 1024)  # 1KB but threshold is 100 bytes here
            fp = introspect(psd_path, root=root, partial_threshold_bytes=100)

        self.assertTrue(fp.partial_introspection)
        self.assertIsNotNone(fp.error)
        self.assertEqual(fp.layers, {})

    def test_jsonl_roundtrip_preserves_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "fp.jsonl"
            fp = make_fingerprint("/x.psd")
            write_fingerprint_jsonl(fp, jsonl)
            write_fingerprint_jsonl(make_fingerprint("/y.psd"), jsonl)
            loaded = read_fingerprints_jsonl(jsonl)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].path, "/x.psd")
        self.assertEqual(loaded[0].layers["total"], 5)


class CorpusWalkTests(unittest.TestCase):
    def test_walk_corpus_includes_psd_psb_skips_appledouble(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Top Cuts").mkdir()
            (root / ".hidden").mkdir()
            (root / "Top Cuts" / "A.psd").write_bytes(b"x")
            (root / "Top Cuts" / "B.PSB").write_bytes(b"x")
            (root / "Top Cuts" / "._A.psd").write_bytes(b"x")
            (root / "Top Cuts" / "C.jpg").write_bytes(b"x")
            (root / ".hidden" / "Skip.psd").write_bytes(b"x")

            paths = walk_psd_corpus(root)

        names = sorted(p.name for p in paths)
        self.assertEqual(names, ["A.psd", "B.PSB"])


class MineStylesIntegrationTests(unittest.TestCase):
    """End-to-end smoke test using synthetic PSDs."""

    def test_mine_styles_runs_without_vision_or_thumbs(self):
        from psd_tools import PSDImage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "PS Works"
            for tier in ("Top Cuts", "Abstracts"):
                for proj in ("ProjectA", "ProjectB"):
                    (root / tier / proj).mkdir(parents=True)
                    for i in range(2):
                        path = root / tier / proj / f"save_{i}.psd"
                        img = Image.new("RGB", (32 + i, 24 + i), (100 + i * 10, 50, 200))
                        PSDImage.frompil(img).save(path)

            working_dir = Path(tmp) / ".bridge-assist"
            draft = mine_styles(
                root,
                working_dir,
                resume=False,
                skip_thumbs=True,
                skip_vision=True,
                log=lambda s: None,
            )

            self.assertTrue(draft.exists(), f"styles_draft.md not written at {draft}")
            text = draft.read_text()
            self.assertIn("Style Library", text)
            self.assertTrue((working_dir / "styles" / "candidate_styles.json").exists())
            cand = json.loads((working_dir / "styles" / "candidate_styles.json").read_text())
            # 8 synthetic PSDs cluster into at least one record (often via the
            # KMeans fallback once HDBSCAN drops them all into noise).
            self.assertGreaterEqual(len(cand["clusters"]), 1)


if __name__ == "__main__":
    unittest.main()
