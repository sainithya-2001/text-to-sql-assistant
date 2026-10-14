"""Schema catalog: live table/column metadata from the backend joined with business descriptions."""

from __future__ import annotations

from dataclasses import dataclass

from ..db.base import Backend, Table
from . import descriptions


@dataclass(frozen=True)
class ColumnInfo:
    table: str
    name: str
    type: str
    description: str


@dataclass(frozen=True)
class TableInfo:
    name: str
    description: str
    columns: tuple[ColumnInfo, ...]
    row_count: int | None

    def render(self, qualifier: str = "") -> str:
        """Compact DDL-like text for the prompt."""
        lines = [f"-- {self.description}"]
        if self.row_count is not None:
            lines[0] += f" ({self.row_count:,} rows)"
        lines.append(f"TABLE {qualifier}{self.name} (")
        for i, c in enumerate(self.columns):
            sep = "," if i < len(self.columns) - 1 else ""
            note = f"  -- {c.description}" if c.description else ""
            lines.append(f"  {c.name} {c.type}{sep}{note}")
        lines.append(")")
        return "\n".join(lines)


class Catalog:
    def __init__(self, tables: list[Table], qualifier: str = ""):
        self.qualifier = qualifier
        self.tables: dict[str, TableInfo] = {}
        for t in sorted(tables, key=lambda t: t.name):
            col_docs = descriptions.COLUMNS.get(t.name, {})
            cols = tuple(ColumnInfo(t.name, c.name, c.type, col_docs.get(c.name, "")) for c in t.columns)
            self.tables[t.name] = TableInfo(t.name, descriptions.TABLES.get(t.name, ""), cols, t.row_count)
        self.foreign_keys = [
            fk for fk in descriptions.FOREIGN_KEYS if fk[0] in self.tables and fk[2] in self.tables
        ]

    @classmethod
    def from_backend(cls, backend: Backend) -> Catalog:
        # Both backends set a default schema on the connection, so unqualified names resolve.
        return cls(backend.tables())

    def names(self) -> list[str]:
        return list(self.tables)

    def neighbours(self, table: str) -> set[str]:
        out = set()
        for t, _, rt, _ in self.foreign_keys:
            if t == table:
                out.add(rt)
            elif rt == table:
                out.add(t)
        return out

    def join_path(self, tables: set[str]) -> set[str]:
        """Smallest connecting set: add bridge tables so `tables` are linked by FK joins (BFS)."""
        tables = {t for t in tables if t in self.tables}
        if len(tables) <= 1:
            return tables
        connected = {next(iter(sorted(tables)))}
        remaining = tables - connected
        while remaining:
            # BFS from the connected component to the nearest remaining table
            frontier = {t: [t] for t in sorted(connected)}  # sorted: set order varies per process
            seen = set(connected)
            found = None
            while frontier and not found:
                nxt = {}
                for t, path in frontier.items():
                    for n in sorted(self.neighbours(t)):
                        if n in seen:
                            continue
                        seen.add(n)
                        nxt[n] = path + [n]
                        if n in remaining:
                            found = nxt[n]
                            break
                    if found:
                        break
                frontier = nxt
            if not found:  # disconnected; give up on bridging
                connected |= remaining
                break
            connected |= set(found)
            remaining -= set(found)
        return connected

    def render(self, names: list[str] | None = None) -> str:
        names = sorted(names) if names is not None else self.names()
        parts = [self.tables[n].render(self.qualifier) for n in names if n in self.tables]
        fks = [f"{t}.{c} -> {rt}.{rc}" for t, c, rt, rc in self.foreign_keys if t in names and rt in names]
        if fks:
            parts.append("-- Join keys:\n" + "\n".join(f"--   {fk}" for fk in fks))
        return "\n\n".join(parts)
