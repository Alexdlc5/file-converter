"""Spreadsheets and data files: CSV, Excel, OpenDocument, JSON, YAML, TOML."""

import html
import json
import re
from pathlib import Path

from .engine import Converter
from .tools import ConversionError, has_module

TABLE_IN = {"csv", "tsv", "xlsx", "xlsm", "xls", "ods", "json"}
TABLE_OUT = {"csv", "tsv", "xlsx", "ods", "json", "html", "md", "txt", "pdf"}
SINGLE_TABLE = {"csv", "tsv"}  # one sheet per file; several sheets -> a folder


def _read_tables(job):
    """Returns {sheet name: DataFrame}."""
    import pandas as pd

    ext, path = job.src_ext, job.src
    if ext in ("csv", "tsv"):
        from .documents import read_text
        from io import StringIO

        text = read_text(path)
        sep = "\t" if ext == "tsv" else None  # None = detect , ; | or tab
        try:
            df = pd.read_csv(StringIO(text), sep=sep, engine="python", dtype=str,
                             keep_default_na=False)
        except Exception as exc:
            raise ConversionError(f"Couldn't read this table ({exc}).") from exc
        return {"Sheet1": _infer_numbers(df)}
    if ext in ("xlsx", "xlsm", "xls", "ods"):
        engine = {"xls": "xlrd", "ods": "odf"}.get(ext, "openpyxl")
        try:
            sheets = pd.read_excel(path, sheet_name=None, engine=engine)
        except Exception as exc:
            raise ConversionError(f"Couldn't read this spreadsheet ({exc}).") from exc
        return {name: df for name, df in sheets.items()}
    if ext == "json":
        data = _load_structured(path, "json")
        return {"Sheet1": _json_table(data)}
    raise ConversionError(f"Can't read .{ext} as a table.")


def _json_table(data):
    import pandas as pd

    if isinstance(data, list):
        if all(isinstance(row, dict) for row in data):
            return pd.json_normalize(data)
        return pd.DataFrame({"value": data})
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1 and all(isinstance(r, dict) for r in lists[0]):
            return pd.json_normalize(lists[0])  # {"items": [ {...}, ... ]}
        if data and all(isinstance(v, list) for v in data.values()) and \
                len({len(v) for v in data.values()}) == 1:
            return pd.DataFrame(data)
        return pd.json_normalize([data])
    return pd.DataFrame({"value": [data]})


def _infer_numbers(df):
    """Turn text columns that are purely numbers into numbers, but leave
    things like ZIP codes and IDs ("00501") alone."""
    import pandas as pd

    for col in df.columns:
        values = df[col][df[col] != ""]
        if values.empty:
            continue
        if values.str.match(r"^-?0\d").any():
            continue  # leading zeros matter
        converted = pd.to_numeric(values, errors="coerce")
        if converted.notna().all():
            numbers = pd.to_numeric(df[col].where(df[col] != ""), errors="coerce")
            if (converted % 1 == 0).all():
                numbers = numbers.astype("Int64")  # keep 7 as 7, not 7.0
            df[col] = numbers
    return df


def _safe_sheet_name(name, used):
    name = re.sub(r"[\[\]:*?/\\]", "_", str(name))[:31] or "Sheet"
    base, n = name, 1
    while name in used:
        name = f"{base[:28]}_{n}"
        n += 1
    used.add(name)
    return name


def _safe_file_name(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .") or "sheet"


def _autofit(path):
    from openpyxl import load_workbook

    wb = load_workbook(path)
    for ws in wb.worksheets:
        for column in ws.columns:
            width = max((len(str(c.value)) for c in column if c.value is not None), default=8)
            ws.column_dimensions[column[0].column_letter].width = min(60, max(8, width + 2))
    wb.save(path)


def _tables_html(tables):
    parts = []
    for name, df in tables.items():
        if len(tables) > 1:
            parts.append(f"<h2>{html.escape(str(name))}</h2>")
        parts.append(df.to_html(index=False, na_rep="", border=0))
    return "\n".join(parts)


class DataConverter(Converter):
    name = "tables"

    def available(self):
        return has_module("pandas")

    def targets(self, ext, path):
        if ext not in TABLE_IN:
            return set()
        out = set(TABLE_OUT)
        if ext == "xls" and not has_module("xlrd"):
            return set()
        if not has_module("odf"):
            out.discard("ods")
            if ext == "ods":
                return set()
        if not has_module("openpyxl"):
            out.discard("xlsx")
        if not has_module("tabulate"):
            out.discard("md")
        if not has_module("pymupdf"):
            out.discard("pdf")
        return out

    def convert(self, job):
        tables = _read_tables(job)
        job.check_cancel()
        t, out = job.target, job.out()

        if t in SINGLE_TABLE:
            sep = "\t" if t == "tsv" else ","
            if len(tables) == 1:
                next(iter(tables.values())).to_csv(out, sep=sep, index=False, encoding="utf-8-sig")
                return [out]
            folder = job.work_dir / f"{job.stem}_sheets"
            folder.mkdir()
            for name, df in tables.items():
                df.to_csv(folder / f"{_safe_file_name(name)}.{t}", sep=sep, index=False,
                          encoding="utf-8-sig")
            return [folder]

        if t in ("xlsx", "ods"):
            import pandas as pd

            used = set()
            with pd.ExcelWriter(out, engine="openpyxl" if t == "xlsx" else "odf") as writer:
                for name, df in tables.items():
                    df.to_excel(writer, sheet_name=_safe_sheet_name(name, used), index=False)
            if t == "xlsx":
                _autofit(out)
            return [out]

        if t == "json":
            def records(df):
                return json.loads(df.to_json(orient="records", date_format="iso", force_ascii=False))
            data = (records(next(iter(tables.values()))) if len(tables) == 1
                    else {str(n): records(df) for n, df in tables.items()})
            out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return [out]

        if t == "md":
            parts = []
            for name, df in tables.items():
                if len(tables) > 1:
                    parts.append(f"## {name}\n")
                parts.append(df.to_markdown(index=False) + "\n")
            out.write_text("\n".join(parts), encoding="utf-8")
            return [out]

        if t == "txt":
            parts = []
            for name, df in tables.items():
                if len(tables) > 1:
                    parts.append(f"== {name} ==")
                parts.append(df.to_string(index=False, na_rep="") + "\n")
            out.write_text("\n".join(parts), encoding="utf-8")
            return [out]

        if t == "html":
            page = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    f"<title>{html.escape(job.stem)}</title><style>"
                    "body{font-family:sans-serif;margin:24px} table{border-collapse:collapse}"
                    "th,td{border:1px solid #bbb;padding:4px 8px;text-align:left}"
                    "th{background:#f0f0f0}</style></head><body>"
                    f"{_tables_html(tables)}</body></html>")
            out.write_text(page, encoding="utf-8")
            return [out]

        if t == "pdf":
            from .documents import BASE_CSS, html_to_pdf

            widest = max((len(df.columns) for df in tables.values()), default=1)
            css = BASE_CSS + "body, td, th { font-size: %dpt; }" % (9 if widest <= 8 else 7)
            html_to_pdf(_tables_html(tables), out, [], job, css=css, landscape=widest > 6)
            return [out]

        raise ConversionError(f"Can't write .{t}.")


# ---- JSON / YAML / TOML --------------------------------------------------

STRUCTURED = {"json", "yaml", "toml"}


def _load_structured(path, ext):
    from .documents import read_text

    text = read_text(path)
    try:
        if ext == "json":
            return json.loads(text)
        if ext == "yaml":
            import yaml
            docs = list(yaml.safe_load_all(text))
            return docs[0] if len(docs) == 1 else docs
        if ext == "toml":
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib
            return tomllib.loads(text)
    except Exception as exc:
        raise ConversionError(f"This .{ext} file has a syntax error: {exc}") from exc
    raise ConversionError(f"Can't read .{ext}.")


def _strip_nulls(value):
    if isinstance(value, dict):
        return {k: _strip_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_nulls(v) for v in value if v is not None]
    return value


class StructuredConverter(Converter):
    name = "structured"

    def available(self):
        return True

    def targets(self, ext, path):
        if ext not in STRUCTURED:
            return set()
        out = {"json"}
        if has_module("yaml"):
            out.add("yaml")
        if has_module("tomli_w"):
            out.add("toml")
        if ext == "yaml" and not has_module("yaml"):
            return set()
        if ext == "toml" and not (has_module("tomllib") or has_module("tomli")):
            return set()
        return out

    def convert(self, job):
        data = _load_structured(job.src, job.src_ext)
        out = job.out()
        if job.target == "json":
            text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        elif job.target == "yaml":
            import yaml
            text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        else:
            import tomli_w
            if not isinstance(data, dict):
                data = {"items": data}  # TOML files must start with named keys
            # TOML has no "null"; leave those keys out.
            text = tomli_w.dumps(_strip_nulls(json.loads(json.dumps(data, default=str))))
        Path(out).write_text(text, encoding="utf-8")
        return [out]
