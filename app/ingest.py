"""
Document ingestion pipeline:
PDF/DOCX/TXT/MD/URL -> per-page (or pseudo-page) text extraction ->
sentence-aware overlapping chunking -> embedding -> ChromaDB upsert ->
Document row in SQL DB.
"""
import re
import uuid

import fitz  # pymupdf
import chromadb
import requests
from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from sentence_transformers import SentenceTransformer

from app import config

_chroma_client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
collection = _chroma_client.get_or_create_collection("documents")

_embedder = SentenceTransformer(config.EMBEDDING_MODEL)


def split_text(text: str, chunk_size: int = config.CHUNK_SIZE, overlap: int = config.CHUNK_OVERLAP):
    """Sentence-aware chunking: packs whole sentences into ~chunk_size windows
    with overlap, instead of blindly cutting mid-sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current = [], ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= chunk_size:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            # start next chunk with overlap tail of previous chunk
            tail = current[-overlap:] if len(current) > overlap else current
            current = f"{tail} {sentence}".strip()

    if current:
        chunks.append(current)

    return chunks if chunks else [text[:chunk_size]]


def _index_page(filename: str, page_num: int, text: str) -> int:
    """Chunks one page's worth of text, embeds it, and upserts into Chroma.
    Returns the number of chunks written."""
    if not text.strip():
        return 0

    page_chunks = split_text(text)
    if not page_chunks:
        return 0

    embeddings = _embedder.encode(page_chunks).tolist()
    ids = [str(uuid.uuid4()) for _ in page_chunks]
    metadatas = [
        {
            "source": filename,
            "page": page_num,
            "chunk": i,
            "chunk_size": len(chunk),
        }
        for i, chunk in enumerate(page_chunks)
    ]

    collection.add(ids=ids, embeddings=embeddings, documents=page_chunks, metadatas=metadatas)
    return len(page_chunks)


def _index_flat_text(filename: str, text: str, pseudo_page_size: int = 2500):
    """For formats without a native page concept (docx/txt/md/url): splits the
    full text into pseudo-pages so the rest of the pipeline (page citations,
    per-document chunk counts) behaves the same as PDF ingestion."""
    text = text.strip()
    if not text:
        return 0, 0

    pseudo_pages = [text[i:i + pseudo_page_size] for i in range(0, len(text), pseudo_page_size)] or [text]
    total_chunks = 0
    for i, page_text in enumerate(pseudo_pages):
        total_chunks += _index_page(filename, i + 1, page_text)

    return total_chunks, len(pseudo_pages)


def ingest_pdf(pdf_path: str, filename: str):
    doc = fitz.open(pdf_path)
    total_chunks = 0
    page_count = len(doc)

    for page_num in range(page_count):
        text = doc[page_num].get_text()
        total_chunks += _index_page(filename, page_num + 1, text)

    return total_chunks, page_count


def ingest_docx(docx_path: str, filename: str):
    doc = DocxDocument(docx_path)
    full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return _index_flat_text(filename, full_text)


def ingest_txt(txt_path: str, filename: str):
    with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
        full_text = f.read()
    return _index_flat_text(filename, full_text)


def ingest_url(url: str):
    """Fetches a web page, strips boilerplate/script/style, and indexes the
    readable text. Returns (chunks, pseudo_pages, resolved_title)."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; EnterpriseAgenticRAG/1.0)"}
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else url)
    full_text = re.sub(r"\n{2,}", "\n", soup.get_text(separator="\n")).strip()

    chunks, pages = _index_flat_text(url, full_text)
    return chunks, pages, title


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def ingest_by_extension(file_path: str, filename: str, extension: str):
    """Dispatches to the right ingestion routine based on file extension."""
    if extension == ".pdf":
        return ingest_pdf(file_path, filename)
    if extension == ".docx":
        return ingest_docx(file_path, filename)
    if extension in (".txt", ".md"):
        return ingest_txt(file_path, filename)
    raise ValueError(f"Unsupported file type: {extension}")


def delete_document(filename: str):
    collection.delete(where={"source": filename})
