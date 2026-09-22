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
            required_record_fields = field.get("required_record_fields", [])
            unknown_required = set(required_record_fields) - set(record_fields)
            if unknown_required:
                errors.append(f"{field_id} 的required_record_fields不存在：{', '.join(sorted(unknown_required))}。")
            column_types = field.get("record_column_types", {})
            value_lists = field.get("record_value_lists", {})
            unknown_typed = set(column_types) - set(record_fields)
            if unknown_typed:
                errors.append(f"{field_id} 的record column不存在：{', '.join(sorted(unknown_typed))}。")
            for column, column_type in column_types.items():
                if column_type not in {"select", "multiselect", "text"}:
                    errors.append(f"{field_id}.{column} 的record column type无效。")
                if column_type in {"select", "multiselect"} and not value_lists.get(column):
                    errors.append(f"{field_id}.{column} 缺少受控值域。")
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
        roles = {"researcher", "coder_verification"}
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


def parse_records(value: Any, columns: list[str]) -> list[dict[str, Any]]:
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
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean: dict[str, Any] = {}
        for column in columns:
            raw = row.get(column, "")
            if isinstance(raw, list):
                clean[column] = [str(item).strip() for item in raw if str(item).strip()]
            else:
                clean[column] = str(raw).strip()
        if any(not is_blank(item) for item in clean.values()):
            result.append(clean)
    return result


def is_blank(value: Any) -> bool:
    if isinstance(value, list):
        return not value or all(is_blank(item) for item in value)
    if isinstance(value, dict):
        return not value or all(is_blank(item) for item in value.values())
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
    for field in schema.get("fields", []):
        if field.get("field_type") != "record_list":
            continue
        field_id = field["id"]
        columns = field.get("record_fields", [])
        records = parse_records(values.get(field_id), columns)
        required_columns = field.get("required_record_fields", [])
        value_lists = field.get("record_value_lists", {})
        column_types = field.get("record_column_types", {})
        for row_number, record in enumerate(records, start=1):
            for column in required_columns:
                if is_blank(record.get(column)):
                    errors.append(f"{field_id} 第{row_number}条缺少 {column}。")
            for column, options in value_lists.items():
                raw = record.get(column)
                chosen = raw if isinstance(raw, list) else ([] if is_blank(raw) else [raw])
                invalid = [str(item) for item in chosen if str(item) not in options]
                if invalid:
                    errors.append(f"{field_id} 第{row_number}条 {column} 含无效值：{', '.join(invalid)}。")

            if field_id in {"st_intermodal_relation_records", "tt_intermodal_relation_records"}:
                component_set = str(record.get("component_set", ""))
                component_requirements = {
                    "Verbal": "verbal_component",
                    "Vocal": "vocal_record_ids",
                    "Visual": "visual_record_ids",
                }
                for component, column in component_requirements.items():
                    if component in component_set and is_blank(record.get(column)):
                        errors.append(f"{field_id} 第{row_number}条选择了{component}，必须填写 {column}。")

            if field_id == "intermodal_relation_change_records":
                relation = str(record.get("intermodal_relation_change", ""))
                if relation in {"Retained", "Changed"}:
                    if is_blank(record.get("st_record_id")) or is_blank(record.get("tt_record_id")):
                        errors.append(f"{field_id} 第{row_number}条的{relation}需要ST和TT record IDs。")
                elif relation == "ST Relation Not Maintained" and is_blank(record.get("st_record_id")):
                    errors.append(f"{field_id} 第{row_number}条需要st_record_id。")
                elif relation == "New TT Relation" and is_blank(record.get("tt_record_id")):
                    errors.append(f"{field_id} 第{row_number}条需要tt_record_id。")

            if field_id == "support_redistribution_records":
                status = str(record.get("support_redistribution_status", ""))
                if status in {"Redistributed", "Mixed／Partial"}:
                    if is_blank(record.get("support_from")) or is_blank(record.get("support_to")):
                        errors.append(f"{field_id} 第{row_number}条的{status}必须填写support_from和support_to。")
    return errors


def parse_timecode_seconds(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    text = text.split("–", 1)[0].strip()
    parts = text.split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 1:
        return numbers[0]
    return None


def derive_clip_duration(values: dict[str, Any]) -> float | None:
    start = parse_timecode_seconds(values.get("shared_av_window_start"))
    end = parse_timecode_seconds(values.get("shared_av_window_end"))
    if start is None or end is None or end <= start:
        return None
    return round(end - start, 6)


def derive_temporal_values(values: dict[str, Any]) -> dict[str, Any]:
    if values.get("st_naming_presence") != "Overt" or values.get("tt_naming_presence") != "Overt":
        return {"temporal_comparability": "Not Comparable"}
    duration = values.get("clip_duration") or derive_clip_duration(values)
    try:
        duration = float(duration)
        s0, s1 = float(values.get("st_naming_onset", "")), float(values.get("st_naming_offset", ""))
        t0, t1 = float(values.get("tt_naming_onset", "")), float(values.get("tt_naming_offset", ""))
        if duration <= 0 or s1 < s0 or t1 < t0:
            raise ValueError
    except (TypeError, ValueError):
        return {"temporal_comparability": "Not Assessable"}
    intersection = max(0.0, min(s1, t1) - max(s0, t0))
    union = max(s1, t1) - min(s0, t0)
    return {
        "clip_duration": round(duration, 6),
        "normalized_st_onset": round(s0 / duration, 6),
        "normalized_st_offset": round(s1 / duration, 6),
        "normalized_tt_onset": round(t0 / duration, 6),
        "normalized_tt_offset": round(t1 / duration, 6),
        "temporal_iou": round(intersection / union, 6) if union > 0 else 1.0,
        "temporal_comparability": "Comparable",
    }


def _normalized_text(value: Any) -> str:
    return re.sub(r"\W+", "", str(value or "").casefold(), flags=re.UNICODE)


def derive_verbal_values(values: dict[str, Any]) -> dict[str, Any]:
    pattern = str(values.get("verbal_correspondence", "")).strip()
    if not pattern:
        return {}
    flags: list[str] = []
    st_expression = _normalized_text(values.get("st_naming_expression"))
    tt_expression = _normalized_text(values.get("tt_naming_expression"))
    st_bases = set(parse_multi(values.get("st_naming_bases")))
    tt_bases = set(parse_multi(values.get("tt_naming_bases")))
    st_treatment = str(values.get("st_interactional_treatment", ""))
    tt_treatment = str(values.get("tt_interactional_treatment", ""))
    if pattern == "Comparable Overt Naming":
        flags.append("Close Retention" if st_expression and st_expression == tt_expression else "Reformulation")
    elif pattern == "Reconfigured Overt Naming":
        if st_bases != tt_bases:
            flags.append("Basis Shift")
        if st_treatment != tt_treatment:
            flags.append("Treatment Shift")
        if st_expression and tt_expression:
            ratio = len(tt_expression) / max(len(st_expression), 1)
            if ratio >= 1.2:
                flags.append("Expansion")
            elif ratio <= 0.8:
                flags.append("Compression")
        if not flags:
            flags.append("Reformulation")
    elif pattern == "ST-only Overt Naming":
        flags.extend(["De-naming", "Omission"])
    elif pattern == "TT-only Overt Naming":
        flags.append("Addition")
    else:
        flags.append("No flag")
    return {"derived_verbal_rendering_pattern": pattern, "derived_verbal_flags": flags}


def derive_intermodal_change_records(values: dict[str, Any], event_id: str) -> list[dict[str, str]]:
    columns = ["record_id", "component_set", "verbal_component", "vocal_record_ids", "visual_record_ids", "local_claim", "relation_type", "evidence_note"]
    st_records = parse_records(values.get("st_intermodal_relation_records"), columns)
    tt_records = parse_records(values.get("tt_intermodal_relation_records"), columns)
    unused_tt = set(range(len(tt_records)))
    result: list[dict[str, str]] = []
    ordinal = 0
    for st_record in st_records:
        match = next((index for index in unused_tt if _normalized_text(tt_records[index].get("local_claim")) == _normalized_text(st_record.get("local_claim")) and _normalized_text(st_record.get("local_claim"))), None)
        ordinal += 1
        if match is None:
            result.append({
                "intermodal_pair_id": f"{event_id}-IMPAIR-{ordinal:02d}",
                "st_record_id": str(st_record.get("record_id", "")),
                "tt_record_id": "",
                "intermodal_relation_change": "ST Relation Not Maintained",
                "note": "System suggestion: no TT record with the same normalized local claim.",
            })
            continue
        unused_tt.remove(match)
        tt_record = tt_records[match]
        same_type = st_record.get("relation_type") == tt_record.get("relation_type")
        result.append({
            "intermodal_pair_id": f"{event_id}-IMPAIR-{ordinal:02d}",
            "st_record_id": str(st_record.get("record_id", "")),
            "tt_record_id": str(tt_record.get("record_id", "")),
            "intermodal_relation_change": "Retained" if same_type else "Changed",
            "note": "System suggestion from exact normalized local-claim pairing; Researcher must verify.",
        })
    for index in sorted(unused_tt):
        ordinal += 1
        tt_record = tt_records[index]
        result.append({
            "intermodal_pair_id": f"{event_id}-IMPAIR-{ordinal:02d}",
            "st_record_id": "",
            "tt_record_id": str(tt_record.get("record_id", "")),
            "intermodal_relation_change": "New TT Relation",
            "note": "System suggestion: no ST record with the same normalized local claim.",
        })
    return result


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


def _span_bounds(value: Any) -> tuple[float, float] | None:
    # Spans are offsets, so the separator in "1-4" must not be parsed as a
    # negative sign. Negative offsets are outside the Codebook's span model.
    numbers = re.findall(r"\d+(?:\.\d+)?", str(value or ""))
    if len(numbers) < 2:
        return None
    start, end = float(numbers[0]), float(numbers[1])
    return (start, end) if end >= start else None


def _span_iou(left: Any, right: Any) -> float | None:
    a, b = _span_bounds(left), _span_bounds(right)
    if a is None or b is None:
        return None
    intersection = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return intersection / union if union > 0 else 1.0


def _set_scores(left: Any, right: Any) -> tuple[float, float]:
    a, b = set(parse_multi(left)), set(parse_multi(right))
    if not a and not b:
        return 1.0, 1.0
    union = a | b
    intersection = a & b
    jaccard = len(intersection) / len(union) if union else 1.0
    precision = len(intersection) / len(a) if a else 0.0
    recall = len(intersection) / len(b) if b else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return jaccard, f1


def compare_coders(
    left: pd.DataFrame,
    right: pd.DataFrame,
    fields: list[str],
    schema: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    id_col = next((name for name in ("event_id", "Event ID", "item_id", "Item ID", "No.", "No", "ID") if name in left and name in right), None)
    if id_col is None:
        raise ValueError("两份文件需要相同的 event_id（或旧版 item_id／No.）列。")
    merged = left.merge(right, on=id_col, suffixes=("_coder1", "_coder2"), how="inner")
    summary, disagreements = [], []
    fmap = field_map(schema) if schema else {}
    for field in fields:
        a_col, b_col = f"{field}_coder1", f"{field}_coder2"
        if a_col not in merged or b_col not in merged:
            continue
        left_values = merged[a_col].fillna("").astype(str)
        right_values = merged[b_col].fillna("").astype(str)
        field_type = fmap.get(field, {}).get("field_type", "")
        jaccards: list[float] = []
        set_f1s: list[float] = []
        span_ious: list[float] = []
        if field_type == "controlled_multi":
            for left_value, right_value in zip(left_values, right_values):
                jaccard, set_f1 = _set_scores(left_value, right_value)
                jaccards.append(jaccard)
                set_f1s.append(set_f1)
            exact_left = left_values.map(lambda value: " | ".join(sorted(parse_multi(value))))
            exact_right = right_values.map(lambda value: " | ".join(sorted(parse_multi(value))))
        else:
            exact_left, exact_right = left_values, right_values
        if field in {"st_text_span", "tt_text_span"}:
            span_ious = [score for score in (_span_iou(a, b) for a, b in zip(left_values, right_values)) if score is not None]
        summary.append({
            "field": field,
            "n_compared": int((~(merged[a_col].isna() | merged[b_col].isna())).sum()),
            "percent_agreement": percent_agreement(exact_left, exact_right),
            "cohen_kappa": cohen_kappa(exact_left, exact_right) if field_type != "controlled_multi" else math.nan,
            "mean_jaccard": sum(jaccards) / len(jaccards) if jaccards else math.nan,
            "mean_set_f1": sum(set_f1s) / len(set_f1s) if set_f1s else math.nan,
            "mean_span_iou": sum(span_ious) / len(span_ious) if span_ious else math.nan,
        })
        mismatch = exact_left != exact_right
        for _, row in merged.loc[mismatch, [id_col, a_col, b_col]].iterrows():
            disagreements.append({
                "event_id": row[id_col], "field": field,
                "coder_1": row[a_col], "coder_2": row[b_col],
            })
    return pd.DataFrame(summary), pd.DataFrame(disagreements)
