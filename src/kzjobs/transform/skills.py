"""Skill extraction from vacancy text using a CSV dictionary (data/reference/skills.csv)."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillEntry:
    name: str
    category: str
    aliases: tuple[str, ...]
    exact_aliases: tuple[str, ...]


def load_dictionary(path: Path) -> list[SkillEntry]:
    entries: list[SkillEntry] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            raw_aliases = [a.strip().lower() for a in row["aliases"].split("|") if a.strip()]
            # an alias starting with '=' matches only the explicit key_skills list, not free text
            exact = tuple(a[1:] for a in raw_aliases if a.startswith("="))
            free = tuple(a for a in raw_aliases if not a.startswith("="))
            entries.append(SkillEntry(row["skill"].strip(), row["category"].strip(), free, exact))
    return entries


class SkillMatcher:
    def __init__(self, entries: list[SkillEntry]) -> None:
        self.entries = entries
        self._patterns: list[tuple[SkillEntry, re.Pattern[str] | None]] = []
        for entry in entries:
            if entry.aliases:
                alternatives = "|".join(
                    re.escape(a) for a in sorted(entry.aliases, key=len, reverse=True)
                )
                pattern = re.compile(rf"(?<![\w+#])(?:{alternatives})(?![\w+#])", re.IGNORECASE)
            else:
                pattern = None
            self._patterns.append((entry, pattern))

    @classmethod
    def from_csv(cls, path: Path) -> SkillMatcher:
        return cls(load_dictionary(path))

    def find(self, text: str, key_skills: list[str] | None = None) -> list[str]:
        explicit = {s.strip().lower() for s in (key_skills or [])}
        haystack = " ".join([text, *explicit]).lower()
        found: list[str] = []
        for entry, pattern in self._patterns:
            hit = bool(pattern and pattern.search(haystack))
            hit = (
                hit
                or entry.name.lower() in explicit
                or any(a in explicit for a in entry.exact_aliases)
            )
            if hit:
                found.append(entry.name)
        return sorted(found)

    def category_of(self, name: str) -> str:
        return next((e.category for e in self.entries if e.name == name), "other")
