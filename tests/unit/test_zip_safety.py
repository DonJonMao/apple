from zipfile import ZIP_DEFLATED, ZipExtFile, ZipFile

import pytest

from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.importers.apple_zip import UnsafeZipError, _find_xml, inspect_zip

HEALTH_XML = (
    '<HealthData><Record type="HKQuantityTypeIdentifierRestingHeartRate" '
    'value="55" unit="count/min" startDate="2026-11-01 08:00:00 +0800" '
    'endDate="2026-11-01 08:00:00 +0800"/></HealthData>'
)


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


@pytest.mark.parametrize("name", ["导出.xml", "σ»╝σç║.xml"])
def test_cda_first_localized_health_root_is_selected_and_imported(tmp_path, name):
    path = tmp_path / "synthetic-localized.zip"
    member = "apple_health_export/" + name
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("apple_health_export/export_cda.xml", "<ClinicalDocument><Record/></ClinicalDocument>")
        archive.writestr(member, HEALTH_XML)
    inspection = inspect_zip(path)
    assert inspection.xml_member_path == member
    assert inspection.record_types == {"HKQuantityTypeIdentifierRestingHeartRate": 1}
    repo = Repository(tmp_path / "synthetic.sqlite3")
    try:
        result = import_apple_zip(path, repo)
        assert result.status == "completed" and result.records_inserted == 1
        assert repo.count("health_sample") == 1
    finally:
        repo.close()


def test_conventional_name_wins_only_when_its_root_is_health_data(tmp_path):
    path = tmp_path / "synthetic-conventional.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("导出.xml", "<HealthData/>")
        archive.writestr("nested/export.xml", HEALTH_XML)
    inspection = inspect_zip(path)
    assert inspection.xml_member_path == "nested/export.xml"
    assert inspection.record_types == {"HKQuantityTypeIdentifierRestingHeartRate": 1}


def test_conventional_unrelated_xml_does_not_mask_localized_health_export(tmp_path):
    path = tmp_path / "synthetic-wrong-conventional.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("export.xml", "<Envelope><HealthData/></Envelope>")
        archive.writestr("nested/导出.xml", HEALTH_XML)
    assert inspect_zip(path).xml_member_path == "nested/导出.xml"


@pytest.mark.parametrize("document", ["<ClinicalDocument/>", "<Envelope><HealthData/></Envelope>", "<broken"])
def test_no_health_data_root_is_rejected_before_import_batch(tmp_path, document):
    path = tmp_path / "synthetic-no-health-data.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("export.xml", document)
    repo = Repository(tmp_path / "synthetic.sqlite3")
    try:
        with pytest.raises(ValueError, match="HealthData XML root"):
            import_apple_zip(path, repo)
        assert repo.one("SELECT count(*) FROM import_batch")[0] == 0
        assert repo.count("health_sample") == 0
    finally:
        repo.close()


def test_root_discovery_stops_before_large_document_body(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-large-body.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("first.xml", "<ClinicalDocument>" + "x" * 2_000_000 + "</ClinicalDocument>")
        archive.writestr("导出.xml", "<HealthData>" + "x" * 2_000_000 + "</HealthData>")
    original = ZipExtFile.read
    read_sizes = []

    def bounded_read(self, size=-1):
        assert size > 0, "root discovery must never read a whole XML member"
        data = original(self, size)
        read_sizes.append(len(data))
        return data

    monkeypatch.setattr(ZipExtFile, "read", bounded_read)
    with ZipFile(path) as archive:
        assert _find_xml(archive) == "导出.xml"
    assert sum(read_sizes) < 32_768


def test_root_discovery_caps_unterminated_prolog(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-long-prolog.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("export.xml", "<!--" + "x" * 2_000_000 + "--><HealthData/>")
    original = ZipExtFile.read
    bytes_read = 0

    def bounded_read(self, size=-1):
        nonlocal bytes_read
        assert size > 0
        data = original(self, size)
        bytes_read += len(data)
        return data

    monkeypatch.setattr(ZipExtFile, "read", bounded_read)
    with ZipFile(path) as archive, pytest.raises(ValueError, match="inspection limit"):
        _find_xml(archive)
    assert bytes_read == 1024 * 1024


def test_health_data_root_keeps_malformed_body_partial_import(tmp_path):
    path = tmp_path / "synthetic-malformed-body.zip"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("导出.xml", HEALTH_XML.replace("</HealthData>", "</Wrong>"))
    inspection = inspect_zip(path)
    assert inspection.xml_member_path == "导出.xml" and inspection.warnings
    repo = Repository(tmp_path / "synthetic.sqlite3")
    try:
        result = import_apple_zip(path, repo)
        assert result.status == "partial_failed" and result.errors_count >= 1
    finally:
        repo.close()


def test_root_discovery_does_not_load_external_dtd_or_expand_entities(tmp_path):
    path = tmp_path / "synthetic-external.zip"
    # Invalid external DTD would fail parsing if it were loaded. The external
    # entity remains unresolved; neither is needed to identify HealthData.
    dtd = tmp_path / "synthetic-external.dtd"
    dtd.write_text("this is not a DTD")
    entity = tmp_path / "synthetic-entity.txt"
    entity.write_text("<Record type='should-never-be-expanded'/>")
    document = (f'<!DOCTYPE HealthData SYSTEM "{dtd.as_uri()}" '
                f'[<!ENTITY external SYSTEM "{entity.as_uri()}">]>'
                + HEALTH_XML.replace("<HealthData>", "<HealthData>&external;"))
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("导出.xml", document)
    inspection = inspect_zip(path)
    assert not inspection.warnings
    assert inspection.record_types == {"HKQuantityTypeIdentifierRestingHeartRate": 1}
