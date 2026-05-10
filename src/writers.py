from __future__ import annotations

import csv
from dataclasses import fields, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Type, TypeVar
from datetime import datetime, date


T = TypeVar('T')


def write_csv(path: Path, headers: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def append_csv(path: Path, headers: List[str], rows: List[Dict[str, str]]) -> None:
    file_exists = path.exists()
    with path.open('a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open('r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_dataclass_rows(path: Path, cls: Type[T]) -> list[T]:
    rows = read_csv(path)
    field_types = {field.name: field.type for field in fields(cls)}

    def convert(value: str, target_type: Any) -> Any:
        if target_type in {int, 'int'}:
            return int(value)
        if target_type in {float, 'float'}:
            return float(value)
        if target_type is date or getattr(target_type, '__name__', None) == 'date':
            return date.fromisoformat(value)
        if target_type is datetime or getattr(target_type, '__name__', None) == 'datetime':
            return datetime.fromisoformat(value)
        return value

    converted: list[T] = []
    for row in rows:
        kwargs = {name: convert(value, field_types[name]) for name, value in row.items() if name in field_types}
        converted.append(cls(**kwargs))
    return converted


def infer_dataclass_value(value: str) -> Any:
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    try:
        return date.fromisoformat(value)
    except ValueError:
        return value
