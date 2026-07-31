from __future__ import annotations

import hashlib
import re


def normalize_question_stem(stem: str) -> str:
    text = stem.strip().lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？；：、,.!?;:'\"“”‘’（）()\[\]{}]", "", text)
    return text


def question_hash(stem: str) -> str:
    return hashlib.sha256(normalize_question_stem(stem).encode("utf-8")).hexdigest()

