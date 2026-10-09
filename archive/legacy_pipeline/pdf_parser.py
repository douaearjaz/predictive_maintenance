import fitz
from pathlib import Path
import os
import json
import time
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# =====================================================================
# CONFIGURATION
# =====================================================================

# Path to the partial checkpoint file (updated after each chunk)
CHECKPOINT_FILE = Path("knowledge_graph_partial.json")

# Set to a small number (e.g., 5) for testing, or None to process all chunks
MAX_CHUNKS_TO_PROCESS = None  # e.g., 5

# Keywords to filter chunks: only chunks containing at least one are sent to LLM
RELEVANCE_KEYWORDS = [
    "bearing", "motor", "gearbox", "vibration", "failure", "fault",
    "overheating", "lubrication", "misalignment", "imbalance", "crack",
    "corrosion", "fatigue", "maintenance", "inspection", "diagnosis",
    "sensor", "temperature", "pressure", "current", "torque",
    "pump", "compressor", "turbine", "shaft", "rotor", "stator"
]
CHUNKS_PER_RUN = 60  # à ajuster selon votre quota journalier
# =====================================================================
# 1. PDF Text Extraction (unchanged)
# =====================================================================

def extract_pdf_text(pdf_path):
    doc = fitz.open(pdf_path)
    text = [page.get_text() for page in doc]
    return "\n".join(text)

def parse_directory(pdf_dir):
    documents = []
    pdf_files = list(Path(pdf_dir).rglob("*.pdf"))
    for pdf_file in pdf_files:
        try:
            text = extract_pdf_text(pdf_file)
            documents.append({
                "file": pdf_file.name,
                "path": str(pdf_file),
                "text": text
            })
        except Exception as e:
            print(f"Failed {pdf_file}: {e}")
    return documents

# =====================================================================
# 2. Chunking
# =====================================================================

def chunk_text(text, chunk_size=1500, overlap=300):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += (chunk_size - overlap)
    return chunks

# =====================================================================
# 3. Relevance filtering
# =====================================================================

def is_chunk_relevant(chunk, keywords, min_matches=2):
    chunk_lower = chunk.lower()
    matches = sum(1 for kw in keywords if kw.lower() in chunk_lower)
    return matches >= min_matches

# =====================================================================
# 4. Prompt and LLM extraction (Groq)
# =====================================================================

EXTRACTION_PROMPT = """
You are an ontology engineer specialized in predictive maintenance of motors.

Extract ONLY information explicitly mentioned.

Identify:
1. Components
2. Failure Modes
3. Symptoms
4. Causes
5. Maintenance Actions
6. Sensors
7. Measurements

Then extract semantic relations.

Allowed relation types:
hasFailureMode
causes
indicates
measuredBy
requiresMaintenance
partOf
detectedBy

Ignore:
- Authors
- Universities
- Conferences
- Research methods
- Machine learning algorithms
- Publications
- Companies
- Projects
- Datasets

Extract ONLY predictive maintenance domain knowledge.

Return ONLY valid JSON.

Schema:
{
  "entities":[
    {"name":"", "type":""}
  ],
  "relations":[
    {"subject":"", "predicate":"", "object":""}
  ]
}

TEXT:
<<TEXT>>
"""

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ.get("GROQ_API_KEY"),
)

def extract_knowledge(chunk, model="llama-3.1-8b-instant", max_retries=5):
    prompt = EXTRACTION_PROMPT.replace("<<TEXT>>", chunk)
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that outputs only JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=2048
            )
            return response.choices[0].message.content
        except Exception as e:
            error_msg = str(e).lower()
            if "rate limit" in str(e).lower() and attempt == max_retries - 1:
                            print("Limite de taux atteinte. Arrêt du script. Relancez demain.")
                            raise SystemExit(0)  # ou return None et sortir de la boucle
            print(f"Error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return None

# =====================================================================
# 5. Checkpoint management
# =====================================================================

def load_checkpoint():
    """Load the partial knowledge graph from checkpoint file."""
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_checkpoint(graph):
    """Save the partial knowledge graph to checkpoint file."""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

# =====================================================================
# 6. Estimation: count total chunks and relevant chunks
# =====================================================================

def estimate_chunks(documents, chunk_size=1000, overlap=100):
    total_chunks = 0
    relevant_chunks = 0
    for doc in documents:
        chunks = chunk_text(doc["text"], chunk_size, overlap)
        total_chunks += len(chunks)
        relevant_chunks += sum(1 for c in chunks if is_chunk_relevant(c, RELEVANCE_KEYWORDS))
    return total_chunks, relevant_chunks

# =====================================================================
# 7. Main processing with checkpoint/resume
# =====================================================================

def process_documents(documents, max_chunks=None):
    # Load existing progress
    knowledge_graph = load_checkpoint()
    processed_keys = set()
    for item in knowledge_graph:
        if "chunk_id" in item:
            processed_keys.add(item["chunk_id"])

    processed_count = len(knowledge_graph)

    # Generate all chunk IDs and process
    total_chunks_processed = 0
    chunk_counter = 0

    for doc in documents:
        doc_path = doc["path"]
        chunks = chunk_text(doc["text"])
        
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{doc_path}::chunk_{idx}"
            chunk_counter += 1

            # Check if we've hit the max limit
            if max_chunks is not None and total_chunks_processed >= max_chunks:
                print(f"Reached MAX_CHUNKS_TO_PROCESS ({max_chunks}). Stopping.")
                return knowledge_graph

            # Skip if already processed
            if chunk_id in processed_keys:
                continue

            # Skip irrelevant chunks to save tokens
            if not is_chunk_relevant(chunk, RELEVANCE_KEYWORDS):
                print(f"Skipping irrelevant chunk: {chunk_id}")
                continue

            print(f"Processing chunk {chunk_counter}: {chunk_id}")

            result = extract_knowledge(chunk)
            if result is None:
                print(f"Failed to extract from {chunk_id}. Skipping.")
                continue

            try:
                result_json = json.loads(result)
                # Attach chunk_id for resume
                result_json["chunk_id"] = chunk_id
                knowledge_graph.append(result_json)
                processed_keys.add(chunk_id)
                total_chunks_processed += 1

                # Save after each successful chunk
                save_checkpoint(knowledge_graph)
                print(f"Saved checkpoint. Total entries: {len(knowledge_graph)}")

            except json.JSONDecodeError as e:
                print(f"JSON invalid from {chunk_id}: {e}\nRaw: {result}")

    return knowledge_graph

# =====================================================================
# 8. Aggregate entities and relations
# =====================================================================

def aggregate_knowledge_graph(knowledge_graph):
    all_entities = {}
    all_relations = []
    for item in knowledge_graph:
        for entity in item.get("entities", []):
            name = entity.get("name")
            if name:
                all_entities[name] = entity
        all_relations.extend(item.get("relations", []))
    return {
        "entities": list(all_entities.values()),
        "relations": all_relations
    }

# =====================================================================
# 9. MAIN EXECUTION
# =====================================================================

if __name__ == "__main__":
    # Load documents
    pdf_dir = Path("knowledge_base/papers")  # adjust as needed
    print(f"Scanning PDFs in: {pdf_dir}")
    documents = parse_directory(pdf_dir)
    print(f"Found {len(documents)} documents.")

    # Estimate total chunks
    total_chunks, relevant_chunks = estimate_chunks(documents)
    print(f"Total chunks: {total_chunks}")
    print(f"Relevant chunks (will be processed): {relevant_chunks}")

    # Process with checkpoint/resume
    knowledge_graph = process_documents(documents, max_chunks=MAX_CHUNKS_TO_PROCESS)

    # Aggregate final graph
    final_graph = aggregate_knowledge_graph(knowledge_graph)

    # Save final output
    with open("knowledge_graph.json", "w", encoding="utf-8") as f:
        json.dump(final_graph, f, indent=2, ensure_ascii=False)

    print(f"Done. Entities: {len(final_graph['entities'])}, Relations: {len(final_graph['relations'])}")
    print(f"Total processed chunks: {len(knowledge_graph)}")