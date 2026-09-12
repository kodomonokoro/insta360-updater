"""Spherical Video metadata injection.

Wraps the vendored `spatialmedia` package (Google's spatial-media project,
Apache 2.0, see src/spatialmedia/LICENSE) rather than hand-rolling ISOBMFF
box surgery — getting chunk-offset rewriting wrong would silently corrupt
output videos.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from spatialmedia import metadata_utils


class MetadataError(RuntimeError):
    pass


def _diagnose_missing_dest(dest: Path, elapsed: float) -> str:
    """Extra context for the "inject_metadata() reported success but dest
    isn't there" case, which is otherwise silent about what happened. Only
    called on that failure path, so the cost of listing the parent
    directory / checking free space is never paid on the success path."""
    parts = [f"elapsed={elapsed:.1f}s"]
    parent = dest.parent
    try:
        parent_exists = parent.is_dir()
    except OSError as exc:
        parts.append(f"parent_check_failed={exc}")
        parent_exists = False
    parts.append(f"parent_exists={parent_exists}")
    if parent_exists:
        try:
            siblings = sorted(p.name for p in parent.iterdir())
        except OSError as exc:
            parts.append(f"parent_listing_failed={exc}")
        else:
            parts.append(f"parent_contents={siblings}")
    try:
        usage = shutil.disk_usage(parent)
    except OSError as exc:
        parts.append(f"disk_usage_failed={exc}")
    else:
        parts.append(f"free_bytes={usage.free}")
    return "; ".join(parts)


def inject_spherical_metadata(src: Path, dest: Path, *, projection: str = "equirectangular") -> Path:
    src, dest = Path(src), Path(dest)
    if src.resolve() == dest.resolve():
        raise MetadataError("source and destination must be different files")
    dest.parent.mkdir(parents=True, exist_ok=True)

    messages: list[str] = []
    metadata = metadata_utils.Metadata(projection, None, None)
    metadata.video = metadata_utils.generate_spherical_xml(projection)

    start = time.monotonic()
    try:
        error = metadata_utils.inject_metadata(str(src), str(dest), metadata, messages.append)
    except Exception as exc:
        # The vendored parser isn't defensive about malformed/incomplete mp4s
        # (e.g. a file still being copied over the network) and can raise
        # raw AttributeErrors instead of returning cleanly — surface those
        # as a MetadataError with whatever it managed to log first.
        raise MetadataError("; ".join(messages) or str(exc)) from exc
    elapsed = time.monotonic() - start

    if error:
        raise MetadataError(error)
    if any(line.lower().startswith("error") for line in messages):
        raise MetadataError("; ".join(messages))
    if not dest.is_file():
        diagnostics = _diagnose_missing_dest(dest, elapsed)
        raise MetadataError(f"metadata injection did not produce {dest} ({diagnostics})")
    return dest


def has_spherical_metadata(path: Path) -> bool:
    """Best-effort check for an existing Spherical Video V1 XML/uuid box.

    Used as a safety net: Insta360 Studio's "360 Panorama" export already
    embeds this, so this should normally return True and we skip
    re-injecting. A False here doesn't prove the file will fail on
    YouTube (Studio may use a different tagging convention), but if it
    fires we inject our own well-tested tag rather than gamble.
    """
    try:
        parsed = metadata_utils.parse_mpeg4(str(path), lambda _msg: None)
    except Exception as exc:
        raise MetadataError(f"could not read {path}: {exc}") from exc
    return bool(parsed and parsed.video)
