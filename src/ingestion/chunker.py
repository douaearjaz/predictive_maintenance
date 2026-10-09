"""Character windows adapted from the legacy parser, bounded to one page."""
import re
from src.extraction.schemas import Chunk
from src.io_utils import digest


def chunk_page(text, document_id, document_name, page, chunk_size=1500, overlap=300):
    if not 0 <= overlap < chunk_size:
        raise ValueError("Require 0 <= overlap < chunk_size")
    chunks = []
    boundaries = [m.end() for m in re.finditer(r"\S+\s*", text)]
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        # Prefer a line boundary without changing the source characters.
        if end < len(text):
            boundary = text.rfind("\n", start + max(overlap + 1, chunk_size // 2), end)
            if boundary >= 0:
                end = boundary + 1
            else:
                before = [b for b in boundaries if start < b <= end]
                end = before[-1] if before else next(b for b in boundaries if b > start)
        part = text[start:end]
        if part.strip():
            chunk_id = "CHK_" + digest([document_id, document_name, page, start, end, part])[:24]
            chunks.append(Chunk(document_id=document_id, document_name=document_name,
                                page=page, chunk_id=chunk_id, text=part, start=start, end=end))
        if end == len(text):
            break
        choices = [b for b in boundaries if start < b <= end - overlap]
        start = choices[-1] if choices else end
    return chunks
