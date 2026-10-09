"""Recover exact source spans from unique layout-only matches."""
import re
from src.extraction.schemas import FIELDS


def canonical(text):
    chars, spans = [], []
    for match in re.finditer(r'(?<=[A-Za-z])-\s*\n\s*(?=[a-z])|\s+|[^\s]', text):
        token = match.group()
        if token.startswith('-') and '\n' in token:
            continue
        chars.append(' ' if token.isspace() else token)
        spans.append((match.start(), match.end()))
    return ''.join(chars), spans


def recover_evidence(record, chunk):
    result = record.model_copy(deep=True)
    groups = [getattr(result, name).evidence for name in FIELDS if getattr(result, name)]
    for relation in result.relations:
        groups.append(relation.evidence)
        if relation.operating_conditions:
            groups.append(relation.operating_conditions.evidence)
    source, spans = canonical(chunk.text)
    repairs = []
    for group in groups:
        for ev in group:
            if any(getattr(ev, key) != getattr(chunk, key) for key in ('document_id', 'document_name', 'page', 'chunk_id')):
                continue
            if ev.quote in chunk.text:
                continue
            quote, _ = canonical(ev.quote)
            quote = quote.strip()
            if not quote:
                continue
            start = source.find(quote)
            if start < 0 or source.find(quote, start + 1) >= 0:
                continue
            end = start + len(quote)
            if ((start and source[start-1].isalnum() and quote[0].isalnum()) or
                    (end < len(source) and source[end].isalnum() and quote[-1].isalnum())):
                continue
            exact = chunk.text[spans[start][0]:spans[end-1][1]]
            repairs.append({'original_quote': ev.quote, 'source_quote': exact,
                            'chunk_id': chunk.chunk_id, 'method': 'unique_layout_match'})
            ev.quote = exact
    return result, repairs
