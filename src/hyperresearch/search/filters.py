"""Structured field filter builder for search queries."""

from __future__ import annotations

from dataclasses import dataclass

# (attribute, clause template, keep): "truthy" skips empties, "present"
# keeps any non-None value. Order is the SQL order.
_FIELD_CLAUSES = (
    ("status", "{a}.status = ?", "truthy"),
    ("note_type", "{a}.type = ?", "truthy"),
    ("tier", "{a}.tier = ?", "truthy"),
    ("content_type", "{a}.content_type = ?", "truthy"),
    ("after", "{a}.created >= ?", "truthy"),
    ("before", "{a}.created <= ?", "truthy"),
    ("path_glob", "{a}.path GLOB ?", "truthy"),
    ("parent", "{a}.parent = ?", "truthy"),
    ("min_words", "{a}.word_count >= ?", "present"),
    ("max_words", "{a}.word_count <= ?", "present"),
    (
        "linked_from",
        "{a}.id IN (SELECT target_id FROM links WHERE source_id = ? AND target_id IS NOT NULL)",
        "truthy",
    ),
    ("linked_to", "{a}.id IN (SELECT source_id FROM links WHERE target_id = ?)", "truthy"),
    (
        "min_inbound",
        "{a}.id IN (SELECT target_id FROM links WHERE target_id IS NOT NULL GROUP BY target_id HAVING COUNT(*) >= ?)",
        "present",
    ),
)


@dataclass
class SearchFilters:
    tags: list[str] | None = None
    status: str | None = None
    note_type: str | None = None
    tier: str | None = None  # Epistemic tier filter
    content_type: str | None = None  # Artifact kind filter
    after: str | None = None
    before: str | None = None
    path_glob: str | None = None
    parent: str | None = None
    min_words: int | None = None
    max_words: int | None = None
    # Graph-aware filters
    linked_from: str | None = None  # Only notes linked FROM this note ID
    linked_to: str | None = None  # Only notes that link TO this note ID
    min_inbound: int | None = None  # Minimum inbound link count
    has_backlinks: bool | None = None  # Must have at least one inbound link

    def to_sql(self, table_alias: str = "n") -> tuple[str, list]:
        """Build SQL WHERE clauses and parameters."""
        clauses: list[str] = []
        params: list = []

        for tag in self.tags or []:
            clauses.append(f"{table_alias}.id IN (SELECT note_id FROM tags WHERE tag = ?)")
            params.append(tag.lower())

        for attr, template, keep in _FIELD_CLAUSES:
            value = getattr(self, attr)
            if (value is not None) if keep == "present" else value:
                clauses.append(template.format(a=table_alias))
                params.append(value)

        if self.has_backlinks is True:
            clauses.append(
                f"{table_alias}.id IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL)"
            )

        where = " AND ".join(clauses) if clauses else "1=1"
        return where, params
