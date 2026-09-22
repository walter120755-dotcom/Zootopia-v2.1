from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from utils.core import (
    compare_coders,
    derive_clip_duration,
    derive_temporal_values,
    derive_verbal_values,
    ensure_item_ids,
    fields_for_role,
    read_annotation_standard,
    read_json,
    read_table,
    record_constraint_errors,
    schema_errors,
    workbook_sheets,
)


def minimal_xlsx_bytes() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Annotation_Items" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="4" uniqueCount="4">'
            '<si><t>event_id</t></si><si><t>speaker</t></si><si><t>ZN-1</t></si><si><t>Judy</t></si></sst>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
            '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>'
            '</sheetData></worksheet>',
        )
    return output.getvalue()


def test_shipped_schema_is_valid():
    assert schema_errors(read_json()) == []


def test_v21_field_inventory_and_removed_l2():
    schema = read_json()
    standard = read_annotation_standard()
    schema_ids = [field["id"] for field in schema["fields"]]
    standard_ids = [field["id"] for level in standard["levels"] for field in level["fields"]]
    assert len(schema_ids) == 92
    assert schema_ids == standard_ids
    assert not any(field["analytical_level"].startswith("L2") for field in schema["fields"])
    assert schema["schema_version"] == "2.1-revised-web-alignment-fix"
    assert schema["interface_version"] == "2.1-web-alignment-fix"


def test_coder_field_set_contains_revised_core_fields():
    coder_fields = fields_for_role(read_json(), "Coder")
    ids = {field["id"] for field in coder_fields}
    assert {"inclusion_status", "shared_av_window_start", "st_naming_head", "tt_naming_head"} <= ids
    assert {"st_characterizing_function", "tt_characterizing_function"} <= ids


def test_record_fields_have_declared_columns():
    records = [field for field in read_json()["fields"] if field["field_type"] == "record_list"]
    assert records
    assert all(field.get("record_fields") for field in records)
    assert all(field.get("required_record_fields") for field in records)
    assert all(field.get("record_column_types") for field in records)


def test_researcher_can_verify_prefilled_fields():
    researcher_fields = fields_for_role(read_json(), "Researcher")
    roles = {field["entry_role"] for field in researcher_fields}
    assert {"researcher", "coder_verification"} <= roles


def test_media_fields_are_not_in_schema():
    ids = {field["id"] for field in read_json()["fields"]}
    assert not ids.intersection({"st_video_url", "tt_video_url", "praat_image_url", "praat_evidence_status"})


def test_schema_rejects_duplicate_field_ids():
    schema = read_json()
    schema["fields"].append(dict(schema["fields"][0]))
    assert any("重复" in error for error in schema_errors(schema))


def test_stable_ids_survive_row_reordering():
    frame = pd.DataFrame([
        {"speaker": "S1", "target": "T", "st_naming_expression": "x"},
        {"speaker": "S2", "target": "T", "st_naming_expression": "y"},
    ])
    first = ensure_item_ids(frame)
    second = ensure_item_ids(frame.iloc[::-1].reset_index(drop=True))
    assert set(first["event_id"]) == set(second["event_id"])


def test_reliability_comparison_and_disagreement_list():
    left = pd.DataFrame({"event_id": ["1", "2"], "field": ["A", "B"]})
    right = pd.DataFrame({"event_id": ["1", "2"], "field": ["A", "C"]})
    summary, disagreements = compare_coders(left, right, ["field"])
    assert summary.loc[0, "percent_agreement"] == 0.5
    assert disagreements.to_dict("records") == [
        {"event_id": "2", "field": "field", "coder_1": "B", "coder_2": "C"}
    ]


def test_temporal_derivation_uses_shared_clip_origin_and_iou():
    values = {
        "shared_av_window_start": "00:01:00.000",
        "shared_av_window_end": "00:01:10.000",
        "st_naming_presence": "Overt",
        "tt_naming_presence": "Overt",
        "st_naming_onset": "2.0",
        "st_naming_offset": "4.0",
        "tt_naming_onset": "3.0",
        "tt_naming_offset": "5.0",
    }
    assert derive_clip_duration(values) == 10.0
    derived = derive_temporal_values(values)
    assert derived["normalized_st_onset"] == 0.2
    assert derived["normalized_tt_offset"] == 0.5
    assert derived["temporal_iou"] == 0.333333


def test_verbal_derivation_and_record_validation():
    derived = derive_verbal_values({
        "verbal_correspondence": "ST-only Overt Naming",
        "st_naming_expression": "dumb bunny",
        "tt_naming_expression": "",
    })
    assert derived["derived_verbal_flags"] == ["De-naming", "Omission"]

    schema = read_json()
    errors = record_constraint_errors(schema, {
        "shared_visual_evidence_status": "One or More Material Visual Cues",
        "shared_visual_evidence_records": [{"visual_record_id": "", "cue_type": "Invalid"}],
    })
    assert any("clip_local_span" in error for error in errors)

    errors = record_constraint_errors(schema, {
        "shared_visual_evidence_records": [{
            "clip_local_span": "00:00.00–00:01.00",
            "cue_type": "Invalid",
            "visible_participants_or_objects": "Judy",
            "observable_note": "Judy visible",
        }],
    })
    assert any("无效值" in error for error in errors)


def test_multilabel_and_span_reliability_metrics():
    schema = read_json()
    left = pd.DataFrame({
        "event_id": ["1"],
        "st_naming_bases": ["Species／Group | Role／Institution"],
        "st_text_span": ["1-4"],
    })
    right = pd.DataFrame({
        "event_id": ["1"],
        "st_naming_bases": ["Species／Group"],
        "st_text_span": ["2-4"],
    })
    summary, _ = compare_coders(left, right, ["st_naming_bases", "st_text_span"], schema=schema)
    by_field = summary.set_index("field")
    assert by_field.loc["st_naming_bases", "mean_jaccard"] == 0.5
    assert round(by_field.loc["st_naming_bases", "mean_set_f1"], 6) == 0.666667
    assert round(by_field.loc["st_text_span", "mean_span_iou"], 6) == 0.666667


def test_xlsx_fallback_when_openpyxl_is_missing(monkeypatch):
    data = minimal_xlsx_bytes()

    def missing_engine(*args, **kwargs):
        raise ImportError("Missing optional dependency 'openpyxl'")

    monkeypatch.setattr(pd, "ExcelFile", missing_engine)
    monkeypatch.setattr(pd, "read_excel", missing_engine)
    assert workbook_sheets(data, "items.xlsx") == ["Annotation_Items"]
    frame = read_table(data, "items.xlsx", "Annotation_Items")
    assert frame.to_dict("records") == [{"event_id": "ZN-1", "speaker": "Judy"}]
