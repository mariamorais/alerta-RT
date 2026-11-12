"""Unpack .sar via SAPCAR and parse note manifest (XML) + long text."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .config import settings


@dataclass
class NoteContent:
    long_text: str = ""
    raw_xml: str = ""
    releases: list[dict] = field(default_factory=list)       # {software_component, release, sp_from, sp_to}
    objects: list[dict] = field(default_factory=list)        # {obj_type, obj_name, version_from, version_to}
    prereqs: list[str] = field(default_factory=list)


def extract(sar_path: str) -> NoteContent:
    with tempfile.TemporaryDirectory(prefix="sapnote_") as tmp:
        _run_sapcar(sar_path, tmp)
        return _parse_dir(Path(tmp))


def _run_sapcar(sar_path: str, out_dir: str) -> None:
    cmd = [settings.sapcar_bin, "-xvf", sar_path, "-R", out_dir]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"SAPCAR failed ({res.returncode}): {res.stderr}")


def _parse_dir(root: Path) -> NoteContent:
    content = NoteContent()
    for p in root.rglob("*"):
        if p.suffix.lower() == ".xml":
            xml_bytes = p.read_bytes()
            content.raw_xml = xml_bytes.decode("utf-8", errors="replace")
            _parse_manifest(xml_bytes, content)
        elif p.suffix.lower() in {".txt", ".htm", ".html"} and "longtext" in p.name.lower():
            content.long_text = p.read_text(encoding="utf-8", errors="replace")
    return content


def _parse_manifest(xml_bytes: bytes, out: NoteContent) -> None:
    try:
        tree = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        return

    # NOTE: element names vary by SAP release; keep selectors generic.
    for rel in tree.iter():
        tag = etree.QName(rel.tag).localname.lower()
        if tag in {"validity", "release", "softwarecomponent"}:
            out.releases.append({
                "software_component": rel.get("SoftwareComponent") or rel.findtext("SoftwareComponent", ""),
                "release": rel.get("Release") or rel.findtext("Release", ""),
                "sp_from": rel.get("SpFrom") or rel.findtext("SpFrom"),
                "sp_to": rel.get("SpTo") or rel.findtext("SpTo"),
            })
        elif tag in {"object", "correctioninstruction"}:
            out.objects.append({
                "obj_type": rel.get("ObjType") or rel.findtext("ObjType", ""),
                "obj_name": rel.get("ObjName") or rel.findtext("ObjName", ""),
                "version_from": rel.get("VersionFrom") or rel.findtext("VersionFrom"),
                "version_to": rel.get("VersionTo") or rel.findtext("VersionTo"),
            })
        elif tag in {"prerequisite", "prereqnote"}:
            n = rel.get("NoteNumber") or rel.text
            if n:
                out.prereqs.append(n.strip())

    out.releases = [r for r in out.releases if r.get("software_component")]
    out.objects = [o for o in out.objects if o.get("obj_name")]
