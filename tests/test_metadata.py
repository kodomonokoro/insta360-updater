import pytest

from insta360_uploader import metadata


def _fake_inject_metadata_no_op(input_file, output_file, metadata_obj, console):
    # Simulates the observed failure: inject_metadata() reports success
    # (no exception, falsy error, no "error"-prefixed message) but never
    # actually creates the output file.
    console("Processing: " + input_file)
    return None


def test_missing_dest_error_includes_diagnostics(tmp_path, monkeypatch):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")
    dest = tmp_path / "out" / "retagged.mp4"

    monkeypatch.setattr(metadata.metadata_utils, "inject_metadata", _fake_inject_metadata_no_op)

    with pytest.raises(metadata.MetadataError) as excinfo:
        metadata.inject_spherical_metadata(src, dest)

    message = str(excinfo.value)
    assert "did not produce" in message
    assert "elapsed=" in message
    assert "parent_exists=True" in message
    assert "free_bytes=" in message


def test_missing_dest_error_notes_missing_parent(tmp_path, monkeypatch):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")
    dest = tmp_path / "out" / "retagged.mp4"

    def fake_inject_and_delete_parent(input_file, output_file, metadata_obj, console):
        # dest.parent.mkdir() already ran before this is called; simulate
        # the directory disappearing out from under us mid-injection (e.g.
        # a network share hiccup) rather than the more common case above.
        dest.parent.rmdir()
        return None

    monkeypatch.setattr(metadata.metadata_utils, "inject_metadata", fake_inject_and_delete_parent)

    with pytest.raises(metadata.MetadataError) as excinfo:
        metadata.inject_spherical_metadata(src, dest)

    assert "parent_exists=False" in str(excinfo.value)
