"""PostgreSQL connection and dataframe persistence helpers."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Generator, Mapping, Sequence

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import Boolean, SmallInteger, create_engine, text
from sqlalchemy.engine import Connection, Engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_BOOLEAN_COLUMNS = {
    "flooded_2022",
    "flooded_2025",
    "has_balcony",
    "free_hours",
    "has_camera_security",
    "has_elevator",
    "has_mezzanine",
    "private_bathroom",
    "wifi",
    "has_parking",
    "has_window",
}
_SMALL_INTEGER_COLUMNS = {"flood_risk_label"}


def _sqlalchemy_dtype(columns: Sequence[str]) -> dict[str, Boolean | SmallInteger]:
    types: dict[str, Boolean | SmallInteger] = {
        column: Boolean() for column in columns if column in _BOOLEAN_COLUMNS
    }
    types.update(
        {
            column: SmallInteger()
            for column in columns
            if column in _SMALL_INTEGER_COLUMNS
        }
    )
    return types


def _load_environment() -> None:
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    else:
        load_dotenv()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    _load_environment()
    dsn = os.getenv("POSTGRES_DSN", "").strip()
    if not dsn:
        raise RuntimeError(
            "POSTGRES_DSN is not configured. Set it in the local .env file."
        )
    if not dsn.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError(
            "POSTGRES_DSN must use postgresql:// or postgresql+psycopg://."
        )
    if dsn.startswith("postgresql://"):
        dsn = "postgresql+psycopg://" + dsn.removeprefix("postgresql://")
    return create_engine(dsn, pool_pre_ping=True, future=True)


def validate_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return value


@contextmanager
def connection_scope(
    connection: Connection | None = None, *, transaction: bool = False
) -> Generator[Connection, None, None]:
    if connection is not None:
        if transaction:
            transaction_scope = (
                connection.begin_nested()
                if connection.in_transaction()
                else connection.begin()
            )
            with transaction_scope:
                yield connection
        else:
            yield connection
        return

    engine = get_engine()
    if transaction:
        with engine.begin() as owned_connection:
            yield owned_connection
    else:
        with engine.connect() as owned_connection:
            yield owned_connection


def read_dataframe(
    query: str,
    params: dict | None = None,
    *,
    connection: Connection | None = None,
) -> pd.DataFrame:
    with connection_scope(connection) as active_connection:
        return pd.read_sql_query(text(query), active_connection, params=params or {})


def execute(
    query: str,
    params: dict | Sequence[dict] | None = None,
    *,
    connection: Connection | None = None,
) -> int:
    with connection_scope(connection, transaction=connection is None) as active_connection:
        result = active_connection.execute(text(query), params or {})
        return max(result.rowcount, 0)


def replace_dataframe(
    schema: str,
    table: str,
    dataframe: pd.DataFrame,
    columns: Sequence[str],
    *,
    connection: Connection | None = None,
    dtype_overrides: Mapping[str, Boolean | SmallInteger] | None = None,
) -> int:
    schema = validate_identifier(schema)
    table = validate_identifier(table)
    missing = [column for column in columns if column not in dataframe.columns]
    if missing:
        raise KeyError(f"{schema}.{table} input is missing columns: {missing}")

    frame = dataframe.loc[:, list(columns)].copy()
    statement = text(f'TRUNCATE TABLE "{schema}"."{table}"')
    with connection_scope(connection, transaction=True) as active_connection:
        active_connection.execute(statement)
        if not frame.empty:
            frame.to_sql(
                table,
                con=active_connection,
                schema=schema,
                if_exists="append",
                index=False,
                chunksize=1000,
                method="multi",
                dtype={
                    **_sqlalchemy_dtype(columns),
                    **(dtype_overrides or {}),
                },
            )
    return len(frame)


def append_dataframe(
    schema: str,
    table: str,
    dataframe: pd.DataFrame,
    columns: Sequence[str],
    *,
    connection: Connection | None = None,
) -> int:
    schema = validate_identifier(schema)
    table = validate_identifier(table)
    if dataframe.empty:
        return 0

    missing = [column for column in columns if column not in dataframe.columns]
    if missing:
        raise KeyError(f"{schema}.{table} input is missing columns: {missing}")
    frame = dataframe.loc[:, list(columns)].copy()
    with connection_scope(connection, transaction=True) as active_connection:
        frame.to_sql(
            table,
            con=active_connection,
            schema=schema,
            if_exists="append",
            index=False,
            chunksize=1000,
            method="multi",
            dtype=_sqlalchemy_dtype(columns),
        )
    return len(frame)
