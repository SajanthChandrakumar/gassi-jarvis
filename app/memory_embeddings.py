"""Local ONNX embeddings compatible with Chroma's all-MiniLM-L6-v2 default."""

import fcntl
import hashlib
import importlib
import json
import os
import shutil
import ssl
import stat
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

MODEL_NAME = "all-MiniLM-L6-v2"
MODEL_URL = "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
ARCHIVE_SHA256 = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"
MODEL_ID = f"{MODEL_NAME}:{ARCHIVE_SHA256}"
MAX_TOKENS = 256
DIMENSIONS = 384
MAX_ARCHIVE_BYTES = 150 * 1024 * 1024
MAX_EXPANDED_BYTES = 250 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1000
_TIMEOUT_SECONDS = 30
_CHUNK_SIZE = 1024 * 1024
_REQUIRED_FILES = ("onnx/model.onnx", "onnx/tokenizer.json")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The model endpoint is fixed; never forward requests to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MiniLMEncoder:
    """Lazy local encoder; documents are tokenized and embedded on this machine."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self._model_dir: Path | None = None
        self._session = None
        self._tokenizer = None

    def __call__(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
            raise TypeError("texts must be a list of strings")
        if not texts:
            return []
        self._load_runtime()

        import numpy as np

        vectors = []
        for start in range(0, len(texts), 32):
            batch = texts[start : start + 32]
            encoded = [self._tokenizer.encode(text) for text in batch]
            if any(len(item.ids) != MAX_TOKENS or len(item.attention_mask) != MAX_TOKENS for item in encoded):
                raise ValueError("tokenizer must return padded 256-token inputs")

            input_ids = np.asarray([item.ids for item in encoded], dtype=np.int64)
            attention_mask = np.asarray([item.attention_mask for item in encoded], dtype=np.int64)
            feeds = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": np.zeros_like(input_ids),
            }
            output = self._session.run(None, feeds)
            if not output:
                raise ValueError("ONNX model returned no output")
            hidden = np.asarray(output[0], dtype=np.float32)
            expected = (len(batch), MAX_TOKENS, DIMENSIONS)
            if hidden.shape != expected:
                raise ValueError(f"ONNX output has shape {hidden.shape}; expected {expected} with 384 dimensions")
            if not np.isfinite(hidden).all():
                raise ValueError("ONNX output must contain only finite values")

            mask = attention_mask[:, :, None]
            pooled = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-9)
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            norms[norms == 0] = 1e-12
            normalized = pooled / norms
            if not np.isfinite(normalized).all():
                raise ValueError("embedding output must contain only finite values")
            vectors.extend(normalized.astype(np.float32).tolist())
        return vectors

    def _load_runtime(self) -> None:
        if self._session is not None and self._tokenizer is not None:
            return
        model_dir = self._ensure_model()
        try:
            ort = importlib.import_module("onnxruntime")
            tokenizer_type = importlib.import_module("tokenizers").Tokenizer
        except ImportError as exc:
            raise RuntimeError("memory embeddings require onnxruntime and tokenizers") from exc

        tokenizer = tokenizer_type.from_file(str(model_dir / "onnx/tokenizer.json"))
        tokenizer.enable_truncation(max_length=MAX_TOKENS)
        tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=MAX_TOKENS)
        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = [p for p in ort.get_available_providers() if p != "CoreMLExecutionProvider"]
        session = ort.InferenceSession(
            str(model_dir / "onnx/model.onnx"), providers=providers, sess_options=options
        )
        self._tokenizer, self._session = tokenizer, session

    def _ensure_model(self) -> Path:
        if self._model_dir is not None:
            return self._model_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        model_dir = self.cache_dir / MODEL_NAME
        if self._valid_model(model_dir):
            self._model_dir = model_dir
            return model_dir

        lock_path = self.cache_dir / f".{MODEL_NAME}.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if self._valid_model(model_dir):
                    self._model_dir = model_dir
                    return model_dir

                stage = Path(tempfile.mkdtemp(prefix=f".{MODEL_NAME}.install-", dir=self.cache_dir))
                try:
                    archive_path = stage / "model.tar.gz"
                    self._download_archive(archive_path)
                    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
                        raise ValueError("model archive exceeds the 150 MiB download limit")
                    if _sha256_file(archive_path) != ARCHIVE_SHA256:
                        raise ValueError("model archive SHA-256 does not match the pinned digest")

                    install_dir = stage / "installed"
                    install_dir.mkdir()
                    self._extract_archive(archive_path, install_dir)
                    files = {name: _sha256_file(install_dir / name) for name in _REQUIRED_FILES}
                    (install_dir / "manifest.json").write_text(
                        json.dumps({"archive_sha256": ARCHIVE_SHA256, "files": files}, sort_keys=True),
                        encoding="utf-8",
                    )
                    self._remove_model_dir(model_dir)
                    os.replace(install_dir, model_dir)
                    self._model_dir = model_dir
                    return model_dir
                finally:
                    shutil.rmtree(stage, ignore_errors=True)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def _remove_model_dir(path: Path) -> None:
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)

    @staticmethod
    def _valid_model(model_dir: Path) -> bool:
        try:
            if model_dir.is_symlink() or not model_dir.is_dir():
                return False
            manifest_path = model_dir / "manifest.json"
            if manifest_path.is_symlink() or not manifest_path.is_file():
                return False
            onnx_dir = model_dir / "onnx"
            if onnx_dir.is_symlink() or not onnx_dir.is_dir():
                return False
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("archive_sha256") != ARCHIVE_SHA256:
                return False
            files = manifest.get("files")
            if not isinstance(files, dict) or set(files) != set(_REQUIRED_FILES):
                return False
            for name in _REQUIRED_FILES:
                path = model_dir / name
                if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
                    return False
                if _sha256_file(path) != files[name]:
                    return False
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

    def _download_archive(self, destination: Path) -> None:
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "Gassi-Jarvis"})
        opener = urllib.request.build_opener(
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
            if response.geturl() != MODEL_URL:
                raise ValueError("model download endpoint changed unexpectedly")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_ARCHIVE_BYTES:
                raise ValueError("model archive exceeds the 150 MiB download limit")
            total = 0
            with destination.open("xb") as output:
                while chunk := response.read(_CHUNK_SIZE):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ValueError("model archive exceeds the 150 MiB download limit")
                    output.write(chunk)

    @staticmethod
    def _extract_archive(archive_path: Path, install_dir: Path) -> None:
        if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("model archive exceeds the 150 MiB download limit")
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                total_size = 0
                targets = {}
                for index, member in enumerate(archive):
                    if index >= MAX_ARCHIVE_MEMBERS:
                        raise ValueError("model archive contains too many entries")
                    name = member.name
                    path = PurePosixPath(name)
                    if not name or "\\" in name or path.is_absolute() or ".." in path.parts:
                        raise ValueError("model archive contains an unsafe path")
                    if not member.isdir() and not member.isfile():
                        raise ValueError("model archive contains a link or special file")
                    total_size += member.size
                    if total_size > MAX_EXPANDED_BYTES:
                        raise ValueError("model archive exceeds the 250 MiB expanded limit")
                    if name in _REQUIRED_FILES:
                        if not member.isfile() or name in targets:
                            raise ValueError("model archive has an invalid or duplicate required file")
                        targets[name] = member
                if set(targets) != set(_REQUIRED_FILES):
                    raise ValueError("model archive is missing model.onnx or tokenizer.json")

                onnx_dir = install_dir / "onnx"
                onnx_dir.mkdir()
                for name in _REQUIRED_FILES:
                    member = targets[name]
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError(f"model archive cannot read {name}")
                    destination = install_dir / name
                    remaining = member.size
                    with source, destination.open("xb") as output:
                        while remaining:
                            chunk = source.read(min(_CHUNK_SIZE, remaining))
                            if not chunk:
                                raise ValueError(f"model archive ended early while reading {name}")
                            output.write(chunk)
                            remaining -= len(chunk)
        except (tarfile.TarError, OSError, EOFError) as exc:
            raise ValueError("model archive is invalid") from exc
