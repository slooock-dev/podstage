from pathlib import Path

from podstage.core import steam


def _make_library(root: Path) -> None:
    (root / "steamapps/common").mkdir(parents=True)


def test_library_folders_parses_vdf(tmp_path: Path):
    main = tmp_path / "Steam"
    extra = tmp_path / "Data/SteamLibrary"
    _make_library(main)
    _make_library(extra)

    vdf = main / "steamapps/libraryfolders.vdf"
    vdf.write_text(
        '"libraryfolders"\n{\n'
        f'\t"0"\n\t{{\n\t\t"path"\t\t"{main}"\n\t}}\n'
        f'\t"1"\n\t{{\n\t\t"path"\t\t"{extra}"\n\t}}\n'
        "}\n"
    )

    folders = steam.library_folders(main)
    paths = [f.path for f in folders]
    assert main in paths and extra in paths
    assert folders[0].common == main / "steamapps/common"


def test_library_folders_includes_root_without_vdf(tmp_path: Path):
    main = tmp_path / "Steam"
    _make_library(main)
    folders = steam.library_folders(main)
    assert [f.path for f in folders] == [main]


def test_find_steam_root_none(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(steam, "_STEAM_ROOT_CANDIDATES", [tmp_path / "absent"])
    assert steam.find_steam_root() is None
