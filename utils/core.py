from __future__ import annotations

import hashlib
import io
import json
import math
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "codebook_schema.json"
SAMPLE_PATH = ROOT / "data" / "sample_items.csv"
STANDARD_PATH = ROOT / "data" / "annotation_standard_zh.json"


def read_json(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_annotation_standard(path: Path = STANDARD_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_errors(schema: Any) -> list[str]:
    if not isinstance(schema, dict):
        return ["Codebook 顶层必须是 JSON object。"]
    fields = schema.get("fields")
    if not isinstance(fields, list) or not fields:
        return ["fields 必须是非空 list。"]

    errors: list[str] = []
    required = schema.get("field_contract", {}).get("required_properties", [])
    pattern = re.compile(schema.get("field_contract", {}).get("id_pattern", r"^[a-z][a-z0-9_]*$"))
    seen: set[str] = set()
    for index, field in enumerate(fields, start=1):
        if not isinstance(field, dict):
            errors.append(f"第 {index} 个字段不是 object。")
            continue
        field_id = str(field.get("id", "")).strip()
        if not field_id:
            errors.append(f"第 {index} 个字段缺少 id。")
        elif field_id in seen:
            errors.append(f"字段 id 重复：{field_id}。")
        elif not pattern.fullmatch(field_id):
            errors.append(f"字段 id 不符合命名规则：{field_id}。")
        seen.add(field_id)
        missing = [key for key in required if key not in field]
        if missing:
            errors.append(f"{field_id or index} 缺少：{', '.join(missing)}。")
        values = field.get("full_value_list", [])
        if field.get("field_type") in {"controlled_single", "controlled_multi"}:
            if not isinstance(values, list) or not [value for value in values if str(value).strip()]:
                errors.append(f"{field_id} 是受控字段，但没有有效选项。")
            elif len({str(value).strip() for value in values}) != len(values):
                errors.append(f"{field_id} 的选项存在重复值。")
        if field.get("field_type") == "record_list":
            record_fields = field.get("record_fields", [])
            if not isinstance(record_fields, list) or not all(str(value).strip() for value in record_fields):
                errors.append(f"{field_id} 是record_list，但没有有效record_fields。")
        if field.get("provenance_class") not in schema.get("provenance_classes", {}):
            errors.append(f"{field_id} 的 provenance_class 无效或缺失。")
    retired = {"close_analysis_selection", "selection_stratum"}
    stale = retired.intersection(seen)
    if stale:
        errors.append(f"已删除的抽样字段仍存在：{', '.join(sorted(stale))}。")
    return errors


def field_map(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {field["id"]: field for field in schema["fields"]}


def level_code(field: dict[str, Any]) -> str:
    return str(field.get("analytical_level", "L9")).split(maxsplit=1)[0]


def fields_for_role(schema: dict[str, Any], role: str) -> list[dict[str, Any]]:
    if role == "Coder":
        roles = {"coder", "coder_verification"}
    elif role == "Researcher":
        roles = {"researcher"}
    else:
        roles = set()
    return [field for field in schema["fields"] if field.get("entry_role") in roles]


def fields_by_level(fields: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        grouped.setdefault(level_code(field), []).append(field)
    return grouped


def stable_item_id(row: pd.Series, ordinal: int = 0) -> str:
    for candidate in ("event_id", "Event ID", "item_id", "Item ID", "No.", "No", "ID"):
        value = str(row.get(candidate, "")).strip()
        if value:
            return value
    parts = [
        str(row.get(key, "")).strip()
        for key in (
            "scene_label", "Scene", "speaker", "Speaker", "target", "Target",
            "st_naming_expression", "ST naming instance", "tt_naming_expression", "TT rendering",
        )
    ]
    digest = hashlib.sha256("\u241f".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"ZN-{digest}"


def ensure_item_ids(df: pd.DataFrame) -> pd.DataFrame:
    clean = df.fillna("").astype(str).copy()
    ids = [stable_item_id(row, index) for index, (_, row) in enumerate(clean.iterrows())]
    if "event_id" in clean:
        provided = [str(value).strip() for value in clean["event_id"] if str(value).strip()]
        if len(provided) != len(set(provided)):
            raise ValueError("event_id存在重复值；请在元数据表中修正后重新上传。")
    if len(set(ids)) != len(ids):
        counts: dict[str, int] = {}
        unique_ids = []
        for value in ids:
            counts[value] = counts.get(value, 0) + 1
            unique_ids.append(value if counts[value] == 1 else f"{value}-{counts[value]}")
        ids = unique_ids
    if "event_id" in clean:
        clean["event_id"] = ids
    else:
        clean.insert(0, "event_id", ids)
    return clean


def read_sample_items() -> pd.DataFrame:
    return ensure_item_ids(pd.read_csv(SAMPLE_PATH, dtype=str).fillna(""))


_XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XLSX_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XLSX_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _xlsx_sheet_targets(data: bytes) -> list[tuple[str, str]]:
    """Return (visible sheet name, worksheet XML path) without third-party engines."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target_by_id = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in relationships.findall(f"{{{_XLSX_PACKAGE_REL_NS}}}Relationship")
        }
        result: list[tuple[str, str]] = []
        for sheet in workbook.findall(f".//{{{_XLSX_MAIN_NS}}}sheet"):
            relationship_id = sheet.attrib.get(f"{{{_XLSX_DOC_REL_NS}}}id", "")
            target = target_by_id.get(relationship_id, "")
            if not target:
                continue
            if target.startswith("/"):
                xml_path = target.lstrip("/")
            else:
                xml_path = posixpath.normpath(posixpath.join("xl", target))
            result.append((sheet.attrib.get("name", "Sheet"), xml_path))
        return result


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(node.text or "" for node in item.findall(f".//{{{_XLSX_MAIN_NS}}}t"))
        for item in root.findall(f"{{{_XLSX_MAIN_NS}}}si")
    ]


def _xlsx_column_index(cell_reference: str) -> int:
    letters = re.match(r"[A-Za-z]+", cell_reference)
    if not letters:
        return 0
    value = 0
    for letter in letters.group(0).upper():
        value = value * 26 + (ord(letter) - 64)
    return value - 1


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> Any:
    cell_type = cell.attrib.get("t", "n")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{{{_XLSX_MAIN_NS}}}t"))
    value_node = cell.find(f"{{{_XLSX_MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text
    if cell_type == "s":
        index = int(raw)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    if cell_type in {"str", "e"}:
        return raw
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    try:
        number = float(raw)
        return int(number) if number.is_integer() else number
    except ValueError:
        return raw


def _read_xlsx_without_openpyxl(data: bytes, sheet_name: str | None = None) -> pd.DataFrame:
    """Read the plain cell table used by this project if openpyxl is unavailable."""
    sheet_targets = _xlsx_sheet_targets(data)
    if not sheet_targets:
        raise ValueError("XLSX 文件中没有可读取的工作表。")
    selected_name = sheet_name or preferred_sheet([name for name, _ in sheet_targets])
    target = next((path for name, path in sheet_targets if name == selected_name), None)
    if target is None:
        raise ValueError(f"找不到工作表：{selected_name}")

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared_strings = _xlsx_shared_strings(archive)
        root = ET.fromstring(archive.read(target))
        rows: list[list[Any]] = []
        max_width = 0
        for row_node in root.findall(f".//{{{_XLSX_MAIN_NS}}}sheetData/{{{_XLSX_MAIN_NS}}}row"):
            row_values: list[Any] = []
            for cell in row_node.findall(f"{{{_XLSX_MAIN_NS}}}c"):
                index = _xlsx_column_index(cell.attrib.get("r", "A1"))
                if len(row_values) <= index:
                    row_values.extend([""] * (index + 1 - len(row_values)))
                row_values[index] = _xlsx_cell_value(cell, shared_strings)
            max_width = max(max_width, len(row_values))
            rows.append(row_values)

    if not rows:
        return pd.DataFrame()
    rows = [row + [""] * (max_width - len(row)) for row in rows]
    headers = [str(value).strip() for value in rows[0]]
    if not any(headers):
        raise ValueError("所选工作表第一行没有字段名。")
    return pd.DataFrame(rows[1:], columns=headers).fillna("").astype(str)


def workbook_sheets(data: bytes, filename: str) -> list[str]:
    if filename.lower().endswith(".xlsx"):
        try:
            return pd.ExcelFile(io.BytesIO(data), engine="openpyxl").sheet_names
        except (ImportError, ModuleNotFoundError):
            return [name for name, _ in _xlsx_sheet_targets(data)]
    if filename.lower().endswith(".xls"):
        return pd.ExcelFile(io.BytesIO(data), engine="xlrd").sheet_names
    return []


def preferred_sheet(sheets: list[str]) -> str:
    for candidate in ("Annotation_Items", "Detailed_Annotation", "FiveCol_Annotation"):
        if candidate in sheets:
            return candidate
    meaningful = [sheet for sheet in sheets if sheet.lower() not in {"readme", "summary", "tag_guide"}]
    return meaningful[0] if meaningful else sheets[0]


def read_table(data: bytes, filename: str, sheet_name: str | None = None) -> pd.DataFrame:
    stream = io.BytesIO(data)
    if filename.lower().endswith(".csv"):
        return ensure_item_ids(pd.read_csv(stream, dtype=str).fillna(""))
    if filename.lower().endswith(".xlsx"):
        try:
            frame = pd.read_excel(stream, sheet_name=sheet_name, dtype=str, engine="openpyxl").fillna("")
        except (ImportError, ModuleNotFoundError):
            frame = _read_xlsx_without_openpyxl(data, sheet_name)
        return ensure_item_ids(frame)
    if filename.lower().endswith(".xls"):
        return ensure_item_ids(pd.read_excel(stream, sheet_name=sheet_name, dtype=str, engine="xlrd").fillna(""))
    raise ValueError("仅支持 CSV、XLSX 或 XLS。")


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def annotations_frame(annotations: dict[str, dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for annotation in annotations.values():
        normalized = {}
        for key, value in annotation.items():
            if isinstance(value, list) and any(isinstance(item, dict) for item in value):
                normalized[key] = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, list):
                normalized[key] = " | ".join(str(item) for item in value)
            else:
                normalized[key] = value
        rows.append(normalized)
    return pd.DataFrame(rows)


def parse_multi(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None or not str(value).strip():
        return []
    return [item.strip() for item in re.split(r"\s*[|;]\s*", str(value)) if item.strip()]


def parse_records(value: Any, columns: list[str]) -> list[dict[str, str]]:
    if isinstance(value, list):
        rows = value
    elif value is None or not str(value).strip():
        rows = []
    else:
        try:
            loaded = json.loads(str(value))
            rows = loaded if isinstance(loaded, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            rows = []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean = {column: str(row.get(column, "")).strip() for column in columns}
        if any(clean.values()):
            result.append(clean)
    return result


def is_blank(value: Any) -> bool:
    if isinstance(value, list):
        return not value
    return not str(value).strip()


def record_constraint_errors(schema: dict[str, Any], values: dict[str, Any]) -> list[str]:
    errors = []
    fmap = field_map(schema)
    for status_id, requirement in schema.get("record_constraints", {}).items():
        trigger_value, records_id = requirement
        if values.get(status_id) != trigger_value:
            continue
        if is_blank(values.get(records_id)):
            label = fmap.get(records_id, {}).get("display_name", records_id)
            errors.append(f"{label}：当前Status要求至少一条Record。")
    return errors


def percent_agreement(a: pd.Series, b: pd.Series) -> float:
    valid = ~(a.isna() | b.isna())
    return math.nan if valid.sum() == 0 else float((a[valid].astype(str) == b[valid].astype(str)).mean())


def cohen_kappa(a: pd.Series, b: pd.Series) -> float:
    valid = ~(a.isna() | b.isna())
    left, right = a[valid].astype(str), b[valid].astype(str)
    if left.empty:
        return math.nan
    observed = float((left == right).mean())
    labels = set(left) | set(right)
    expected = sum(float(left.eq(label).mean() * right.eq(label).mean()) for label in labels)
    return math.nan if abs(1 - expected) < 1e-12 else (observed - expected) / (1 - expected)


def compare_coders(left: pd.DataFrame, right: pd.DataFrame, fields: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    id_col = next((name for name in ("event_id", "Event ID", "item_id", "Item ID", "No.", "No", "ID") if name in left and name in right), None)
    if id_col is None:
        raise ValueError("两份文件需要相同的 event_id（或旧版 item_id／No.）列。")
    merged = left.merge(right, on=id_col, suffixes=("_coder1", "_coder2"), how="inner")
    summary, disagreements = [], []
    for field in fields:
        a_col, b_col = f"{field}_coder1", f"{field}_coder2"
        if a_col not in merged or b_col not in merged:
            continue
        summary.append({
            "field": field,
            "n_compared": int((~(merged[a_col].isna() | merged[b_col].isna())).sum()),
            "percent_agreement": percent_agreement(merged[a_col], merged[b_col]),
            "cohen_kappa": cohen_kappa(merged[a_col], merged[b_col]),
        })
        mismatch = merged[a_col].astype(str) != merged[b_col].astype(str)
        for _, row in merged.loc[mismatch, [id_col, a_col, b_col]].iterrows():
            disagreements.append({
                "event_id": row[id_col], "field": field,
                "coder_1": row[a_col], "coder_2": row[b_col],
            })
    return pd.DataFrame(summary), pd.DataFrame(disagreements)
