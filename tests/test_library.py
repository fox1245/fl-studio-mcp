"""Tests for reading FL Studio's content library from disk."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from fl_studio_mcp.utils import library


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# =============================================================================
# Installed plugins
# =============================================================================


@pytest.fixture
def plugin_db(tmp_path: Path) -> Path:
    root = tmp_path / "Installed"
    nfo = (
        "ps_name={name}\n"
        "ps_file_filename_0=%FLPath%\\Plugins\\{name}.dll\n"
        "ps_file_vendorname_0={vendor}\n"
    )
    _write(root / "Generators" / "Fruity" / "Sytrus.nfo",
           nfo.format(name="Sytrus", vendor="Image-Line"))
    _write(root / "Generators" / "VST3" / "Serum.nfo",
           nfo.format(name="Serum", vendor="Xfer Records"))
    _write(root / "Effects" / "Fruity" / "Fruity Limiter.nfo",
           nfo.format(name="Fruity Limiter", vendor="Image-Line"))
    # "New" duplicates entries that are listed under their format folder.
    _write(root / "Generators" / "New" / "Sytrus.nfo",
           nfo.format(name="Sytrus", vendor="Image-Line"))
    return root


def test_installed_plugins_skips_new_folder(plugin_db: Path) -> None:
    found = library.list_installed_plugins(database_dir=plugin_db)
    assert sorted((p["name"], p["kind"], p["format"]) for p in found) == [
        ("Fruity Limiter", "effect", "Fruity"),
        ("Serum", "generator", "VST3"),
        ("Sytrus", "generator", "Fruity"),
    ]


def test_installed_plugins_filters(plugin_db: Path) -> None:
    effects = library.list_installed_plugins(kind="effect", database_dir=plugin_db)
    assert [p["name"] for p in effects] == ["Fruity Limiter"]

    by_vendor = library.list_installed_plugins(query="xfer", database_dir=plugin_db)
    assert [p["name"] for p in by_vendor] == ["Serum"]
    assert by_vendor[0]["vendor"] == "Xfer Records"


# =============================================================================
# Plugin presets
# =============================================================================


@pytest.fixture
def preset_roots(tmp_path: Path) -> list[tuple[str, Path]]:
    factory = tmp_path / "factory"
    user = tmp_path / "user"
    _write(factory / "Generators" / "Sytrus" / "Default.fst")
    _write(factory / "Generators" / "Sytrus" / "Bass" / "Acid bass.fst")
    _write(factory / "Generators" / "Sytrus" / "Pad" / "Warm pad.fst")
    _write(factory / "Generators" / "Harmless" / "Bass" / "Sub bass.fst")
    _write(factory / "Effects" / "LuxeVerb" / "Large hall.fst")
    _write(user / "Generators" / "Sytrus" / "My bass.fst")
    return [("factory", factory), ("user", user)]


def test_iter_presets_fields(preset_roots: list[tuple[str, Path]]) -> None:
    presets = {p["name"]: p for p in library.iter_presets(preset_roots, flex_dirs=[])}
    assert presets["Acid bass"]["plugin"] == "Sytrus"
    assert presets["Acid bass"]["kind"] == "generator"
    assert presets["Acid bass"]["category"] == "Bass"
    assert presets["Default"]["category"] == ""
    assert presets["Large hall"]["kind"] == "effect"
    assert presets["My bass"]["source"] == "user"


def test_search_presets(preset_roots: list[tuple[str, Path]]) -> None:
    result = library.search_presets(query="bass", roots=preset_roots, flex_dirs=[])
    assert {p["name"] for p in result["presets"]} == {"Acid bass", "Sub bass", "My bass"}
    assert result["categories"] == {"Sytrus/Bass": 1, "Harmless/Bass": 1, "Sytrus": 1}

    sytrus = library.search_presets(
        plugin="sytrus", category="bass", roots=preset_roots, flex_dirs=[]
    )
    assert [p["name"] for p in sytrus["presets"]] == ["Acid bass"]

    limited = library.search_presets(
        plugin="Sytrus", limit=2, roots=preset_roots, flex_dirs=[]
    )
    assert limited["total"] == 4
    assert len(limited["presets"]) == 2


# =============================================================================
# FLEX packs
# =============================================================================


def _write_flex_pack(path: Path, entry_names: list[str]) -> Path:
    """Write a pack in FLEX's container layout with empty entry contents."""
    table = b""
    for name in entry_names:
        raw = name.encode() + b"\0"
        table += struct.pack(">I", len(raw)) + raw + struct.pack(">QQ", 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x01\x00\x00\x02" + struct.pack(">I", len(entry_names)) + table)
    return path


@pytest.fixture
def flex_dir(tmp_path: Path) -> Path:
    packs = tmp_path / "Packs"
    _write_flex_pack(packs / "Core 808s.flex2pack", [
        "presetsIndex.presetsIndex",
        "pcf.pcf",
        "808 Astronomic.flex2preset",
        "808 Astronomic.usedsamples",
        "808 Avalanche.flex2preset",
        "MSXII_808s_C_01.flac",
    ])
    _write_flex_pack(packs / "Arksun Cityscape.flexpack", [
        "presetsIndex.presetsIndex",
        "70s Bounce.flexpreset",
    ])
    return packs


@pytest.fixture
def flex_catalog_file(tmp_path: Path) -> Path:
    catalog = [
        {"productName": "Core 808s", "filename": "/FLEX/Core 808s.flex2pack",
         "genre": "Hip Hop", "instrument": "Bass;Drums", "availability": "free"},
        {"productName": "Chiptune", "filename": "/FLEX/Chiptune.flexpack",
         "genre": "Electronic", "instrument": "Synth", "availability": "commercial"},
    ]
    return _write(tmp_path / "cache.json", json.dumps(catalog))


def test_read_flex_pack_presets(flex_dir: Path) -> None:
    names = library.read_flex_pack_presets(flex_dir / "Core 808s.flex2pack")
    assert names == ["808 Astronomic", "808 Avalanche"]


def test_read_flex_pack_presets_tolerates_bad_files(tmp_path: Path) -> None:
    assert library.read_flex_pack_presets(tmp_path / "missing.flexpack") == []
    truncated = _write_flex_pack(tmp_path / "t.flexpack", ["A.flexpreset", "B.flexpreset"])
    truncated.write_bytes(truncated.read_bytes()[:-20])
    assert library.read_flex_pack_presets(truncated) == ["A"]


def test_search_presets_includes_flex(
    preset_roots: list[tuple[str, Path]], flex_dir: Path
) -> None:
    result = library.search_presets(query="808", roots=preset_roots, flex_dirs=[flex_dir])
    assert [(p["plugin"], p["category"], p["name"]) for p in result["presets"]] == [
        ("FLEX", "Core 808s", "808 Astronomic"),
        ("FLEX", "Core 808s", "808 Avalanche"),
    ]
    assert result["presets"][0]["source"] == "flex-pack"


def test_list_flex_packs(flex_dir: Path, flex_catalog_file: Path) -> None:
    def packs(**kwargs) -> dict[str, dict]:
        found = library.list_flex_packs(
            flex_dirs=[flex_dir], catalog_path=flex_catalog_file, **kwargs
        )
        return {p["name"]: p for p in found}

    every = packs()
    # Arksun Cityscape is installed but missing from the catalog.
    assert set(every) == {"Core 808s", "Chiptune", "Arksun Cityscape"}
    assert every["Core 808s"]["installed"] is True
    assert every["Core 808s"]["presets"] == 2
    assert every["Core 808s"]["instruments"] == ["Bass", "Drums"]
    assert every["Chiptune"]["installed"] is False
    assert every["Chiptune"]["presets"] is None

    assert set(packs(installed_only=True)) == {"Core 808s", "Arksun Cityscape"}
    assert set(packs(query="drums")) == {"Core 808s"}


# =============================================================================
# FL Cloud sounds
# =============================================================================


@pytest.fixture
def cloud_dir(tmp_path: Path) -> Path:
    root = tmp_path / "FL CLOUD Sounds"
    stem = "TD_SV_StuffOfLegend_Wet_Vintage_Synths_Arpeggio_85BPM_C#min_2_4996431"
    _write(root / "sonic-voyage-tre" / f"{stem}.wav")
    _write(
        root / "sonic-voyage-tre" / f"{stem}.nfo",
        "Vendor=TREND\nTempo=85\nRootNote=C#\nChordType=min\nFileType=loop\n"
        "Tags=reverb,synth-arpeggio,synth-lead\nGenres=pop,synthpop\n",
    )
    # Older downloads have no .nfo; BPM and key come from the filename.
    _write(root / "power-vol-1-prl"
           / "FLS_IF_PV1_[[Focus]]_Hi-hat_132BPM_F#Min_3476449.fldownload.wav")
    _write(root / "sonic-voyage-tre.nfo", "Tip=sonic-voyage-tre (TREND)\n")
    return root


def test_cloud_sounds_metadata(cloud_dir: Path) -> None:
    sounds = {s["pack"]: s for s in library.iter_cloud_sounds(cloud_dir)}
    assert len(sounds) == 2

    arp = sounds["sonic-voyage-tre"]
    assert arp["has_metadata"] is True
    assert (arp["bpm"], arp["key"], arp["scale"], arp["type"]) == (85.0, "C#", "minor", "loop")
    assert arp["genres"] == ["pop", "synthpop"]
    assert arp["vendor"] == "TREND"

    hat = sounds["power-vol-1-prl"]
    assert hat["has_metadata"] is False
    assert hat["name"] == "FLS_IF_PV1_[[Focus]]_Hi-hat_132BPM_F#Min_3476449"
    assert (hat["bpm"], hat["key"], hat["scale"]) == (132.0, "F#", "minor")


def test_search_cloud_sounds_filters(cloud_dir: Path) -> None:
    def names(**kwargs) -> list[str]:
        result = library.search_cloud_sounds(root=cloud_dir, **kwargs)
        return [s["pack"] for s in result["sounds"]]

    assert names(query="synthpop") == ["sonic-voyage-tre"]
    assert names(query="hi-hat") == ["power-vol-1-prl"]
    assert names(bpm_min=80, bpm_max=90) == ["sonic-voyage-tre"]
    assert names(key="Db minor") == ["sonic-voyage-tre"]  # enharmonic with C#
    assert names(key="F#m") == ["power-vol-1-prl"]
    assert names(key="C# major") == []
    assert names(file_type="Loop") == ["sonic-voyage-tre"]


def test_search_cloud_sounds_rejects_bad_key(cloud_dir: Path) -> None:
    with pytest.raises(ValueError):
        library.search_cloud_sounds(key="H minor", root=cloud_dir)


def test_missing_folders_are_empty(tmp_path: Path) -> None:
    assert library.list_installed_plugins(database_dir=tmp_path / "nope") == []
    assert library.search_presets(roots=[("user", tmp_path / "nope")], flex_dirs=[])["total"] == 0
    assert list(library.iter_cloud_sounds(tmp_path / "nope")) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("C#", (1, None)),
        ("Db minor", (1, "minor")),
        ("Am", (9, "minor")),
        ("bb maj", (10, "major")),
        ("H", None),
    ],
)
def test_parse_key(text: str, expected: tuple[int, str | None] | None) -> None:
    assert library.parse_key(text) == expected
