from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from healthzip.importers.apple_zip import UnsafeZipError, inspect_zip


def test_zip_inspection_finds_arbitrary_export_path(fixture_zip):
    info = inspect_zip(fixture_zip)
    assert info.xml_member_path.endswith("export.xml")
    assert info.record_types["HKQuantityTypeIdentifierHeartRate"] > 0


def test_zip_slip_rejected(tmp_path):
    p = tmp_path / "evil.zip"
    with ZipFile(p, "w", ZIP_DEFLATED) as z:
        z.writestr("../export.xml", "<HealthData/>")
    with pytest.raises(UnsafeZipError):
        inspect_zip(p)
