"""Ollama, the local model server (http://127.0.0.1:11434), over its HTTP API with the standard library. Hull runs
Gemma through it: Ollama loads the model onto the GPU, falls back to the processor, and unloads it when idle."""
import base64, json, urllib.request

import numpy as np


class Ollama:
    def __init__(self, address="http://127.0.0.1:11434", timeout=60):
        self.address, self.timeout = address.rstrip("/"), timeout

    def _post(self, path, body, timeout=None):
        req = urllib.request.Request(self.address + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
            return json.loads(r.read())

    def json(self, model, prompt, schema, images=(), system="", timeout=None):
        """a reply in the shape of a JSON schema (Ollama constrains the output to it)"""
        r = self._post("/api/generate", {
            "model": model, "prompt": prompt, "system": system, "format": schema, "stream": False, "think": False,
            "images": [base64.b64encode(i).decode() for i in images],
            # Hull's prompts are short (a sort batch is ~2k tokens): a small context window keeps Gemma quick, where
            # Ollama otherwise gives it the model's full 128k
            "options": {"temperature": 0, "num_ctx": 8192},
            "keep_alive": "30m"}, timeout)
        # Gemma sometimes adds text after the JSON ("Extra data"): read the JSON and leave the rest
        return json.JSONDecoder().raw_decode(r["response"].strip())[0]

    def ping(self):
        """is Ollama answering? (a quick question that loads nothing)"""
        try:
            with urllib.request.urlopen(self.address + "/api/version", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def unload(self, model):
        """take a model out of memory now (frees the graphics card)"""
        self._post("/api/generate", {"model": model, "keep_alive": 0})

    def embed(self, model, texts):
        """unit-length vectors (float32), one row per text"""
        texts = list(texts)
        if not texts:
            return np.zeros((0, 0), np.float32)
        rows = []
        for i in range(0, len(texts), 64):  # Ollama turns down a few hundred at once (400 Bad Request)
            rows += self._post("/api/embed", {"model": model, "input": texts[i:i + 64], "keep_alive": "30m"})["embeddings"]
        v = np.array(rows, np.float32)
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
