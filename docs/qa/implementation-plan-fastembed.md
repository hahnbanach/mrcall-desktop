# Implementation Plan: sentence-transformers to fastembed

## Motivation

Replace `sentence-transformers[onnx]` + explicit `torch` install with `fastembed`.
Same model, same ONNX runtime, same 384-dim output. Dependency footprint drops from ~2GB to ~50MB.
No database migration needed -- embeddings are numerically identical.

## Affected Files (4 code, 1 spec)

### 1. `requirements.txt` (line 38)

```diff
-sentence-transformers[onnx]>=3.0.0
+fastembed>=0.4.0
```

### 2. `Dockerfile` (line 14)

Remove the torch pre-install. The two-command `RUN` becomes one:

```diff
-RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
-    pip install --no-cache-dir -r requirements.txt
+RUN pip install --no-cache-dir -r requirements.txt
```

### 3. `zylch/memory/embeddings.py` (full rewrite of `__init__` and `encode`)

**Constructor** -- replace `SentenceTransformer` with `TextEmbedding`:

```python
from fastembed import TextEmbedding

self.model = TextEmbedding(model_name=config.embedding_model)
```

Model name must change from `all-MiniLM-L6-v2` to the fastembed-qualified form
`sentence-transformers/all-MiniLM-L6-v2` (see file 4 below).

The `device` attribute does not exist on `TextEmbedding`; drop it from the ready-log.

**Dimensionality check** -- `TextEmbedding.embed()` returns a generator:

```python
test_embedding = list(self.model.embed(["test"]))[0]
actual_dim = len(test_embedding)
```

**`encode()` method**:

```python
def encode(self, text: Union[str, List[str]]) -> np.ndarray:
    if isinstance(text, str):
        embedding = list(self.model.embed([text]))[0]
        return np.array(embedding, dtype=np.float32)
    else:
        embeddings = list(self.model.embed(text))
        return np.array(embeddings, dtype=np.float32)
```

Key differences from sentence-transformers:
- `embed()` takes a list, never a bare string.
- `embed()` returns a generator of numpy arrays; must wrap in `list()`.
- No `batch_size`, `convert_to_numpy`, or `show_progress_bar` params.
  fastembed handles batching internally (default 256).
- `batch_size` can be passed: `self.model.embed(text, batch_size=config.batch_size)`
  if we want to keep the config knob.

The `similarity()`, `distance()`, `serialize()`, `deserialize()` methods use only numpy
and remain unchanged.

### 4. `zylch/memory/config.py` (line 29)

Update the default model name to fastembed's format:

```diff
 embedding_model: str = Field(
-    default="all-MiniLM-L6-v2",
-    description="Sentence-transformers model name"
+    default="sentence-transformers/all-MiniLM-L6-v2",
+    description="Fastembed model name"
 )
```

Also remove the `embedding_device` field (line 36-39) -- fastembed does not expose
device selection (it uses ONNX CPU by default, which is what we want).

### 5. `zylch/api/main.py` (line 33)

Update the noisy-logger silencing list:

```diff
-for noisy_logger in ["hpack", "httpcore", "httpx", "h2", "h11", "urllib3", "cachecontrol", "sentence_transformers", "LiteLLM"]:
+for noisy_logger in ["hpack", "httpcore", "httpx", "h2", "h11", "urllib3", "cachecontrol", "fastembed", "LiteLLM"]:
```

### 6. `spec/INGESTION_PIPELINE.md` (lines 230-233)

Update the example code snippet. Low priority -- spec doc only.

## Files NOT affected

- `zylch/services/command_handlers.py` -- imports `EmbeddingEngine` but never touches
  `sentence_transformers` directly. No change needed.
- `zylch/memory/` (all other modules) -- consume `EmbeddingEngine.encode()` which keeps
  the same signature and return type. No change needed.
- Database / Alembic migrations -- embeddings are identical, no migration.

## Env override note

Anyone who has `MEMORY_EMBEDDING_MODEL=all-MiniLM-L6-v2` in their `.env` must update
to `MEMORY_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2`.
Check `.env.standalone`, `.env.mrcall`, and k8s ConfigMaps.

## Verification

1. `pip install fastembed && python -c "from fastembed import TextEmbedding; m = TextEmbedding('sentence-transformers/all-MiniLM-L6-v2'); print(list(m.embed(['hello']))[0].shape)"`
   -- must print `(384,)`.
2. Run existing tests: `python -m pytest tests/ -v` -- all memory tests must pass.
3. Build Docker image, verify size reduction (~2GB smaller).
4. Spot-check: encode a known string with both old and new, confirm cosine similarity > 0.99.

## Execution order

1. Update `requirements.txt` and `Dockerfile`.
2. Update `config.py` (model name + remove `embedding_device`).
3. Rewrite `embeddings.py`.
4. Update `main.py` logger name.
5. Test locally, then Docker build.
6. Update spec doc last.
