"""The reference population: every dwelling an attacker could confuse a record with.

The population is a table with one row per dwelling (BAG *verblijfsobject* with a residential
function) and canonical attribute columns (see :data:`anonymate.qids.CATALOGUE`). It normally
lives in the local store built by :mod:`anonymate.store`; for tests and experiments any pandas
DataFrame with the right columns will do.

A :class:`Scope` narrows the population to what the attacker knows the dataset was drawn from:
a region ("a project in Zwolle") and/or inclusion criteria ("detached homes built before 1990").
Narrowing is never "optional precision": published inclusion criteria *are* background
knowledge, and ignoring them makes the risk look smaller than it is.
"""
from __future__ import annotations

import os

from dataclasses import dataclass, field
from typing import Mapping

import duckdb
import pandas as pd

from . import namen
from .constraints import Constraint, OneOf, Range


@dataclass(frozen=True)
class Snapshot:
    """Where the population came from, so every report can be reproduced."""

    sources: Mapping[str, str] = field(default_factory=dict)  # source name -> version/date

    def describe(self) -> str:
        if not self.sources:
            return "onbekend / unknown"
        return "; ".join(f"{k} {v}" for k, v in sorted(self.sources.items()))


@dataclass(frozen=True)
class Scope:
    """Restriction of the population to what the dataset could have been drawn from.

    ``criteria`` maps a population column to a constraint the dwelling must satisfy, e.g.
    ``{"woningtype__cat": OneOf.of("vrijstaand", "twee_onder_een_kap", "hoekwoning",
    "tussenwoning"), "oppervlakte__m2": Range(50, 250)}``; ``exclude`` to a constraint it must
    *not* satisfy, e.g. ``{"gemeente__cat": OneOf.of("Amsterdam")}`` (a dwelling with an unknown value is kept).
    """

    criteria: Mapping[str, Constraint] = field(default_factory=dict)
    description: str = ""
    exclude: Mapping[str, Constraint] = field(default_factory=dict)

    @classmethod
    def region(cls, column: str, *values: str) -> "Scope":
        return cls({column: OneOf(frozenset(values))}, f"{column} in {', '.join(values)}")

    def __and__(self, other: "Scope") -> "Scope":
        crit = dict(self.criteria)
        for k, v in other.criteria.items():
            if k in crit:
                raise ValueError(f"criterion on {k!r} given twice")
            crit[k] = v
        desc = " en ".join(d for d in (self.description, other.description) if d)
        excl = dict(self.exclude)
        for k, v in other.exclude.items():
            if k in excl:
                raise ValueError(f"exclusion on {k!r} given twice")
            excl[k] = v
        return Scope(crit, desc, excl)

    def is_everything(self) -> bool:
        return not any(c is not None for c in self.criteria.values()) and \
            not any(c is not None for c in self.exclude.values())


def sql_condition(column: str, c: Constraint, params: list) -> str:
    """SQL predicate for ``column`` satisfying ``c``; appends bind values to ``params``."""
    col = _quote(column)
    if c is None:
        return "TRUE"
    if isinstance(c, Range):
        parts = []
        if c.lo is not None:
            parts.append(f"{col} >= ?")
            params.append(c.lo)
        if c.hi is not None:
            parts.append(f"{col} <= ?")
            params.append(c.hi)
        return " AND ".join(parts) if parts else f"{col} IS NOT NULL"
    if isinstance(c, OneOf):
        params.append(sorted(c.values))
        return f"list_contains(?, CAST({col} AS VARCHAR))"
    raise TypeError(c)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# the column of an aanvulling (Population.from_parquet) that says its row holds the values
AANGEVULD = "aangevuld__bool"


class Population:
    """A reference population held in DuckDB.

    Use :meth:`from_dataframe` for in-memory data or :meth:`from_parquet` / the store for the
    real thing. Nothing here performs network I/O.
    """

    def __init__(self, con: duckdb.DuckDBPyConnection, relation: str, snapshot: Snapshot,
                 scope: Scope | None = None):
        self.con = con
        self.relation = relation  # a table or view name, or a parenthesised subquery
        self.snapshot = snapshot
        self.scope = scope or Scope()
        self.columns: list[str] = [
            r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
        ]

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame, snapshot: Snapshot | None = None) -> "Population":
        con = duckdb.connect()
        # materialise once: scanning a pandas frame re-converts its columns on every query
        con.register("population_df", df)
        con.execute("CREATE TABLE population AS SELECT * FROM population_df")
        con.unregister("population_df")
        return cls(con, "population", snapshot or Snapshot({"dataframe": "in-memory"}))

    @classmethod
    def from_parquet(cls, path: str, snapshot: Snapshot, *,
                     memory_limit: str | None = None,
                     aanvulling: str | None = None) -> "Population":
        """``memory_limit`` (default ``$ANONYMATE_GEHEUGEN`` or 1GB) caps DuckDB, whose own
        default of 80% of RAM crowds out everything else on a laptop; queries spill to disk.

        ``aanvulling``: Parquet file(s) with one row per row of ``path``, in the same order, that
        replace or add columns where :data:`AANGEVULD` is true (EP-online added in the browser,
        :func:`anonymate.web.add_eponline`). Joined by position, so no key lookup per query."""
        con = duckdb.connect()
        con.execute(f"SET memory_limit = '{memory_limit or os.environ.get('ANONYMATE_GEHEUGEN', '1GB')}'")
        # a population built before the naming convention (docs/variabelen.md) is read under
        # the new names: the view gives each old column its new name as an alias
        rel = namen.parquet_relatie(path, con=con)
        if aanvulling:
            extra = "read_parquet('" + str(aanvulling).replace("'", "''") + "')"
            basis = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()]
            erbij = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {extra}").fetchall()]
            kolommen = [f'CASE WHEN a."{AANGEVULD}" THEN a."{c}" ELSE b."{c}" END AS "{c}"'
                        if c in erbij else f'b."{c}"' for c in basis]
            kolommen += [f'a."{c}"' for c in erbij if c not in basis and c != AANGEVULD]
            rel = f"(SELECT {', '.join(kolommen)} FROM {rel} b POSITIONAL JOIN {extra} a)"
        con.execute(f"CREATE VIEW population AS SELECT * FROM {rel}")
        return cls(con, "population", snapshot)

    def within(self, scope: Scope) -> "Population":
        """This population narrowed by an additional scope."""
        return Population(self.con, self.relation, self.snapshot, self.scope & scope)

    def where(self, params: list) -> str:
        """SQL WHERE-clause body for the current scope."""
        conds = []
        for column, c in self.scope.criteria.items():
            self.require(column)
            conds.append(sql_condition(column, c, params))
        for column, c in self.scope.exclude.items():
            if c is None:
                continue
            self.require(column)
            conds.append(f"NOT coalesce(({sql_condition(column, c, params)}), FALSE)")
        return " AND ".join(conds) or "TRUE"

    def require(self, column: str) -> None:
        if column not in self.columns:
            raise KeyError(
                f"de populatie heeft geen kolom {column!r} / population has no column {column!r}; "
                f"beschikbaar / available: {', '.join(self.columns)}"
            )

    def size(self) -> int:
        params: list = []
        sql = f"SELECT count(*) FROM {self.relation} WHERE {self.where(params)}"
        return int(self.con.execute(sql, params).fetchone()[0])

    def lookup(self, column: str, key_column: str, keys: list[str]) -> dict[str, str]:
        """Most frequent value of ``column`` per value of ``key_column`` (e.g. pc4 -> gemeente)."""
        self.require(column)
        self.require(key_column)
        sql = f"""
            SELECT k, arg_max(v, n) FROM (
                SELECT CAST({_quote(key_column)} AS VARCHAR) k, CAST({_quote(column)} AS VARCHAR) v,
                       count(*) n
                FROM {self.relation}
                WHERE list_contains(?, CAST({_quote(key_column)} AS VARCHAR))
                GROUP BY ALL
            ) GROUP BY k
        """
        return dict(self.con.execute(sql, [sorted(set(keys))]).fetchall())
