# Non-PDF parser fixtures

`sample.html`, `sample.srt`, and `sample.vtt` are fixed byte fixtures. The focused
pytest module creates minimal DOCX, PPTX, and XLSX packages with their official
pure-Python libraries so the tests exercise real OOXML packages without storing
opaque binaries.

Each fixture intentionally includes structural features:

- DOCX: title, heading, paragraph, merged table, header, and footer.
- PPTX: ordered slides, positioned text, table, and speaker notes.
- XLSX: ordered/hidden sheets, an explicit table, merged cells, and a formula.
- HTML: headings, paragraph, list, table, figure, active content, and remote refs.
- SRT/VTT: identifiers, timestamps, speakers, metadata, and repeated cues.
