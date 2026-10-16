"""Content library tools for FL Studio: installed plugins, presets and FL Cloud sounds.

These read FL Studio's files on disk, so they work without the MIDI connection.

NOTE: Presets and samples found here have to be loaded by hand. FL Studio's
scripting API cannot load preset files or samples into a channel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_library_tools(mcp: FastMCP) -> None:
    """Register content library tools with the MCP server."""
    from fl_studio_mcp.utils import library

    @mcp.tool()
    def fl_list_installed_plugins(kind: str | None = None, query: str = "") -> dict:
        """List the plugins installed in FL Studio (native, VST, VST3, ...).

        Reads FL Studio's plugin database, so it reflects the plugin manager's
        last scan.

        Args:
            kind: "generator" (instruments) or "effect"; omit for both
            query: Words that must all appear in the plugin name or vendor
        """
        found = library.list_installed_plugins(kind=kind, query=query)
        return {"total": len(found), "plugins": found}

    @mcp.tool()
    def fl_search_presets(
        query: str = "",
        plugin: str | None = None,
        category: str | None = None,
        limit: int = 50
    ) -> dict:
        """Search the plugin preset library on disk.

        Covers FL Studio's factory .fst presets, the user's saved presets, and
        the presets inside installed FLEX packs (plugin "FLEX", with the pack
        name as the category). The result includes a per plugin/category
        breakdown of all matches, which helps narrow a broad search.

        Args:
            query: Words that must all appear in the preset name, category or plugin
            plugin: Exact plugin name, e.g. "Sytrus" or "Kepler Exo"
            category: Text that must appear in the preset's category folder, e.g. "Bass"
            limit: Maximum number of presets to return (default 50)
        """
        return library.search_presets(
            query=query, plugin=plugin, category=category, limit=limit
        )

    @mcp.tool()
    def fl_list_flex_packs(query: str = "", installed_only: bool = False) -> dict:
        """List FLEX preset packs, installed or available from Image-Line.

        Combines FLEX's pack catalog with the pack files on disk. Installed
        packs report their preset count; use fl_search_presets with
        plugin="FLEX" to see the presets themselves.

        Args:
            query: Words that must all appear in the pack name, genre or instruments
            installed_only: Only list packs that are installed
        """
        packs = library.list_flex_packs(query=query, installed_only=installed_only)
        return {
            "total": len(packs),
            "installed": sum(1 for p in packs if p["installed"]),
            "packs": packs,
        }

    @mcp.tool()
    def fl_search_cloud_sounds(
        query: str = "",
        bpm_min: float | None = None,
        bpm_max: float | None = None,
        key: str | None = None,
        file_type: str | None = None,
        limit: int = 50
    ) -> dict:
        """Search samples downloaded from FL Cloud Sounds.

        Only samples already downloaded through FL Studio's SOUNDS browser tab
        are on disk; the online catalog can't be searched from here.

        Args:
            query: Words that must all appear in the name, pack, vendor, tags or genres
            bpm_min: Lowest tempo to include
            bpm_max: Highest tempo to include
            key: Key such as "C#", "Db minor" or "Am"; enharmonic spellings match
            file_type: "loop" or "one-shot"
            limit: Maximum number of samples to return (default 50)
        """
        try:
            return library.search_cloud_sounds(
                query=query,
                bpm_min=bpm_min,
                bpm_max=bpm_max,
                key=key,
                file_type=file_type,
                limit=limit,
            )
        except ValueError as e:
            return {"error": str(e)}
