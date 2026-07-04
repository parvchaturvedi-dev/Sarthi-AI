"""PDF analysis + question-answering — fully offline.

Pipeline: PyMuPDF extracts text per page -> chunk -> embed (nomic-embed) -> on a
question, cosine-retrieve the most relevant chunks -> the local LLM answers,
grounded in them (with page numbers). Scanned/image pages (no extractable text)
fall back to OCR (RapidOCR) so image-only PDFs still work.

Nothing leaves the machine — same local Ollama models used everywhere else.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

from ..memory.vectors import top_k

log = logging.getLogger("nova.pdf")

_ANSWER_SYSTEM = {
    "hinglish": (
        "You are Sarthi. Answer the question using ONLY the PDF excerpts given. "
        "Be accurate and specific — quote real numbers, names, dates from the text. "
        "Reply in casual HINGLISH (Roman, female). Mention the page number when "
        "useful. If the excerpts don't answer it, say so honestly. No Devanagari."
    ),
    "hindi": (
        "तुम सारथी हो। सिर्फ़ दिए गए PDF अंशों से सवाल का उत्तर देवनागरी हिंदी में दो — "
        "सटीक तथ्य, नाम, तारीख़ें दो। ज़रूरत हो तो पेज नंबर बताओ। अगर अंशों में उत्तर "
        "नहीं है तो साफ़ कह दो।"
    ),
    "english": (
        "You are Sarthi. Answer the question using ONLY the provided PDF excerpts. "
        "Be accurate and specific — quote real numbers, names, dates. Cite the page "
        "number when useful. If the excerpts don't answer it, say so honestly."
    ),
}


def _chunk(text: str, size: int = 900, overlap: int = 150) -> List[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= size:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


class PdfDoc:
    def __init__(self, path: str, embedder, llm, language: str = "english"):
        self.path = str(Path(path))
        self.name = Path(path).name
        self.embedder = embedder            # text -> vector (nomic-embed)
        self.llm = llm
        self.language = language
        self.chunks: List[dict] = []        # {text, page, vec}
        self.pages = 0
        self._ocr = None

    # --- build ------------------------------------------------------------
    def build(self) -> int:
        """Extract, chunk and embed the PDF. Returns the number of chunks."""
        import fitz  # PyMuPDF

        doc = fitz.open(self.path)
        self.pages = doc.page_count
        raw: List[Tuple[int, str]] = []
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            text = page.get_text("text") or ""
            if len(text.strip()) < 20:      # likely scanned -> OCR the page image
                text = self._ocr_page(page) or text
            for ch in _chunk(text):
                raw.append((pno + 1, ch))
        doc.close()

        for page, ch in raw:
            vec = None
            if self.embedder:
                try:
                    vec = self.embedder(ch)
                except Exception:
                    vec = None
            self.chunks.append({"text": ch, "page": page, "vec": vec})
        log.info("indexed %s: %d pages, %d chunks", self.name, self.pages, len(self.chunks))
        return len(self.chunks)

    def _ocr_page(self, page) -> Optional[str]:
        try:
            import numpy as np

            if self._ocr is None:
                from ..vision.ocr import OcrEngine
                self._ocr = OcrEngine()
            if not self._ocr.available:
                return None
            pix = page.get_pixmap(dpi=180)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            bgr = img[:, :, :3][:, :, ::-1]
            boxes = self._ocr.read_image(bgr)
            return " ".join(b.text for b in boxes)
        except Exception as e:  # noqa: BLE001
            log.info("page OCR failed: %s", e)
            return None

    # --- query ------------------------------------------------------------
    def _retrieve(self, question: str, k: int = 5) -> List[dict]:
        vecs = [(i, c["vec"]) for i, c in enumerate(self.chunks) if c.get("vec")]
        if self.embedder and vecs:
            try:
                qv = self.embedder(question)
                if qv:
                    ranked = top_k(qv, [(str(i), v) for i, v in vecs], k=k, min_score=0.0)
                    return [self.chunks[int(i)] for i, _ in ranked]
            except Exception:
                pass
        return self.chunks[:k]              # fallback: first chunks

    def answer(self, question: str, k: int = 5) -> str:
        if not self.chunks:
            return "Is PDF me padhne layak text nahi mila."
        hits = self._retrieve(question, k=k)
        context = "\n\n".join(f"[page {h['page']}] {h['text']}" for h in hits)
        if self.llm is None:
            return hits[0]["text"][:500]
        system = _ANSWER_SYSTEM.get(self.language, _ANSWER_SYSTEM["english"])
        user = f"PDF EXCERPTS:\n{context}\n\nQUESTION: {question}\n\nAnswer now."
        reply = self.llm.chat_text(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
        )
        return (reply or hits[0]["text"][:500]).strip()

    def summary(self) -> str:
        if not self.chunks:
            return f"{self.name} me koi text nahi mila (shayad scanned/empty)."
        head = "\n\n".join(c["text"] for c in self.chunks[:6])[:4000]
        if self.llm is None:
            return head[:600]
        system = _ANSWER_SYSTEM.get(self.language, _ANSWER_SYSTEM["english"])
        user = (f"Summarise this PDF ('{self.name}', {self.pages} pages) in a few "
                f"clear sentences — what is it about, key points:\n\n{head}")
        reply = self.llm.chat_text(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
        )
        return (reply or head[:600]).strip()
