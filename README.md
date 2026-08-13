# Ops Assistant Agent

A lightweight, local AI agent built from scratch in Python. It features natural language tool routing, automated system checks, and a sophisticated multi-layered memory architecture.

## 🚀 Key Features

*   **Natural Language Routing**: Interprets user requests and automatically routes them to the appropriate system tools.
*   **Safe Execution Environment**: Built-in permission checks and whitelists for dangerous operations.
*   **Multi-layered Memory System**:
    *   **Summary Layer**: Long-term state tracking and high-level context.
    *   **Keyword Index**: Fast mapping of entities and events.
    *   **Vector Engine**: Semantic search powered by `BAAI/bge-small-zh-v1.5` embeddings, persisted locally using SQLite (`vectors.db`).
    *   **Raw History**: Ground truth event logs ensuring hallucination-free retrieval.
*   **Zero-Configuration Database**: Uses standard Python `sqlite3` for vector storage. No external database servers (like Milvus or Postgres) are required.

## 🧠 Memory Architecture

The agent's `retrieve()` pipeline evaluates context by passing queries through multiple fallback layers:
1. `session_summary.json` (Global Context)
2. `session_index.json` (Keyword Matching)
3. `vectors.db` (Semantic Similarity Matching)
4. `session_history.json` (Fact Retrieval)

This guarantees that the language model always has the highest quality, conflict-resolved context before executing a prompt.

## 🛠️ Technical Stack

*   **Language**: Python 3
*   **Database**: SQLite (`vector_engine.py`)
*   **Embeddings**: `sentence-transformers` / `BAAI/bge-small-zh-v1.5` (384 dimensions)
*   *Note: If the embedding model or network fails, the vector engine gracefully degrades to a deterministic local hashing algorithm.*

## ⚙️ Quick Start

You can interact with the agent directly through the command line to avoid any terminal character encoding issues:

```powershell
# Ask the agent a question directly
python agent.py "Please check my CPU usage"

# Or run it interactively (may have encoding limitations on some Windows consoles)
python agent.py
```

## 📂 Project Structure

*   `agent.py` - Main entry point, tool registration, and routing logic.
*   `memory.py` - Multi-layered memory management and retrieval orchestration.
*   `vector_engine.py` - SQLite-backed vector store for semantic embeddings.
*   `PROJECT_CONCEPT.md` - Detailed architectural design and design principles (in Chinese).
*   `memory/` - Local directory generated at runtime to store session JSON files and `vectors.db`.
