"""Tests for tar archive extraction of RIO-downloaded bags."""
import os
import sys
import tarfile
import pathlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch
from services.rio.rio_service import extract_bag_archive


@pytest.fixture
def bags_dir(tmp_path):
    """Provide a temporary bags directory."""
    d = tmp_path / "bags"
    d.mkdir()
    return d


def _make_tar(tmp_path, filenames, compression="xz"):
    """Create a tar archive containing dummy files."""
    archive_name = f"test_archive.tar.{compression}"
    mode = {"xz": "w:xz", "gz": "w:gz", "bz2": "w:bz2"}[compression]
    archive_path = tmp_path / archive_name
    for fn in filenames:
        f = tmp_path / fn
        f.write_bytes(b"ROSBAG dummy content " + fn.encode())
    with tarfile.open(archive_path, mode) as tar:
        for fn in filenames:
            tar.add(tmp_path / fn, arcname=fn)
    return archive_path


class TestExtractBagArchive:
    """Tests for extract_bag_archive utility."""

    def test_extracts_bag_files_from_tar_xz(self, tmp_path, bags_dir):
        names = ["robot_01.bag", "robot_02.bag"]
        archive = _make_tar(tmp_path, names, "xz")
        result = extract_bag_archive(archive, bags_dir)
        assert len(result) == 2
        assert all(p.exists() for p in result)
        assert all(p.suffix == ".bag" for p in result)

    def test_extracts_bag_files_from_tar_gz(self, tmp_path, bags_dir):
        names = ["data.bag"]
        archive = _make_tar(tmp_path, names, "gz")
        result = extract_bag_archive(archive, bags_dir)
        assert len(result) == 1
        assert result[0].suffix == ".bag"

    def test_extracts_db3_files(self, tmp_path, bags_dir):
        names = ["ros2_data.db3"]
        archive = _make_tar(tmp_path, names, "xz")
        result = extract_bag_archive(archive, bags_dir)
        assert len(result) == 1
        assert result[0].suffix == ".db3"

    def test_extracts_bag_active_as_bag(self, tmp_path, bags_dir):
        """A .bag.active file should be renamed to .bag on extraction."""
        names = ["robot_25.bag.active"]
        archive = _make_tar(tmp_path, names, "xz")
        result = extract_bag_archive(archive, bags_dir)
        assert len(result) == 1
        assert result[0].suffix == ".bag"
        assert result[0].exists()

    def test_ignores_non_bag_files(self, tmp_path, bags_dir):
        names = ["readme.txt", "robot.bag", "config.yaml"]
        archive = _make_tar(tmp_path, names, "xz")
        result = extract_bag_archive(archive, bags_dir)
        assert len(result) == 1
        assert result[0].name == "robot.bag"

    def test_returns_empty_for_no_bags(self, tmp_path, bags_dir):
        names = ["readme.txt", "config.yaml"]
        archive = _make_tar(tmp_path, names, "xz")
        result = extract_bag_archive(archive, bags_dir)
        assert result == []

    def test_removes_archive_after_extraction(self, tmp_path, bags_dir):
        names = ["robot.bag"]
        archive = _make_tar(tmp_path, names, "xz")
        assert archive.exists()
        extract_bag_archive(archive, bags_dir)
        assert not archive.exists()

    def test_collision_appends_suffix(self, tmp_path, bags_dir):
        # Pre-create a file that will collide
        (bags_dir / "robot.bag").write_bytes(b"existing")
        names = ["robot.bag"]
        archive = _make_tar(tmp_path, names, "xz")
        result = extract_bag_archive(archive, bags_dir)
        assert len(result) == 1
        assert result[0].exists()
        # Should not have overwritten the original
        assert (bags_dir / "robot.bag").read_bytes() == b"existing"
        assert result[0] != bags_dir / "robot.bag"

    def test_rejects_path_traversal(self, tmp_path, bags_dir):
        """Archive members with .. in their path must be skipped."""
        archive_path = tmp_path / "evil.tar.gz"
        evil_name = "../../etc/evil.bag"
        # Create a file to add
        f = tmp_path / "evil.bag"
        f.write_bytes(b"evil content")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(f, arcname=evil_name)
        result = extract_bag_archive(archive_path, bags_dir)
        assert result == []
        # Ensure nothing was written outside bags_dir
        assert not (bags_dir.parent.parent / "etc" / "evil.bag").exists()

    def test_returns_sorted_by_name(self, tmp_path, bags_dir):
        names = ["c_03.bag", "a_01.bag", "b_02.bag"]
        archive = _make_tar(tmp_path, names, "xz")
        result = extract_bag_archive(archive, bags_dir)
        result_names = [p.name for p in result]
        assert result_names == sorted(result_names)


class TestIsArchive:
    """Tests for archive file detection."""

    def test_tar_xz_detected(self, tmp_path):
        from services.rio.rio_service import is_bag_archive
        f = tmp_path / "data.tar.xz"
        f.write_bytes(b"")
        assert is_bag_archive(f) is True

    def test_tar_gz_detected(self, tmp_path):
        from services.rio.rio_service import is_bag_archive
        f = tmp_path / "data.tar.gz"
        f.write_bytes(b"")
        assert is_bag_archive(f) is True

    def test_bag_not_detected(self, tmp_path):
        from services.rio.rio_service import is_bag_archive
        f = tmp_path / "data.bag"
        f.write_bytes(b"")
        assert is_bag_archive(f) is False

    def test_xz_suffix_detected(self, tmp_path):
        from services.rio.rio_service import is_bag_archive
        f = tmp_path / "data.xz"
        f.write_bytes(b"")
        assert is_bag_archive(f) is True
