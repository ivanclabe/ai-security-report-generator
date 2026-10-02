"""Embeds the report's heading font (Poppins, SIL OFL -- assets/fonts/OFL.txt) in the .docx,
so headings look the same in Word on any computer and in the PDF the server renders with
LibreOffice, whether or not the font is installed there.

OOXML stores embedded fonts "obfuscated" (ECMA-376 Part 1, §17.8.1): the first 32 bytes
of the font are XOR-ed with a key derived from a GUID that the font table declares.
"""
import uuid
from pathlib import Path

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from lxml import etree

FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
OBFUSCATED_FONT = "application/vnd.openxmlformats-officedocument.obfuscatedFont"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _obfuscate(data: bytes, guid: uuid.UUID) -> bytes:
    hex_key = guid.hex  # 32 hex digits
    key = bytes(int(hex_key[i:i + 2], 16) for i in range(30, -1, -2))  # byte order reversed
    head = bytes(b ^ key[i % 16] for i, b in enumerate(data[:32]))
    return head + data[32:]


def embed_font(document, family: str, files: dict[str, str]) -> None:
    """files: {"regular" | "bold" | "italic" | "boldItalic": file name in assets/fonts}."""
    font_table = document.part.part_related_by(RT.FONT_TABLE)
    root = parse_xml(font_table.blob)
    font = next((f for f in root.findall(qn("w:font")) if f.get(qn("w:name")) == family), None)
    if font is None:
        font = parse_xml(f'<w:font xmlns:w="{W_NS}" w:name="{family}"><w:charset w:val="00"/>'
                         '<w:family w:val="swiss"/><w:pitch w:val="variable"/></w:font>')
        root.append(font)
    for index, (style, file_name) in enumerate(files.items(), start=1):
        path = FONTS_DIR / file_name
        if not path.is_file():
            continue
        guid = uuid.uuid4()
        partname = PackURI(f"/word/fonts/{family.lower()}{index}.odttf")
        part = Part(partname, OBFUSCATED_FONT, _obfuscate(path.read_bytes(), guid), document.part.package)
        r_id = font_table.relate_to(part, RT.FONT)
        tag = {"regular": "embedRegular", "bold": "embedBold", "italic": "embedItalic", "boldItalic": "embedBoldItalic"}[style]
        element = parse_xml(f'<w:{tag} xmlns:w="{W_NS}" xmlns:r="{R_NS}" r:id="{r_id}" w:fontKey="{{{str(guid).upper()}}}"/>')
        font.append(element)
    font_table._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    settings = document.settings.element
    if settings.find(qn("w:embedTrueTypeFonts")) is None:
        # schema order: writeProtection, view, zoom, ... embedTrueTypeFonts -- right after those
        anchor = None
        for tag in ("w:writeProtection", "w:view", "w:zoom", "w:removePersonalInformation", "w:removeDateAndTime"):
            found = settings.find(qn(tag))
            if found is not None:
                anchor = found
        element = parse_xml(f'<w:embedTrueTypeFonts xmlns:w="{W_NS}"/>')
        if anchor is None:
            settings.insert(0, element)
        else:
            anchor.addnext(element)
