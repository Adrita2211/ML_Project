"""
Splits OCR'd agreement text into one chunk per numbered clause (1.1, 2.3 ...)
or Exhibit, so retrieval can cite "Section 3.2" rather than a page blob.

Pure function - no AWS - so it is unit tested locally. Textract's LINE
output puts table cells on separate lines; that is good enough to embed and
for the model to read, and each chunk keeps its heading as context.
"""
import re

_END_OF_CLAUSES = re.compile("^Illustrative signatures", re.IGNORECASE)
_NOISE = re.compile(r"^(Page\s+\d+|SYNTHETIC DEMONSTRATION AGREEMENT.*)$", re.IGNORECASE)
_SUBSECTION = re.compile(r"^(\d{1,2}\.\d{1,2})\s+(\S.*)$")
_SECTION = re.compile(r"^(\d{1,2})\.\s+([A-Z]\S.*)$")
# The separator is required: a clause that wraps so a line starts "Exhibit B. If the Payer ..." is body text.
_EXHIBIT = re.compile(r"^(Exhibit\s+[A-Z])\s*[-–—:]\s*(.*)$", re.IGNORECASE)
MAX_CHUNK_CHARS = 4000


def chunk_agreement(text: str) -> list[dict]:
    """[{"section": "3.2" | "Exhibit B", "title": str, "text": str}]"""
    chunks, current = [], None

    def flush():
        if current and current["lines"]:
            body = " ".join(current["lines"]).strip()
            if body:
                chunks.append({
                    "section": current["section"],
                    "title": current["title"],
                    "text": f"{current['section']} {current['title']}. {body}"[:MAX_CHUNK_CHARS],
                })

    for raw in text.splitlines():
        line = raw.strip()
        if not line or _NOISE.match(line):
            continue
        if _END_OF_CLAUSES.match(line):
            flush()
            current = None
            continue

        exhibit = _EXHIBIT.match(line)
        subsection = _SUBSECTION.match(line)
        section = _SECTION.match(line)

        if exhibit:
            flush()
            label = re.sub(r"\s+", " ", exhibit.group(1)).title()
            current = {"section": label, "title": exhibit.group(2) or label, "lines": []}
        elif subsection:
            flush()
            current = {"section": subsection.group(1), "title": subsection.group(2), "lines": []}
        elif section:
            flush()
            current = {"section": section.group(1), "title": section.group(2), "lines": []}
        elif current is not None:
            current["lines"].append(line)
        # lines before the first clause (title page) are intentionally dropped

    flush()
    return _unique_sections(chunks)


def _unique_sections(chunks):
    """Section labels become vector keys, and a duplicate key fails the whole write. A repeated label
    (odd OCR line breaks, a genuinely repeated heading) gets a suffix instead of losing the contract."""
    seen, out = {}, []
    for chunk in chunks:
        n = seen[chunk["section"]] = seen.get(chunk["section"], 0) + 1
        out.append(chunk if n == 1 else {**chunk, "section": f'{chunk["section"]} ({n})'})
    return out
