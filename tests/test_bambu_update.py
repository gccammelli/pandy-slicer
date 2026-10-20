"""Tests for the weekly Bambu Studio update script (.github/scripts/bambu_update.py)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, "..")
SCRIPT = os.path.join(REPO, ".github", "scripts", "bambu_update.py")


class BambuUpdateTest(unittest.TestCase):
    def run_with(self, release):
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work)
        shutil.copytree(os.path.join(REPO, "pandy_slicer"), os.path.join(work, "pandy_slicer"))
        with open(os.path.join(work, "release.json"), "w") as f:
            json.dump(release, f)
        p = subprocess.run([sys.executable, SCRIPT, os.path.join(work, "release.json"), work], capture_output=True, text=True)
        read = lambda name: open(os.path.join(work, "pandy_slicer", name)).read()
        return p, read

    def test_moves_to_a_newer_release(self):
        p, read = self.run_with({"tag_name": "v99.00.00.01", "assets": [
            {"name": "BambuStudio_ubuntu22.04-v99.00.00.01-20990101.AppImage"},
            {"name": "BambuStudio_ubuntu24.04-v99.00.00.01-20990101000000.AppImage", "digest": "sha256:" + "ab" * 32}]})
        self.assertEqual(0, p.returncode, p.stderr)
        self.assertIn("version=99.00.00.01", p.stdout)
        self.assertIn("ARG BAMBU_ASSET=BambuStudio_ubuntu24.04-v99.00.00.01-20990101000000.AppImage", read("Dockerfile"))
        self.assertIn("ARG BAMBU_SHA256=" + "ab" * 32, read("Dockerfile"))
        self.assertIn("- Bambu Studio 99.00.00.01.", read("CHANGELOG.md"))

    def test_fails_without_a_digest_to_pin(self):
        p, _ = self.run_with({"tag_name": "v99.00.00.01", "assets": [
            {"name": "BambuStudio_ubuntu24.04-v99.00.00.01-20990101000000.AppImage"}]})
        self.assertNotEqual(0, p.returncode)

    def test_leaves_a_current_or_older_release(self):
        p, read = self.run_with({"tag_name": "v01.00.00.00", "assets": []})
        self.assertEqual(("", 0), (p.stdout, p.returncode))

    def test_fails_without_an_ubuntu_24_build(self):
        p, _ = self.run_with({"tag_name": "v99.00.00.01", "assets": [{"name": "Bambu_Studio_win-v99.00.00.01.exe"}]})
        self.assertNotEqual(0, p.returncode)
        stale = {"name": "BambuStudio_ubuntu24.04-v98.00.00.01-20980101000000.AppImage"}  # another version's build
        p, _ = self.run_with({"tag_name": "v99.00.00.01", "assets": [stale]})
        self.assertNotEqual(0, p.returncode)


if __name__ == "__main__":
    unittest.main()
