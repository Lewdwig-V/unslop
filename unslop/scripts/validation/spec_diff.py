"""Spec section diffing for surgical mode."""

from __future__ import annotations


def compute_spec_diff(old_spec: str, new_spec: str) -> dict:
    """Section-level markdown diff between two spec versions.

    Parses ``## `` headings into ``{heading: content}`` maps and compares values.

    Parameters
    ----------
    old_spec:
        The old spec markdown text.
    new_spec:
        The new spec markdown text.

    Returns
    -------
    dict with keys: changed_sections, unchanged_sections.
    """
    old_sections = _parse_md_sections(old_spec)
    new_sections = _parse_md_sections(new_spec)

    all_headings = set(old_sections.keys()) | set(new_sections.keys())
    changed: list[str] = []
    unchanged: list[str] = []

    for heading in sorted(all_headings):
        old_content = old_sections.get(heading)
        new_content = new_sections.get(heading)
        if old_content == new_content:
            unchanged.append(heading)
        else:
            changed.append(heading)

    return {"changed_sections": changed, "unchanged_sections": unchanged}


def _parse_md_sections(text: str) -> dict[str, str]:
    """Parse markdown into {heading: content} by ``## `` boundaries."""
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections
