"""ZIP inspection and safe member discovery."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Union
from zipfile import BadZipFile, ZipFile

from healthzip.config import ImportLimits


class UnsafeZipError(ValueError):
    pass


def _clear_element(elem) -> None:
    """Release element text/children and already-processed siblings."""
    elem.clear()
    parent = elem.getparent()
    if parent is not None:
        while elem.getprevious() is not None:
            del parent[0]


@dataclass
class ZipInspection:
    path: str
    file_size_bytes: int
    sha256: str
    member_count: int
    xml_member_path: Optional[str]
    xml_uncompressed_bytes: int
    total_uncompressed_bytes: int
    export_date: Optional[str]
    record_types: dict[str, int]
    node_counts: dict[str, int]
    warnings: list[str]

    def as_dict(self):
        return asdict(self)


def sha256_file(path: Union[str, Path]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_member(info, limits: ImportLimits) -> None:
    name = info.filename
    normalized = name.replace("\\", "/")
    if (
        normalized.startswith("/")
        or normalized.startswith("../")
        or "/../" in normalized
        or "\x00" in normalized
    ):
        raise UnsafeZipError(f"unsafe ZIP member path: {name!r}")
    if info.file_size > limits.max_member_uncompressed_bytes:
        raise UnsafeZipError(f"ZIP member exceeds size limit: {name}")
    if info.compress_size == 0 and info.file_size > 0:
        raise UnsafeZipError(f"invalid compression metadata: {name}")
    if info.compress_size and info.file_size / info.compress_size > limits.max_compression_ratio:
        raise UnsafeZipError(f"ZIP member compression ratio exceeds limit: {name}")
    # external_attr high mode bits may identify symlinks.
    if ((info.external_attr >> 16) & 0o170000) == 0o120000:
        raise UnsafeZipError(f"symlink-like ZIP member rejected: {name}")


def _find_xml(zf: ZipFile) -> str:
    candidates = []
    for info in zf.infolist():
        if info.filename.lower().endswith(".xml"):
            candidates.append(info.filename)
    if not candidates:
        raise ValueError("ZIP does not contain an XML export")
    # Prefer Apple's conventional path, but inspect arbitrary roots too.
    for name in candidates:
        if name.lower().endswith("export.xml"):
            return name
    return candidates[0]


def inspect_zip(path: Union[str, Path], limits: Optional[ImportLimits] = None) -> ZipInspection:
    limits = limits or ImportLimits()
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    warnings: list[str] = []
    try:
        with ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > limits.max_members:
                raise UnsafeZipError("ZIP has too many members")
            total = 0
            for info in infos:
                _validate_member(info, limits)
                total += info.file_size
            if total > limits.max_total_uncompressed_bytes:
                raise UnsafeZipError("ZIP total uncompressed size exceeds limit")
            xml_path = _find_xml(zf)
            record_types: dict[str, int] = {}
            node_counts: dict[str, int] = {}
            export_date = None
            # Small pre-scan reads XML incrementally; does not materialize it.
            from lxml import etree

            with zf.open(xml_path) as stream:
                context = etree.iterparse(
                    stream,
                    events=("end",),
                    tag=(
                        "Record",
                        "Workout",
                        "ActivitySummary",
                        "ExportDate",
                        "Correlation",
                        "ClinicalRecord",
                        "Electrocardiogram",
                    ),
                    resolve_entities=False,
                    load_dtd=False,
                    no_network=True,
                    huge_tree=False,
                )
                try:
                    for _, elem in context:
                        node_counts[elem.tag] = node_counts.get(elem.tag, 0) + 1
                        if elem.tag == "Record":
                            typ = elem.get("type", "")
                            record_types[typ] = record_types.get(typ, 0) + 1
                        elif elem.tag == "ExportDate":
                            export_date = elem.get("value")
                        _clear_element(elem)
                except etree.XMLSyntaxError as exc:
                    warnings.append(f"XML pre-scan incomplete: {str(exc)[:300]}")
                del context
            xml_info = next(i for i in infos if i.filename == xml_path)
            return ZipInspection(
                str(path),
                path.stat().st_size,
                sha256_file(path),
                len(infos),
                xml_path,
                xml_info.file_size,
                total,
                export_date,
                record_types,
                node_counts,
                warnings,
            )
    except BadZipFile as exc:
        raise UnsafeZipError("invalid ZIP file") from exc
