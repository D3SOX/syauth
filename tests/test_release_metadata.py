"""Journey: specs/journeys/JOURNEY-release-publication.md."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def load_module(self):
        spec = importlib.util.spec_from_file_location("release_metadata", ROOT / "scripts/release-metadata.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_incomplete_release_is_rejected(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as work:
            with self.assertRaisesRegex(ValueError, "missing release artifacts"):
                module.prepare(Path(work), "0.1.0", "a" * 40, "D3SOX/syauth")

    def test_complete_release_records_source_and_artifacts_without_checksum_file(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as work:
            directory = Path(work)
            for name in module.required_artifacts("0.1.0"):
                (directory / name).write_bytes(name.encode())
            module.prepare(directory, "0.1.0", "a" * 40, "D3SOX/syauth")
            manifest = json.loads((directory / "release.json").read_text())
            self.assertEqual(manifest["source_revision"], "a" * 40)
            self.assertEqual(manifest["repository"], "D3SOX/syauth")
            self.assertEqual({item["name"] for item in manifest["artifacts"]}, module.required_artifacts("0.1.0"))
            for item in manifest["artifacts"]:
                self.assertEqual(item["size"], (directory / item["name"]).stat().st_size)
            self.assertFalse((directory / "SHA256SUMS").exists())

    def test_repository_must_be_owner_and_name(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as work:
            directory = Path(work)
            for name in module.required_artifacts("0.1.0"):
                (directory / name).write_bytes(name.encode())
            for repository in ("", "D3SOX", "D3SOX/syauth/extra", "../syauth"):
                with self.subTest(repository=repository), self.assertRaisesRegex(ValueError, "repository"):
                    module.prepare(directory, "0.1.0", "a" * 40, repository)


if __name__ == "__main__":
    unittest.main()
