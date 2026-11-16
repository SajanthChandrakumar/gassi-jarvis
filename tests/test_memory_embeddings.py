"""Offline tests for Jarvis's local MiniLM embedding function."""

import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app import memory_embeddings as embeddings


class _Encoded:
    def __init__(self, ids):
        self.ids = ids
        self.attention_mask = [int(token != 0) for token in ids]


class _Tokenizer:
    def __init__(self):
        self.truncation = None
        self.padding = None

    @classmethod
    def from_file(cls, path):
        assert Path(path).is_file()
        return cls()

    def enable_truncation(self, **kwargs):
        self.truncation = kwargs

    def enable_padding(self, **kwargs):
        self.padding = kwargs

    def encode(self, text):
        ids = [1, 2, 3] if text else []
        ids = ids[: self.truncation["max_length"]]
        if self.padding:
            ids += [0] * (self.padding["length"] - len(ids))
        return _Encoded(ids)


class _Session:
    def __init__(self, output=None):
        self.feeds = None
        self.output = output

    def run(self, _outputs, feeds):
        self.feeds = feeds
        if self.output is not None:
            return [self.output]
        batch = feeds["input_ids"].shape[0]
        hidden = np.ones((batch, 256, 384), dtype=np.float32)
        return [hidden]


def _archive(files: dict[str, bytes]) -> bytes:
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as archive:
        for name, contents in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(contents)
            archive.addfile(info, io.BytesIO(contents))
    return result.getvalue()


def _installable_archive() -> bytes:
    return _archive({
        "onnx/model.onnx": b"fake onnx bytes",
        "onnx/tokenizer.json": b"fake tokenizer bytes",
    })


def _fake_runtime(monkeypatch, encoder, output=None):
    session = _Session(output)
    model_dir = encoder.cache_dir / embeddings.MODEL_NAME
    (model_dir / "onnx").mkdir(parents=True)
    (model_dir / "onnx/tokenizer.json").write_text("{}", encoding="utf-8")
    (model_dir / "onnx/model.onnx").write_bytes(b"fake")
    tokenizer_type = _Tokenizer
    ort = SimpleNamespace(
        SessionOptions=lambda: SimpleNamespace(log_severity_level=0),
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL=1),
        get_available_providers=lambda: ["CPUExecutionProvider"],
        InferenceSession=lambda path, **kwargs: session,
    )
    monkeypatch.setattr(encoder, "_ensure_model", lambda: encoder.cache_dir / embeddings.MODEL_NAME)
    monkeypatch.setattr(
        embeddings.importlib,
        "import_module",
        lambda name: ort if name == "onnxruntime" else SimpleNamespace(Tokenizer=tokenizer_type),
    )
    return session


def test_encoder_is_lazy_and_empty_input_does_not_initialize_model(tmp_path, monkeypatch):
    encoder = embeddings.MiniLMEncoder(tmp_path)
    monkeypatch.setattr(encoder, "_ensure_model", lambda: pytest.fail("model should stay lazy"))
    assert encoder([]) == []
    assert encoder._session is None
    assert list(tmp_path.iterdir()) == []


def test_embeddings_match_chroma_minilm_shape_masking_and_normalization(tmp_path, monkeypatch):
    encoder = embeddings.MiniLMEncoder(tmp_path)
    session = _fake_runtime(monkeypatch, encoder)

    vectors = encoder(["a remembered phrase", ""])

    assert len(vectors) == 2
    assert all(len(vector) == 384 for vector in vectors)
    assert np.linalg.norm(vectors[0]) == pytest.approx(1.0)
    assert vectors[1] == [0.0] * 384
    assert session.feeds["input_ids"].shape == (2, 256)
    assert session.feeds["attention_mask"].shape == (2, 256)
    assert session.feeds["token_type_ids"].shape == (2, 256)
    assert session.feeds["attention_mask"][0, :3].tolist() == [1, 1, 1]
    assert session.feeds["attention_mask"][0, 3:].sum() == 0
    assert session.feeds["token_type_ids"].sum() == 0
    assert encoder._tokenizer.truncation == {"max_length": 256}
    assert encoder._tokenizer.padding == {"pad_id": 0, "pad_token": "[PAD]", "length": 256}


def test_rejects_wrong_model_output_shape(tmp_path, monkeypatch):
    encoder = embeddings.MiniLMEncoder(tmp_path)
    _fake_runtime(monkeypatch, encoder, output=np.ones((1, 256, 383), dtype=np.float32))
    with pytest.raises(ValueError, match="expected.*384"):
        encoder(["phrase"])


def test_rejects_non_finite_model_output(tmp_path, monkeypatch):
    encoder = embeddings.MiniLMEncoder(tmp_path)
    output = np.ones((1, 256, 384), dtype=np.float32)
    output[0, 0, 0] = np.nan
    _fake_runtime(monkeypatch, encoder, output=output)
    with pytest.raises(ValueError, match="finite"):
        encoder(["phrase"])


def test_verified_archive_installs_only_required_files_and_reuses_cache(tmp_path, monkeypatch):
    payload = _installable_archive()
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(embeddings, "ARCHIVE_SHA256", digest)
    encoder = embeddings.MiniLMEncoder(tmp_path)
    downloads = []

    def download(destination):
        downloads.append(destination)
        destination.write_bytes(payload)

    monkeypatch.setattr(encoder, "_download_archive", download)
    installed = encoder._ensure_model()

    assert (installed / "onnx/model.onnx").read_bytes() == b"fake onnx bytes"
    assert (installed / "onnx/tokenizer.json").read_bytes() == b"fake tokenizer bytes"
    assert json.loads((installed / "manifest.json").read_text()) == {
        "archive_sha256": digest,
        "files": {
            "onnx/model.onnx": hashlib.sha256(b"fake onnx bytes").hexdigest(),
            "onnx/tokenizer.json": hashlib.sha256(b"fake tokenizer bytes").hexdigest(),
        },
    }
    second = embeddings.MiniLMEncoder(tmp_path)
    monkeypatch.setattr(second, "_download_archive", download)
    assert second._ensure_model() == installed
    assert len(downloads) == 1

    (installed / "onnx/tokenizer.json").write_bytes(b"corrupted")
    third = embeddings.MiniLMEncoder(tmp_path)
    monkeypatch.setattr(third, "_download_archive", download)
    assert third._ensure_model() == installed
    assert len(downloads) == 2
    assert (installed / "onnx/tokenizer.json").read_bytes() == b"fake tokenizer bytes"


def test_bad_archive_checksum_is_rejected_before_extraction(tmp_path, monkeypatch):
    payload = _installable_archive()
    monkeypatch.setattr(embeddings, "ARCHIVE_SHA256", "0" * 64)
    encoder = embeddings.MiniLMEncoder(tmp_path)
    monkeypatch.setattr(encoder, "_download_archive", lambda destination: destination.write_bytes(payload))
    monkeypatch.setattr(encoder, "_extract_archive", lambda *_: pytest.fail("must verify before extract"))

    with pytest.raises(ValueError, match="SHA-256"):
        encoder._ensure_model()


def test_extractor_rejects_traversal_and_symlink_entries(tmp_path):
    traversal = _archive({"onnx/../../outside": b"no"})
    link_buffer = io.BytesIO()
    with tarfile.open(fileobj=link_buffer, mode="w:gz") as archive:
        link = tarfile.TarInfo("onnx/model.onnx")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    for payload in (traversal, link_buffer.getvalue()):
        archive_path = tmp_path / "bad.tar.gz"
        archive_path.write_bytes(payload)
        with pytest.raises(ValueError):
            embeddings.MiniLMEncoder._extract_archive(archive_path, tmp_path / "out")
    assert not (tmp_path / "outside").exists()


def test_extractor_enforces_expanded_size_limit(tmp_path, monkeypatch):
    payload = _archive({
        "onnx/model.onnx": b"model is too large",
        "onnx/tokenizer.json": b"ok",
    })
    archive_path = tmp_path / "large.tar.gz"
    archive_path.write_bytes(payload)
    monkeypatch.setattr(embeddings, "MAX_EXPANDED_BYTES", 8)

    with pytest.raises(ValueError, match="250 MiB expanded limit"):
        embeddings.MiniLMEncoder._extract_archive(archive_path, tmp_path / "out")
    assert not (tmp_path / "out/onnx/model.onnx").exists()


def test_download_rejects_oversized_response_before_writing(tmp_path, monkeypatch):
    class Response:
        headers = {"Content-Length": str(embeddings.MAX_ARCHIVE_BYTES + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return embeddings.MODEL_URL

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == embeddings.MODEL_URL
            assert timeout == 30
            return Response()

    monkeypatch.setattr(embeddings.urllib.request, "build_opener", lambda *_: Opener())
    destination = tmp_path / "archive.tar.gz"
    with pytest.raises(ValueError, match="150 MiB download limit"):
        embeddings.MiniLMEncoder(tmp_path)._download_archive(destination)
    assert not destination.exists()


def test_redirect_handler_does_not_follow_model_download_redirects():
    handler = embeddings._NoRedirect()
    request = embeddings.urllib.request.Request(embeddings.MODEL_URL)
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://elsewhere.invalid/model") is None
