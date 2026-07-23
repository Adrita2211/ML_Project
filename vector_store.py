"""Build a FAISS vector store over the mock product docs."""

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from knowledge_base import DOCUMENTS

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def build_vector_store() -> FAISS:
    """Chunk the mock docs and index them in FAISS."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80)
    docs = [
        Document(page_content=d["content"].strip(), metadata={"title": d["title"]})
        for d in DOCUMENTS
    ]
    chunks = splitter.split_documents(docs)
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    return FAISS.from_documents(chunks, embeddings)
