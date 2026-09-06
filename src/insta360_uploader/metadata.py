"""Spherical Video metadata injection.

Wraps the vendored `spatialmedia` package (Google's spatial-media project,
Apache 2.0, see src/spatialmedia/LICENSE) rather than hand-rolling ISOBMFF
box surgery — getting chunk-offset rewriting wrong would silently corrupt
output videos.
"""
from __future__ import annotations

from pathlib import Path

from spatialmedia import metadata_utils


class MetadataError(RuntimeError):
    pass


def inject_spherical_metadata(src: Path, dest: Path, *, projection: str = "equirectangular") -> Path:
    src, dest = Path(src), Path(dest)
    if src.resolve() == dest.resolve():
        raise MetadataError("source and destination must be different files")
    dest.parent.mkdir(parents=True, exist_ok=True)

    messages: list[str] = []
    metadata = metadata_utils.Metadata(projection, None, None)
    metadata.video = metadata_utils.generate_spherical_xml(projection)

    try:
        error = metadata_utils.inject_metadata(str(src), str(dest), metadata, messages.append)
    except Exception as exc:
        # The vendored parser isn't defensive about malformed/incomplete mp4s
        # (e.g. a file still being copied over the network) and can raise
        # raw AttributeErrors instead of returning cleanly — surface those
        # as a MetadataError with whatever it managed to log first.
        raise MetadataError("; ".join(messages) or str(exc)) from exc

    if error:
        raise MetadataError(error)
    if any(line.lower().startswith("error") for line in messages):
        raise MetadataError("; ".join(messages))
    if not dest.is_file():
        raise MetadataError(f"metadata injection did not produce {dest}")
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
