"""Read FL Studio's content library from disk.

Covers installed plugins, plugin presets, FLEX packs and downloaded FL Cloud
sounds. None of
this needs FL Studio to be running: it reads the files FL Studio keeps in its
install folder and in the user data folder (Documents/Image-Line).
"""

from __future__ import annotations

import json
import os
import re
import struct
from collections import Counter
from pathlib import Path
from typing import Iterator

AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg", ".aif", ".aiff"}

_KIND_NAMES = {"Generators": "generator", "Effects": "effect"}

_PITCH_CLASSES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

_SCALE_NAMES = {"m": "minor", "min": "minor", "minor": "minor", "maj": "major", "major": "major"}

_NOTE_RE = re.compile(r"([A-Ga-g])([#b]?)")
# Filenames spell keys as e.g. "F#Min", "C#min", "Ebm" between underscores.
_NAME_KEY_RE = re.compile(r"([A-G][#b]?)((?i:maj|major|min|minor|m))?")
_NAME_BPM_RE = re.compile(r"(\d{2,3})\s*BPM", re.IGNORECASE)
_QUERY_KEY_RE = re.compile(r"\s*([A-Ga-g][#b]?)\s*(maj|major|min|minor|m)?\s*", re.IGNORECASE)


def user_data_dir() -> Path:
    """FL Studio's user data folder (Documents/Image-Line)."""
    return Path.home() / "Documents" / "Image-Line"


def install_dir() -> Path | None:
    """FL Studio's install folder, or None if it can't be found.

    Set FL_STUDIO_PATH to point at a non-default install. Otherwise the newest
    "FL Studio <version>" folder under Program Files/Image-Line is used.
    """
    override = os.environ.get("FL_STUDIO_PATH")
    if override:
        return Path(override)

    image_line = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Image-Line"
    candidates = [
        d for d in image_line.glob("FL Studio*") if (d / "Data" / "Patches").is_dir()
    ]
    if not candidates:
        return None

    def version(d: Path) -> int:
        digits = re.sub(r"\D", "", d.name)
        return int(digits) if digits else 0

    return max(candidates, key=version)


def read_nfo(path: Path) -> dict[str, str]:
    """Parse one of FL Studio's key=value .nfo metadata files."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return {}

    info = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            info[key.strip()] = value.strip()
    return info


def _matches(tokens: list[str], *fields: str) -> bool:
    haystack = " ".join(fields).lower()
    return all(token in haystack for token in tokens)


# =============================================================================
# Installed plugins
# =============================================================================


def list_installed_plugins(
    kind: str | None = None,
    query: str = "",
    database_dir: Path | None = None,
) -> list[dict]:
    """List the plugins FL Studio's plugin manager has found.

    Args:
        kind: "generator" or "effect" to list only one kind
        query: Words that must all appear in the plugin name or vendor
        database_dir: The plugin database's "Installed" folder (for tests)
    """
    root = database_dir or (
        user_data_dir() / "FL Studio" / "Presets" / "Plugin database" / "Installed"
    )
    tokens = query.lower().split()

    found = []
    for kind_dir, kind_name in _KIND_NAMES.items():
        if kind and kind.lower() != kind_name:
            continue
        for group in sorted((root / kind_dir).glob("*")):
            # "New" repeats the recently found plugins that are also listed
            # under their own format folder.
            if not group.is_dir() or group.name == "New":
                continue
            for nfo in sorted(group.glob("*.nfo")):
                info = read_nfo(nfo)
                name = info.get("ps_name", nfo.stem)
                vendor = info.get("ps_file_vendorname_0", "")
                if not _matches(tokens, name, vendor):
                    continue
                found.append({
                    "name": name,
                    "kind": kind_name,
                    "format": group.name,
                    "vendor": vendor,
                    "file": info.get("ps_file_filename_0", ""),
                })
    return found


# =============================================================================
# Plugin presets
# =============================================================================


def preset_roots() -> list[tuple[str, Path]]:
    """The folders FL Studio keeps plugin presets in, labelled by source."""
    roots = []
    fl_dir = install_dir()
    if fl_dir is not None:
        roots.append(("factory", fl_dir / "Data" / "Patches" / "Plugin presets"))
    roots.append(("user", user_data_dir() / "FL Studio" / "Presets" / "Plugin presets"))
    return roots


def iter_presets(
    roots: list[tuple[str, Path]] | None = None,
    flex_dirs: list[Path] | None = None,
) -> Iterator[dict]:
    """Yield every preset as {name, plugin, kind, category, source, path}.

    Covers .fst presets and the presets inside installed FLEX packs, which
    are listed with plugin "FLEX" and the pack name as their category.
    """
    yield from iter_flex_presets(flex_dirs)
    for source, root in roots if roots is not None else preset_roots():
        if not root.is_dir():
            continue
        for kind_dir in sorted(d for d in root.iterdir() if d.is_dir()):
            kind = _KIND_NAMES.get(kind_dir.name, kind_dir.name.lower())
            for plugin_dir in sorted(d for d in kind_dir.iterdir() if d.is_dir()):
                for fst in sorted(plugin_dir.rglob("*.fst")):
                    yield {
                        "name": fst.stem,
                        "plugin": plugin_dir.name,
                        "kind": kind,
                        "category": "/".join(fst.parent.relative_to(plugin_dir).parts),
                        "source": source,
                        "path": str(fst),
                    }


def search_presets(
    query: str = "",
    plugin: str | None = None,
    category: str | None = None,
    limit: int = 50,
    roots: list[tuple[str, Path]] | None = None,
    flex_dirs: list[Path] | None = None,
) -> dict:
    """Search plugin presets by name, plugin and category.

    Returns the total match count, a per plugin/category breakdown of all
    matches, and up to `limit` presets.
    """
    tokens = query.lower().split()
    matches = [
        p for p in iter_presets(roots, flex_dirs)
        if (plugin is None or p["plugin"].lower() == plugin.lower())
        and (category is None or category.lower() in p["category"].lower())
        and _matches(tokens, p["name"], p["category"], p["plugin"])
    ]
    categories = Counter(
        f"{p['plugin']}/{p['category']}" if p["category"] else p["plugin"] for p in matches
    )
    return {
        "total": len(matches),
        "categories": dict(categories.most_common(40)),
        "presets": matches[:limit],
    }


# =============================================================================
# FLEX packs
# =============================================================================

_FLEX_PACK_SUFFIXES = (".flexpack", ".flex2pack")
_FLEX_PRESET_SUFFIXES = (".flexpreset", ".flex2preset")


def flex_pack_dirs() -> list[Path]:
    """The folders FLEX loads its preset packs from."""
    dirs = []
    fl_dir = install_dir()
    if fl_dir is not None:
        dirs.append(fl_dir / "Data" / "Patches" / "Packs" / "FLEX" / "Packs")
    dirs.append(user_data_dir() / "FLEX" / "Packs")
    return dirs


def read_flex_pack_presets(path: Path) -> list[str]:
    """List the preset names stored in a FLEX pack file.

    A pack starts with a 4-byte header and a big-endian u32 entry count. Each
    entry is a u32 name length, the NUL-terminated name, and two u64s (offset
    and size). Presets are the entries named "<preset>.flexpreset" or
    "<preset>.flex2preset"; the rest are samples and pack metadata.

    Only the entry table at the start is read; packs can be hundreds of MB.
    """
    names = []
    try:
        with path.open("rb") as f:
            header = f.read(8)
            if len(header) < 8:
                return []
            (count,) = struct.unpack(">I", header[4:8])
            for _ in range(count):
                raw = f.read(4)
                if len(raw) < 4:
                    break
                (length,) = struct.unpack(">I", raw)
                if length == 0 or length > 4096:
                    break
                entry = f.read(length + 16)
                if len(entry) < length + 16:
                    break
                name = entry[:length].rstrip(b"\0").decode("utf-8", "replace")
                for suffix in _FLEX_PRESET_SUFFIXES:
                    if name.endswith(suffix):
                        names.append(name[: -len(suffix)])
    except OSError:
        pass
    return names


def _installed_flex_packs(flex_dirs: list[Path] | None) -> list[Path]:
    packs = []
    for d in flex_dirs if flex_dirs is not None else flex_pack_dirs():
        if d.is_dir():
            packs.extend(sorted(p for p in d.iterdir() if p.suffix in _FLEX_PACK_SUFFIXES))
    return packs


def flex_catalog(catalog_path: Path | None = None) -> list[dict]:
    """FLEX's catalog of every pack Image-Line offers, from its cache.json."""
    path = catalog_path or user_data_dir() / "FLEX" / "cache.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    return catalog if isinstance(catalog, list) else []


def iter_flex_presets(flex_dirs: list[Path] | None = None) -> Iterator[dict]:
    """Yield the presets in installed FLEX packs, shaped like iter_presets."""
    for pack in _installed_flex_packs(flex_dirs):
        for name in read_flex_pack_presets(pack):
            yield {
                "name": name,
                "plugin": "FLEX",
                "kind": "generator",
                "category": pack.stem,
                "source": "flex-pack",
                "path": str(pack),
            }


def list_flex_packs(
    query: str = "",
    installed_only: bool = False,
    flex_dirs: list[Path] | None = None,
    catalog_path: Path | None = None,
) -> list[dict]:
    """List FLEX packs: every pack in FLEX's catalog plus any installed ones.

    Args:
        query: Words that must all appear in the pack name, genre or instruments
        installed_only: Only list packs whose file is installed
        flex_dirs: Folders holding installed pack files (for tests)
        catalog_path: FLEX's cache.json catalog (for tests)
    """
    installed = {p.name.lower(): p for p in _installed_flex_packs(flex_dirs)}
    tokens = query.lower().split()

    packs = []
    seen = set()
    for item in flex_catalog(catalog_path):
        filename = Path(str(item.get("filename", "")).replace("\\", "/")).name
        seen.add(filename.lower())
        packs.append({
            "name": item.get("productName", filename),
            "genre": item.get("genre", ""),
            "instruments": [i for i in str(item.get("instrument", "")).split(";") if i],
            "availability": item.get("availability", ""),
            "pack_file": installed.get(filename.lower()),
        })
    for key, path in installed.items():
        if key not in seen:
            packs.append({
                "name": path.stem, "genre": "", "instruments": [], "availability": "",
                "pack_file": path,
            })

    result = []
    for pack in packs:
        path = pack.pop("pack_file")
        if installed_only and path is None:
            continue
        if not _matches(tokens, pack["name"], pack["genre"], *pack["instruments"]):
            continue
        pack["installed"] = path is not None
        pack["presets"] = len(read_flex_pack_presets(path)) if path else None
        pack["path"] = str(path) if path else ""
        result.append(pack)
    return result


# =============================================================================
# FL Cloud sounds
# =============================================================================


def cloud_sounds_dir() -> Path:
    """Where FL Studio saves samples downloaded from FL Cloud Sounds."""
    return user_data_dir() / "Downloads" / "FL CLOUD Sounds"


def _pitch_class(note: str) -> int | None:
    m = _NOTE_RE.fullmatch(note.strip())
    if not m:
        return None
    offset = {"#": 1, "b": -1}.get(m.group(2), 0)
    return (_PITCH_CLASSES[m.group(1).upper()] + offset) % 12


def parse_key(text: str) -> tuple[int, str | None] | None:
    """Parse a key like "C#", "Db minor" or "Am" into (pitch class, scale)."""
    m = _QUERY_KEY_RE.fullmatch(text)
    pc = _pitch_class(m.group(1)) if m else None
    if pc is None:
        return None
    scale = _SCALE_NAMES.get(m.group(2).lower()) if m.group(2) else None
    return pc, scale


def _key_from_name(name: str) -> tuple[str | None, str | None]:
    for token in name.split("_"):
        m = _NAME_KEY_RE.fullmatch(token)
        if m:
            scale = _SCALE_NAMES.get(m.group(2).lower()) if m.group(2) else None
            return m.group(1), scale
    return None, None


def _to_float(value: str | None) -> float | None:
    try:
        number = float(value) if value else None
    except ValueError:
        return None
    return number or None


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def iter_cloud_sounds(root: Path | None = None) -> Iterator[dict]:
    """Yield every downloaded FL Cloud sample with its metadata.

    Newer downloads come with a <sample>.nfo holding tempo, key, type, tags and
    genres. Older ones only have the filename, which usually carries the BPM
    and key, so those are parsed from it as a fallback.
    """
    root = root or cloud_sounds_dir()
    if not root.is_dir():
        return

    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in AUDIO_EXTENSIONS or not path.is_file():
            continue

        info = read_nfo(path.with_suffix(".nfo"))
        name = path.stem.removesuffix(".fldownload")
        relative = path.parent.relative_to(root).parts
        pack = relative[0] if relative else ""

        root_note = info.get("RootNote") or None
        scale = _SCALE_NAMES.get(info.get("ChordType", "").lower())
        if root_note is None:
            root_note, scale = _key_from_name(name)

        bpm = _to_float(info.get("Tempo"))
        if bpm is None:
            m = _NAME_BPM_RE.search(name)
            bpm = float(m.group(1)) if m else None

        yield {
            "name": name,
            "pack": pack,
            "vendor": info.get("Vendor", ""),
            "bpm": bpm,
            "key": root_note,
            "scale": scale,
            "type": info.get("FileType", ""),
            "genres": _split_list(info.get("Genres", "")),
            "tags": _split_list(info.get("Tags", "")),
            "has_metadata": bool(info),
            "path": str(path),
        }


def search_cloud_sounds(
    query: str = "",
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    key: str | None = None,
    file_type: str | None = None,
    limit: int = 50,
    root: Path | None = None,
) -> dict:
    """Search downloaded FL Cloud samples.

    Args:
        query: Words that must all appear in the name, pack, vendor, tags or genres
        bpm_min: Lowest tempo to include
        bpm_max: Highest tempo to include
        key: Key such as "C#", "Db minor" or "Am"; enharmonic spellings match
        file_type: "loop" or "one-shot"
        limit: Maximum number of samples to return
        root: The FL Cloud downloads folder (for tests)

    Raises:
        ValueError: If `key` can't be parsed.
    """
    tokens = query.lower().split()
    wanted_key = parse_key(key) if key else None
    if key and wanted_key is None:
        raise ValueError(f"Unrecognized key: {key!r} (try e.g. 'C#', 'Db minor', 'Am')")

    def normalize_type(value: str) -> str:
        return re.sub(r"[^a-z]", "", value.lower())

    matches = []
    for sound in iter_cloud_sounds(root):
        fields = [sound["name"], sound["pack"], sound["vendor"], *sound["tags"], *sound["genres"]]
        if not _matches(tokens, *fields):
            continue
        if bpm_min is not None and (sound["bpm"] is None or sound["bpm"] < bpm_min):
            continue
        if bpm_max is not None and (sound["bpm"] is None or sound["bpm"] > bpm_max):
            continue
        if wanted_key is not None:
            pc, scale = wanted_key
            if sound["key"] is None or _pitch_class(sound["key"]) != pc:
                continue
            if scale is not None and sound["scale"] != scale:
                continue
        if file_type and normalize_type(sound["type"]) != normalize_type(file_type):
            continue
        matches.append(sound)

    return {"total": len(matches), "sounds": matches[:limit]}
