"""Text-only and complete packages expose only media files they actually contain."""

import hashlib
import io
import json
import re
from zipfile import ZipFile

import pytest
from PIL import Image

from healthzip.db.repository import Repository
from healthzip.training.catalog_media import offline_package
from healthzip.training.service import TrainingService


def synthetic_media_repo(tmp_path):
    """Generate our own small CC0 image; no source media or network is required."""
    repo = Repository(tmp_path / "synthetic.sqlite3")
    TrainingService(repo)
    buffer = io.BytesIO()
    Image.new("RGB", (3, 2), "red").save(buffer, "PNG")
    data = buffer.getvalue()
    blob_hash = hashlib.sha256(data).hexdigest()
    blob_path = tmp_path / blob_hash
    blob_path.write_bytes(data)
    metadata = {
        "media_id": "synthetic.image.1",
        "media_type": "image",
        "source_uuid": "synthetic-text-package",
        "original_url": "https://example.invalid/synthetic-text-package.png",
        "original_work_url": "https://example.invalid/synthetic-text-package.png",
        "license_scope": "individual_media_object",
        "license": {"short_name": "CC0", "url": "https://creativecommons.org/publicdomain/zero/1.0/"},
        "author": "Synthetic Fixture Author",
        "attribution_text": "Synthetic Fixture Author · CC0 · synthetic image",
        "changes": "none; original generated fixture bytes",
        "verified_file": {"mime": "image/png", "size": len(data), "width": 3, "height": 2},
    }
    repo.conn.execute(
        "INSERT INTO catalog_source_mapping VALUES(?,?,?,?,?,?)",
        ("wger", metadata["source_uuid"], "psa.ex.plank", "exact_identity", "confirmed", "{}"),
    )
    repo.conn.execute(
        "INSERT INTO catalog_media VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            metadata["media_id"], metadata["source_uuid"], "synthetic-snapshot", "image",
            json.dumps(metadata), 1, "ready", blob_hash, str(blob_path),
            "2026-11-12T00:00:00+00:00", None,
        ),
    )
    repo.conn.commit()
    return repo, data, metadata


def embedded_catalog(html):
    return json.loads(re.search(r"const PUBLIC_CATALOG=(.*);\n", html).group(1))


@pytest.mark.parametrize("include_media", [False, True])
def test_package_html_catalog_and_attribution_reference_only_included_files(tmp_path, include_media):
    repo, image, metadata = synthetic_media_repo(tmp_path)
    output = tmp_path / "synthetic-catalog.zip"
    result = offline_package(repo, output, include_media=include_media)
    with ZipFile(output) as archive:
        embedded = embedded_catalog(archive.read("index.html").decode())
        catalog = json.loads(archive.read("catalog.json"))["items"]
        attribution = json.loads(archive.read("media-attribution.json"))
        catalogs = [[m for x in rows for m in x.get("media", [])] for rows in (embedded, catalog)]
        catalogs.append(attribution)
        expected_path = "media/" + hashlib.sha256(image).hexdigest()
        for entries in catalogs:
            assert len(entries) == 1
            entry = entries[0]
            assert entry["author"] == metadata["author"]
            assert entry["license"] == metadata["license"]
            assert "local_path" not in entry
            if include_media:
                assert entry["package_path"] == expected_path
                assert archive.read(entry["package_path"]) == image
            else:
                assert "package_path" not in entry
        assert result["exercises"] == len(embedded) == len(catalog) == 46
        assert result["media_included"] == int(include_media)
        assert len([name for name in archive.namelist() if name.startswith("media/")]) == int(include_media)
        assert archive.testzip() is None
    repo.close()
