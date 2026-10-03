from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


load_dotenv()  # Load environment variables from .env file


# Module-level singleton cache
_vector_store = None


def load_policy_documents() -> list[Document]:
    """
    Load all policy documents from the project's policies/ directory.
    """

    # rag_tool.py
    #   parents[0] -> langchain_bot/
    #   parents[1] -> src/
    #   parents[2] -> project root
    project_root = Path(__file__).resolve().parent.parent.parent

    policies_dir = project_root / "policies"

    documents: list[Document] = []

    for policy_file in policies_dir.glob("*.txt"):
        loader = TextLoader(
            str(policy_file),
            encoding="utf-8",
        )

        loaded_documents = loader.load()

        for document in loaded_documents:
            document.metadata["source"] = policy_file.name

        documents.extend(loaded_documents)

    return documents


def split_documents(
    documents: list[Document],
) -> list[Document]:
    """
    Split policy documents into smaller chunks for retrieval.
    """

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
    )

    return splitter.split_documents(documents)


def get_vector_store():
    """
    Return the cached Chroma vector store.

    If a persisted Chroma database already exists, load it.
    Otherwise, create it from the policy documents.
    """

    global _vector_store

    # ---------------------------------------------------------
    # Return cached vector store if already initialized
    # ---------------------------------------------------------

    if _vector_store is not None:
        return _vector_store

    # ---------------------------------------------------------
    # Resolve project root
    # ---------------------------------------------------------

    project_root = Path(
        __file__
    ).resolve().parent.parent.parent

    persist_dir = project_root / "chroma_db"

    # ---------------------------------------------------------
    # Create embeddings model
    # ---------------------------------------------------------

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small"
    )

    # ---------------------------------------------------------
    # Load existing Chroma database
    # ---------------------------------------------------------

    if persist_dir.exists() and any(persist_dir.iterdir()):
        print("Loading existing policy vector store...")

        _vector_store = Chroma(
            persist_directory=str(persist_dir),
            embedding_function=embeddings,
        )

        print("Loaded existing policy vector store.")

        return _vector_store

    # ---------------------------------------------------------
    # Create new Chroma database
    # ---------------------------------------------------------

    print("Loading policy documents...")

    documents = load_policy_documents()

    print(
        f"Loaded {len(documents)} policy document(s)."
    )

    print("Splitting policy documents...")

    split_docs = split_documents(documents)

    print(
        f"Created {len(split_docs)} document chunk(s)."
    )

    print("Creating policy vector store...")

    persist_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    _vector_store = Chroma.from_documents(
        documents=split_docs,
        embedding=embeddings,
        persist_directory=str(persist_dir),
    )

    print("Policy vector store created.")

    return _vector_store


# =============================================================
# 8.5 — Policy Search Tool
# =============================================================

@tool
def search_policies(query: str) -> str:
    """
    Search policy and FAQ documents only.

    This tool is intended for policy/FAQ questions.
    Do not use this tool for searching or retrieving
    information about individual user orders.
    """

    vector_store = get_vector_store()

    documents = vector_store.similarity_search(
        query,
        k=4,
    )

    if not documents:
        return "No relevant policy or FAQ information was found."

    results = []

    for index, document in enumerate(documents, start=1):
        source = document.metadata.get(
            "source",
            "Unknown source",
        )

        content = document.page_content.strip()

        results.append(
            f"[Source {index}: {source}]\n{content}"
        )

    return "\n\n".join(results)


# =============================================================
# 8.6 — Vector Store Initialization
# =============================================================

def initialize_vector_store():
    """
    Initialize the policy vector store during application startup.

    This calls get_vector_store(), which either loads the
    existing persisted Chroma database or creates it if needed.
    """

    return get_vector_store()


# =============================================================
# Public API
# =============================================================

__all__ = [
    "search_policies",
    "initialize_vector_store",
]


# # =============================================================
# # Local Test
# # =============================================================

# if __name__ == "__main__":
#     initialize_vector_store()

#     result = search_policies.invoke(
#         {"query": "What is the return policy?"}
#     )
#     print(result)

