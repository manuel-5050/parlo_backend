import re


def _tail(text: str, overlap: int) -> str:
    """The last few characters of a chunk, starting at a word boundary."""
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else ""


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    """Cut one very long paragraph into overlapping pieces, preferring word boundaries."""
    pieces = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + max_chars // 2, end)
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        space = text.find(" ", start, end)
        if space != -1:
            start = space + 1
    return pieces


def split_text(text: str, max_chars: int = 1000, overlap: int = 150) -> list[str]:
    """Split text into chunks of at most `max_chars`, keeping paragraphs together.

    Neighbouring chunks share a little text (`overlap`) so an answer that sits on a
    boundary is still found.
    """
    text = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n")).strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long(paragraph, max_chars, overlap))
            continue
        if not current:
            current = paragraph
        elif len(current) + 2 + len(paragraph) <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            tail = _tail(current, overlap)
            if tail and len(tail) + 2 + len(paragraph) <= max_chars:
                current = f"{tail}\n\n{paragraph}"
            else:
                current = paragraph
    if current:
        chunks.append(current)
    return chunks
