"""Content hashing and header parsing for managed files."""

from __future__ import annotations

import hashlib
import re


# Sentinels stored in concrete-manifest when a transitive dep is missing/unreadable.
MISSING_SENTINEL = "missing00000"  # 12 chars, not valid hex
UNREADABLE_SENTINEL = "unreadabl000"  # 12 chars, not valid hex

_SENTINEL_HASHES = {MISSING_SENTINEL, UNREADABLE_SENTINEL}


def compute_hash(content: str) -> str:
    """SHA-256 hash of content, truncated to 12 hex chars.

    Content is stripped of leading/trailing whitespace before hashing
    to normalize across platforms.
    """
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:12]


def parse_header(content: str) -> dict | None:
    """Parse @unslop-managed header from a managed file.

    Reads the first 5 lines looking for the header markers.
    Returns dict with spec_path, spec_hash, output_hash, generated, old_format,
    concrete_deps_hash (legacy), and concrete_manifest (new per-dep format).

    concrete_manifest is a dict of {dep_path: hash} parsed from:
      concrete-manifest:dep1.impl.md:a3f8c2e9b7d1,dep2.impl.md:7f2e1b8a9c04
    """
    lines = content.split("\n")[:5]

    spec_path = None
    spec_hash = None
    output_hash = None
    principles_hash = None
    concrete_deps_hash = None
    concrete_manifest = None
    generated = None
    old_format = False

    for line in lines:
        stripped = line.strip()
        for prefix in ["#", "//", "--", "/*", "<!--"]:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :].strip()
                break
        for suffix in ["*/", "-->"]:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)].strip()

        if "@unslop-managed" in stripped:
            m = re.search(r"Edit (.+?) instead", stripped)
            if m:
                spec_path = m.group(1)

        hash_match = re.search(r"spec-hash:([0-9a-f]{12})", stripped)
        if hash_match:
            spec_hash = hash_match.group(1)
            out_match = re.search(r"output-hash:([0-9a-f]{12})", stripped)
            if out_match:
                output_hash = out_match.group(1)
            prin_match = re.search(r"principles-hash:([0-9a-f]{12})", stripped)
            if prin_match:
                principles_hash = prin_match.group(1)
            cdeps_match = re.search(r"concrete-deps-hash:([0-9a-f]{12})", stripped)
            if cdeps_match:
                concrete_deps_hash = cdeps_match.group(1)
            gen_match = re.search(r"generated:(\S+)", stripped)
            if gen_match:
                generated = gen_match.group(1)

        # Parse concrete-manifest (new per-dep format)
        manifest_match = re.search(r"concrete-manifest:(.+?)(?:\s|$)", stripped)
        if manifest_match:
            raw = manifest_match.group(1)
            manifest = {}
            for entry in raw.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                # Format: path/to/dep.impl.md:a3f8c2e9b7d1
                last_colon = entry.rfind(":")
                if last_colon > 0:
                    dep_path = entry[:last_colon]
                    dep_hash = entry[last_colon + 1 :]
                    if re.match(r"^[0-9a-f]{12}$", dep_hash) or dep_hash in _SENTINEL_HASHES:
                        manifest[dep_path] = dep_hash
            if manifest:
                concrete_manifest = manifest

        if "Generated from spec at" in stripped and spec_hash is None:
            old_format = True
            gen_match = re.search(r"Generated from spec at (\S+)", stripped)
            if gen_match:
                generated = gen_match.group(1)

    if spec_path is None:
        return None

    return {
        "spec_path": spec_path,
        "spec_hash": spec_hash,
        "output_hash": output_hash,
        "principles_hash": principles_hash,
        "concrete_deps_hash": concrete_deps_hash,
        "concrete_manifest": concrete_manifest,
        "generated": generated,
        "old_format": old_format,
    }


def get_body_below_header(content: str) -> str:
    """Extract managed file content below the @unslop-managed header.

    Scans the first 5 lines for header markers, skipping blank lines.
    Returns everything after the last header line.
    """
    lines = content.split("\n")
    header_markers = ("@unslop-managed", "spec-hash:", "output-hash:", "Generated from spec at", "concrete-manifest:")
    body_start = 0
    for i in range(min(5, len(lines))):
        stripped = lines[i].strip()
        if any(m in stripped for m in header_markers) or stripped == "":
            body_start = i + 1
        else:
            break
    return "\n".join(lines[body_start:])
