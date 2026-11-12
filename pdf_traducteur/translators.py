"""Moteur de traduction (Google Traduction, point d'accès public gratuit) + cache disque."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

ProgressFn = Callable[[int, int], None]


class Translator(ABC):
    name = "base"

    def __init__(self, target: str = "fr"):
        self.target = target

    def cache_id(self) -> str:
        return self.name

    @abstractmethod
    def translate_many(self, texts: list[str], progress: ProgressFn | None = None) -> list[str | None]: ...


class CachedTranslator(Translator):
    """Enveloppe un moteur avec un cache JSON (reprise sans re-traduire)."""

    def __init__(self, inner: Translator, cache_file: Path):
        super().__init__(inner.target)
        self.inner = inner
        self.name = inner.name
        self.cache_file = Path(cache_file)
        self.cache: dict[str, str] = {}
        if self.cache_file.exists():
            try:
                self.cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}

    def _key(self, text: str) -> str:
        return hashlib.sha1(f"{self.inner.cache_id()}|{self.target}|{text}".encode()).hexdigest()

    def save(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(self.cache_file)

    def translate_many(self, texts, progress=None):
        results: list[str | None] = [self.cache.get(self._key(t)) for t in texts]
        todo = [i for i, r in enumerate(results) if r is None]
        if todo:
            done_count = len(texts) - len(todo)
            chunk = 40  # sauvegarde régulière du cache
            for c0 in range(0, len(todo), chunk):
                idx = todo[c0 : c0 + chunk]
                out = self.inner.translate_many(
                    [texts[i] for i in idx], lambda k, n, c0=c0: progress and progress(done_count + c0 + k, len(texts))
                )
                for i, r in zip(idx, out):
                    results[i] = r
                    if r is not None:
                        self.cache[self._key(texts[i])] = r
                self.save()
        elif progress:
            progress(len(texts), len(texts))
        return results


class GoogleFreeTranslator(Translator):
    """Point d'accès public de Google Traduction : gratuit, sans clé ni compte.
    Les segments sont envoyés par lots (séparateur ⁂) pour limiter les requêtes."""

    name = "google"
    URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={tl}&dt=t"
    SEP = "\n⁂\n"
    MAX_CHARS = 3800

    def __init__(self, target="fr", pause: float = 0.4, retries: int = 5):
        super().__init__(target)
        self.pause = pause
        self.retries = retries

    def _call(self, text: str) -> str:
        url = self.URL.format(tl=self.target)
        data = urllib.parse.urlencode({"q": text}).encode()
        headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}
        delay = 2.0
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as r:
                    j = json.loads(r.read().decode("utf-8"))
                time.sleep(self.pause)
                return "".join(seg[0] for seg in j[0] if seg and seg[0])
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                if attempt == self.retries - 1:
                    raise RuntimeError(f"Google Traduction indisponible : {e}") from e
                time.sleep(delay)  # limitation de débit (429) ou coupure réseau
                delay *= 2
        raise RuntimeError("unreachable")

    def translate_many(self, texts, progress=None):
        results: list[str | None] = [None] * len(texts)
        batch: list[int] = []
        size = 0
        done = 0

        def flush():
            nonlocal batch, size, done
            if not batch:
                return
            try:
                out = self._call(self.SEP.join(texts[i] for i in batch))
                parts = [p.strip() for p in re.split(r"\s*⁂\s*", out)]
            except RuntimeError:
                parts = None
            if parts is None or len(parts) != len(batch):
                parts = []  # découpage perdu : un appel par texte
                for i in batch:
                    try:
                        parts.append(self._call(texts[i]).strip())
                    except RuntimeError:
                        parts.append(None)
            for i, p in zip(batch, parts):
                results[i] = p
            done += len(batch)
            if progress:
                progress(done, len(texts))
            batch, size = [], 0

        for i, t in enumerate(texts):
            if size + len(t) > self.MAX_CHARS:
                flush()
            batch.append(i)
            size += len(t) + len(self.SEP)
        flush()
        return results


def make_translator(target: str = "fr", cache_dir: Path | None = None, pause: float = 0.4) -> Translator:
    engine = GoogleFreeTranslator(target, pause=pause)
    if cache_dir is None:
        return engine
    return CachedTranslator(engine, Path(cache_dir) / f"cache_{engine.cache_id()}.json")
