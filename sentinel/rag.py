try:
    __import__('pysqlite3')
    import sys
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass

import os
import math
import hashlib
import chromadb
import requests
import time
import threading
import collections
from . import config
from . import utils


class HailoEmbedder:
    """
    Hailo NPU embedding inference.
    Inicializuje se líně — při jakémkoliv selhání zůstane _ready=False
    a RAGEngine transparentně přepne na Ollama fallback.
    """

    def __init__(self, hef_path: str, device_name: str):
        self._hef_path = hef_path
        self._device_name = device_name
        self._ready = False
        self._lock = threading.Lock()
        self._target = None
        self._network_group = None
        self._input_name = None
        self._output_name = None
        self._seq_len = 128
        self._tokenizer = None
        self._init()

    def _init(self):
        if not os.path.exists('/dev/hailo0'):
            utils.log_message("Hailo Embedder: /dev/hailo0 nenalezeno — driver nenačten nebo nutný reboot.")
            return
        if not os.path.exists(self._hef_path):
            utils.log_message(f"Hailo Embedder: HEF model nenalezen: {self._hef_path}")
            return

        try:
            from hailo_platform import (HEF, VDevice, HailoStreamInterface,  # noqa: F401
                                         ConfigureParams)
        except ImportError:
            utils.log_message("Hailo Embedder: hailo_platform není nainstalován (součást hailo-all).")
            return

        try:
            from transformers import AutoTokenizer  # noqa: F401
        except ImportError:
            utils.log_message("Hailo Embedder: transformers není nainstalován — pip install transformers")
            return

        try:
            from hailo_platform import HEF, VDevice, HailoStreamInterface, ConfigureParams
            from transformers import AutoTokenizer

            hef = HEF(self._hef_path)

            # Detekce vstupní délky sekvence z HEF metadat
            input_info = hef.get_input_vstream_infos()
            output_info = hef.get_output_vstream_infos()
            self._input_name = input_info[0].name
            self._output_name = output_info[0].name
            shape = input_info[0].shape
            self._seq_len = int(shape[-1]) if shape else 128

            # Tokenizer — výchozí all-MiniLM-L6-v2 (384-dim), lze změnit dle HEF
            self._tokenizer = AutoTokenizer.from_pretrained(
                'sentence-transformers/all-MiniLM-L6-v2',
                local_files_only=False
            )

            # VDevice zůstane otevřený po celou dobu životnosti embeddera
            self._target = VDevice()
            configure_params = ConfigureParams.create_from_hef(hef, interface=HailoStreamInterface.PCIe)
            network_groups = self._target.configure(hef, configure_params)
            self._network_group = network_groups[0]

            self._ready = True
            utils.log_message(
                f"Hailo Embedder připraven: {self._device_name} | "
                f"HEF: {os.path.basename(self._hef_path)} | seq_len={self._seq_len}"
            )
        except Exception as e:
            utils.log_message(f"Hailo Embedder init selhal: {e}")
            self._cleanup()

    def embed(self, text: str):
        """Vrátí embedding vector nebo None při jakémkoliv selhání."""
        if not self._ready:
            return None
        try:
            import numpy as np
            from hailo_platform import (InputVStreamParams, OutputVStreamParams,  # noqa: F401
                                         InferVStreams)

            encoded = self._tokenizer(
                text,
                padding='max_length',
                truncation=True,
                max_length=self._seq_len,
                return_tensors='np'
            )
            input_ids = encoded['input_ids'].astype(np.float32)

            input_params = InputVStreamParams.make_from_network_group(
                self._network_group, quantized=False
            )
            output_params = OutputVStreamParams.make_from_network_group(
                self._network_group, quantized=False
            )

            with self._lock:
                with self._network_group.activate():
                    with InferVStreams(self._network_group, input_params, output_params) as pipeline:
                        result = pipeline.infer({self._input_name: input_ids})
                        return result[self._output_name][0].tolist()

        except Exception as e:
            utils.log_message(f"Hailo Embedder inference error: {e} — fallback na Ollama.")
            return None

    def _cleanup(self):
        try:
            if self._target:
                self._target.release()
        except Exception:
            pass
        self._ready = False

    def close(self):
        self._cleanup()

class RAGEngine:
    def __init__(self):
        self.collection_name = "sentinel_kb"
        self.is_ready = False
        self.db_lock = threading.Lock()

        db_path = getattr(config, "CHROMADB_PATH", "")
        if db_path and not os.path.exists(db_path):
            os.makedirs(db_path, exist_ok=True)

        utils.log_message(f"RAG: Initializing Vector DB at {db_path}")
        self.client = None
        self.collection = None
        self.kb_chunks = []
        self._idf = {}
        self.kb_file = getattr(config, "KB_FILE_PATH", "")
        self.last_load_time = 0
        self.stats = {
            "model_name": "nomic-embed-text",
            "total_embeddings": 0,
            "last_latency": 0.0,
            "latencies": collections.deque(maxlen=50)
        }

        # AI HAT+ / Hailo NPU embedder (inicializuje se pouze pokud je v configu povolen)
        self._hailo: HailoEmbedder | None = None
        if getattr(config, 'AI_HAT_ENABLED', False) and getattr(config, 'AI_HAT_USE_EMBEDDINGS', False):
            hef = getattr(config, 'AI_HAT_HEF_PATH', '')
            dev = getattr(config, 'AI_HAT_DEVICE', 'hailo8l')
            if hef:
                self._hailo = HailoEmbedder(hef, dev)
                if self._hailo._ready:
                    self.stats["model_name"] = f"{dev} (Hailo HEF)"
            else:
                utils.log_message("RAG: AI HAT+ embedding povolen, ale hef_model_path není nastaven — Ollama fallback.")

        self._load_text_chunks()
        
        try:
            if db_path:
                self.client = chromadb.PersistentClient(path=db_path)
                self.collection = self.client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"} 
                )
        except Exception as e:
            utils.log_message(f"RAG Critical Init Error: {e}")
            self.client = None

    def initialize_background(self):
        t = threading.Thread(target=self._ingest_worker, daemon=True, name="RAG-Indexer")
        t.start()

    def _ingest_worker(self):
        try:
            self.ingest_knowledge_base()
        except Exception as e:
            utils.log_message(f"RAG Background Worker Error: {e}")

    def get_status(self):
        status_suffix = " (Ready)" if self.is_ready else " (Indexing...)"
        backend = ""
        if self._hailo and self._hailo._ready:
            backend = f" | NPU: {getattr(config, 'AI_HAT_DEVICE', 'hailo')} ({getattr(config, 'AI_HAT_TOPS', 0)}T)"
        count = 0
        if self.client and self.collection:
            try:
                count = self.collection.count()
            except: pass
            return f"Vector DB ({count} items){status_suffix}{backend}"
        return f"Text Search Only ({len(self.kb_chunks)} chunks){backend}"

    def _load_text_chunks(self):
        if not self.kb_file or not os.path.exists(self.kb_file): return
        try:
            with open(self.kb_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            raw = content.split("<<<SENTINEL_ENTRY>>>")
            self.kb_chunks = [c.strip() for c in raw if c.strip()]
            self._build_idf_index()
        except: pass

    def _build_idf_index(self):
        N = len(self.kb_chunks)
        if N == 0:
            self._idf = {}
            return
        df = collections.Counter()
        for chunk in self.kb_chunks:
            df.update(set(chunk.lower().split()))
        self._idf = {term: math.log((N + 1) / (count + 1)) for term, count in df.items()}

    def _get_embedding(self, text):
        if not text or not text.strip(): return None
        if not self.client: return None

        # AI HAT+ / Hailo NPU cesta — pokud je ready, zkusíme ji první
        if self._hailo is not None and self._hailo._ready:
            start_ts = time.time()
            result = self._hailo.embed(text)
            if result is not None:
                latency = time.time() - start_ts
                self.stats["total_embeddings"] += 1
                self.stats["last_latency"] = latency
                self.stats["latencies"].append(latency)
                return result
            # Hailo selhal → transparentní fallback na Ollama

        return self._get_embedding_ollama(text)

    def _get_embedding_ollama(self, text):
        """Ollama embedding přes CPU ollama (nomic-embed-text).
        Když je HAILO_OLLAMA_ENABLED, hailo-ollama embeddingy nepodporuje —
        EMBEDDING_OLLAMA_URL nebo OLLAMA_URL musí ukazovat na CPU ollama (port 11434).
        """
        start_ts = time.time()
        try:
            emb_base = getattr(config, 'EMBEDDING_OLLAMA_URL', '') or ''
            if emb_base:
                base_url = emb_base.rstrip('/')
            else:
                base_url = config.OLLAMA_URL.replace('/v1/chat/completions', '').replace('/api/generate', '')
            # OpenAI-compatible servers use /v1/embeddings, native Ollama uses /api/embeddings
            if '/v1' in config.OLLAMA_URL or (emb_base and '/v1' in emb_base):
                url = f"{base_url}/v1/embeddings"
                payload = {"model": "nomic-embed-text", "input": text}
            else:
                url = f"{base_url}/api/embeddings"
                payload = {"model": "nomic-embed-text", "prompt": text}
            headers = {"Authorization": f"Bearer {config.OLLAMA_API_KEY}"} if config.OLLAMA_API_KEY else {}

            resp = requests.post(url, json=payload, headers=headers, timeout=60)

            if resp.status_code == 404:
                utils.log_message("RAG Error: Model 'nomic-embed-text' not found. Disabling Vector DB.")
                self.client = None
                return None

            resp.raise_for_status()
            latency = time.time() - start_ts
            self.stats["total_embeddings"] += 1
            self.stats["last_latency"] = latency
            self.stats["latencies"].append(latency)
            data = resp.json()
            # OpenAI format: {"data": [{"embedding": [...]}]}
            # Ollama format: {"embedding": [...]}
            if "data" in data and data["data"]:
                return data["data"][0].get("embedding")
            return data.get("embedding")

        except Exception as e:
            utils.log_message(f"RAG Embedding Error: {e}")
            return None

    def ingest_knowledge_base(self):
        if not self.client or not self.kb_file:
            utils.log_message("RAG: Text Search Only mode active.")
            self.is_ready = True
            return

        try:
            current_mtime = os.path.getmtime(self.kb_file)
        except FileNotFoundError:
            utils.log_message("RAG: KB file not found. Text Search Only mode active.")
            self.is_ready = True
            return

        if current_mtime == self.last_load_time:
            try:
                if self.collection.count() > 0:
                    self.is_ready = True
                    return
            except Exception as e:
                utils.log_message(f"RAG collection count error: {e}")

        utils.log_message("Starting RAG: Indexing Knowledge Base...")
        self.is_ready = False
        self._load_text_chunks()
        
        if not self.kb_chunks: 
            self.is_ready = True
            return

        try:
            ids, documents, embeddings, metadatas = [], [], [], []
            
            for i, chunk in enumerate(self.kb_chunks):
                if not self.client: break 
                emb = self._get_embedding(chunk)
                if emb:
                    chunk_id = hashlib.md5(chunk.encode()).hexdigest()
                    ids.append(chunk_id)
                    documents.append(chunk)
                    embeddings.append(emb)
                    metadatas.append({"source": "kb_file", "index": i})
                else:
                    if not self.client: break

            if ids and self.client:
                with self.db_lock:
                    utils.log_message("RAG: Acquiring DB lock for write...")
                    try:
                        self.client.delete_collection(self.collection_name)
                        self.collection = self.client.get_or_create_collection(name=self.collection_name, metadata={"hnsw:space": "cosine"})
                        self.collection.add(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
                        utils.log_message(f"RAG: Successfully indexed {len(ids)} chunks.")
                    except Exception as db_e:
                         utils.log_message(f"RAG DB Write Error: {db_e}")
                         raise db_e
            else:
                utils.log_message("RAG: Using Text Search Only (No embeddings generated).")
            
            self.last_load_time = current_mtime
            self.is_ready = True
            
        except Exception as e:
            utils.log_message(f"RAG Ingest Error: {e}")
            self.is_ready = True

    def _text_fallback(self, query, limit=3):
        if not self.kb_chunks: return "KB Empty."
        q_lower = query.lower()
        q_terms = q_lower.split()
        if not q_terms: return "No text match found."

        idf = self._idf
        scored = []

        for chunk in self.kb_chunks:
            c_lower = chunk.lower()
            c_words = c_lower.split()
            c_len = max(len(c_words), 1)

            score = 0.0
            for term in q_terms:
                tf = c_lower.count(term) / c_len
                score += tf * idf.get(term, 1.0)

            if score <= 0:
                continue

            # Phrase match bonus
            if len(q_terms) > 1 and q_lower in c_lower:
                score *= 3.0

            # Header line bonus — match on ##, FILE:, CONTEXT: lines
            for line in chunk.splitlines():
                ls = line.strip().lower()
                if ls.startswith(('#', 'file:', 'context:')):
                    if any(t in ls for t in q_terms):
                        score *= 2.0
                        break

            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [x[1] for x in scored[:limit]]

        if results: return "\n\n".join(results)
        return "No text match found."
    
    def get_metrics(self):
        avg_lat = 0
        if self.stats["latencies"]:
            avg_lat = sum(self.stats["latencies"]) / len(self.stats["latencies"])
        
        return {
            "rag_model": self.stats["model_name"],
            "rag_total_vectors": self.stats["total_embeddings"],
            "rag_last_time": f"{self.stats['last_latency']:.3f}s",
            "rag_avg_time": f"{avg_lat:.3f}s",
            "rag_db_items": self.collection.count() if (self.client and self.collection) else 0,
            "rag_chunks_loaded": len(self.kb_chunks)
        }

    def search(self, query, n_results=3):
        if not self.is_ready:
            return self._text_fallback(query, n_results)

        if self.client and self.collection:
            try:
                emb = self._get_embedding(query)
                
                if emb:
                    with self.db_lock:
                        res = self.collection.query(query_embeddings=[emb], n_results=n_results)
                        if res and res['documents'] and res['documents'][0]:
                            return "\n\n".join(res['documents'][0])
            except Exception as e:
                utils.log_message(f"RAG Vector Search failed: {e}")
        
        return self._text_fallback(query, n_results)

rag_system = RAGEngine()
