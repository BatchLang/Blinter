"""Tests for cross-platform path helpers."""

import os

from blinter.paths import display_path, path_basename, paths_equal


class TestPathBasename:
    """Tests for path_basename."""

    def test_windows_separator(self) -> None:
        """Backslashes are treated as separators on every platform."""
        assert path_basename(r"C:\dir\file.bat") == "file.bat"

    def test_posix_separator(self) -> None:
        """Forward slashes are treated as separators."""
        assert path_basename("/dir/sub/file.bat") == "file.bat"

    def test_relative_name(self) -> None:
        """A path with no separator is returned unchanged."""
        assert path_basename("file.bat") == "file.bat"

    def test_trailing_separator(self) -> None:
        """A trailing separator does not produce an empty basename."""
        assert path_basename("dir/sub/") == "sub"
        assert path_basename(r"dir\sub\\") == "sub"


class TestDisplayPath:
    """Tests for display_path."""

    def test_file_target_uses_basename(self) -> None:
        """A single-file target displays only the file name."""
        assert display_path(r"C:\proj\a.bat", r"C:\proj\a.bat", is_directory=False) == (
            "a.bat"
        )

    def test_directory_target_strips_windows_prefix(self) -> None:
        """Directory output is relative to the target, with forward slashes."""
        assert (
            display_path(r"C:\proj\sub\a.bat", r"C:\proj", is_directory=True)
            == "sub/a.bat"
        )

    def test_directory_target_strips_posix_prefix(self) -> None:
        """POSIX directory prefixes are stripped the same way."""
        assert (
            display_path("/proj/sub/a.bat", "/proj", is_directory=True) == "sub/a.bat"
        )

    def test_unrelated_directory_falls_back_to_basename(self) -> None:
        """A file outside the target directory displays its basename."""
        assert display_path(r"D:\other\a.bat", r"C:\proj", is_directory=True) == "a.bat"


class TestPathsEqual:
    """Tests for paths_equal."""

    def test_same_path(self) -> None:
        """Identical paths compare equal."""
        assert paths_equal("dir/a.bat", "dir/a.bat")

    def test_separator_difference(self) -> None:
        """Separators compare equal when the host path type normalizes them."""
        if os.name == "nt":
            assert paths_equal(r"dir\sub\a.bat", "dir/sub/a.bat")
        else:
            assert paths_equal("dir/sub/a.bat", "dir/sub/a.bat")

    def test_relative_paths(self) -> None:
        """Distinct relative paths are not equal."""
        assert not paths_equal("dir/a.bat", "dir/b.bat")

    def test_case(self) -> None:
        """Case sensitivity follows the host operating system."""
        if os.name == "nt":
            assert paths_equal(r"C:\Temp\A.bat", r"c:\temp\a.bat")
        else:
            assert not paths_equal("/tmp/A.bat", "/tmp/a.bat")
