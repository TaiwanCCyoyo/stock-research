"""Direction-draft contract: docs/en/direction-drafts.md defines what these checks enforce.

The validator lives here because only this test reads drafts today. Move it to
``research_core/`` when a script (for example the open-question roll-up) needs it.
Drafts are read as UTF-8 text through ``pathlib``; nothing here touches market data.
"""

from __future__ import annotations

import html
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "direction_drafts"
TEMPLATE = ROOT / "docs" / "en" / "templates" / "direction-draft.md"
EXAMPLES = ROOT / "docs" / "en" / "examples"

REQUIRED_KEYS = (
    "schema",
    "task_id",
    "stage",
    "owner_purpose",
    "owner_purpose_source",
    "owner_purpose_confirmed",
    "fake_headline_approved",
    "title",
    "outcome_multiples",
    "condition_thresholds",
    "title_outcome_multiples",
    "based_on",
    "carries",
    "closes",
    "open_choices",
)
SECTION_MARKS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"
PENDING = "待確認"
PROPOSERS = {"擁有者", "Opus", "Claude", "Codex"}
LOG_RESULTS = {"採用", "放棄", "部分採用", "不承接"}
OUTCOME_TERMS = ("大漲", "飆股")
LOG_COLUMNS = ["ID", "日期", "提出者", "分岔", "結果", "理由", "來源", "待解"]
QUESTION_COLUMNS = ["ID", "問題", "提出於", "卡在哪", "關閉路徑", "狀態"]
PROMISE_COLUMNS = ["承諾", "主要／次要", "對應主格"]
DELIVERY_HEADING = "承諾 vs 交付"
DELIVERY_COLUMNS = ["承諾", "實際交付"]
CN_DIGITS = {"一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
NUM = r"(?:\d+(?:\.\d+)?|[一二兩三四五六七八九十])"
MULTIPLE_RE = re.compile(rf"(?P<body>{NUM}(?:\s*[／/、,，–~～-]\s*{NUM})*)\s*倍")
RANGE_SEP_RE = re.compile(rf"{NUM}\s*[–~～-]\s*{NUM}")
SECONDARY_BRACKET_RE = re.compile(r"[（(][^（）()]*次要[^（）()]*[）)]")
URL_RE = re.compile(r"https?://\S+")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
CONVERSATION_RE = re.compile(r"^對話 \d{4}-\d{2}-\d{2}：.+")
PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")


@dataclass(frozen=True)
class Mention:
    value: float
    start: int
    end: int


@dataclass(frozen=True)
class Draft:
    path: Path
    front: dict
    sections: dict[str, str]


def split_front_matter(text: str) -> tuple[dict, str]:
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("unterminated YAML front matter")
    loaded = yaml.safe_load(text[4:end])
    if not isinstance(loaded, dict):
        raise ValueError("front matter is not a mapping")
    return loaded, text[end + 5 :]


def load_draft(path: Path) -> Draft:
    front, body = split_front_matter(path.read_text(encoding="utf-8"))
    sections: dict[str, str] = {}
    current: str | None = None
    for line in body.splitlines():
        heading = re.match(rf"^## ([{SECTION_MARKS}])", line)
        if heading:
            mark = str(heading.group(1) or "")
            current = mark
            sections[mark] = ""
        elif line.startswith("## "):
            current = None
        elif current is not None:
            sections[current] += line + "\n"
    return Draft(path, front, sections)


def tables(section: str) -> list[tuple[list[str], list[dict[str, str]]]]:
    """Markdown tables of a section as (header, rows keyed by header)."""
    found: list[tuple[list[str], list[dict[str, str]]]] = []
    block: list[list[str]] = []

    def flush() -> None:
        if len(block) >= 2:
            header = block[0]
            rows = [dict(zip(header, row, strict=False)) for row in block[2:]]
            found.append((header, rows))
        block.clear()

    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            block.append([cell.strip() for cell in stripped.strip("|").split("|")])
        else:
            flush()
    flush()
    return found


def table_rows(section: str, columns: list[str]) -> list[dict[str, str]] | None:
    for header, rows in tables(section):
        if header[: len(columns)] == columns:
            return rows
    return None


def to_number(token: str) -> float:
    return float(CN_DIGITS[token]) if token in CN_DIGITS else float(token)


def outcome_multiples(text: str, thresholds: list[float]) -> tuple[list[Mention], list[str]]:
    """Outcome multiples promised by ``text`` (condition thresholds removed) and ambiguity errors."""
    skip = {float(value) for value in thresholds}
    mentions: list[Mention] = []
    errors: list[str] = []
    for match in MULTIPLE_RE.finditer(text):
        body = match.group("body")
        if RANGE_SEP_RE.search(body):
            errors.append(f"R1: range '{match.group(0)}' is ambiguous; list each multiple")
        for number in re.findall(NUM, body):
            value = to_number(number)
            if value not in skip:
                mentions.append(Mention(value, match.start(), match.end()))
    for match in re.finditer("翻倍", text):
        mentions.append(Mention(2.0, match.start(), match.end()))
    return mentions, errors


def secondary_spans(text: str) -> list[tuple[int, int]]:
    spans = [match.span() for match in SECONDARY_BRACKET_RE.finditer(text)]
    if re.match(r"^\s*(?:\*\*)?次要", text):
        spans.append((0, len(text)))
    return spans


def check_promised_multiples(label: str, text: str, front: dict) -> tuple[list[str], set[float]]:
    errors: list[str] = []
    thresholds = [float(v) for v in front.get("condition_thresholds") or []]
    primary = {float(v) for v in (front.get("outcome_multiples") or {}).get("primary") or []}
    secondary = {float(v) for v in (front.get("outcome_multiples") or {}).get("secondary") or []}
    mentions, ambiguity = outcome_multiples(text, thresholds)
    errors.extend(f"{label}: {message}" for message in ambiguity)
    spans = secondary_spans(text)
    for mention in mentions:
        if mention.value in primary:
            continue
        marked = any(start <= mention.start and mention.end <= end for start, end in spans)
        if not marked:
            errors.append(f"R3: {label} promises {mention.value:g} 倍, not a primary multiple, outside a 次要 bracket")
        elif mention.value not in secondary:
            errors.append(f"R3: {label} marks {mention.value:g} 倍 次要 but outcome_multiples.secondary does not declare it")
    return errors, {mention.value for mention in mentions}


def headline_lines(section: str) -> list[str]:
    return [line.strip()[1:].strip() for line in section.splitlines() if line.strip().startswith(">")]


def has_url(value: object) -> bool:
    return isinstance(value, str) and URL_RE.search(value) is not None


def draft_path(root: Path, task_id: str) -> Path | None:
    for candidate in (
        root / "tasks" / task_id / "direction-draft.md",
        root / "docs" / "en" / "examples" / f"direction-draft-{task_id}.md",
    ):
        if candidate.is_file():
            return candidate
    return None


def own_questions(draft: Draft) -> list[dict[str, str]]:
    return table_rows(draft.sections.get("⑫", ""), QUESTION_COLUMNS) or []


def split_reference(reference: str) -> tuple[str, str]:
    task_id, _, question = reference.partition("#")
    return task_id, question


def check_structure(draft: Draft) -> list[str]:
    errors = [f"FIELD: front matter lacks '{key}'" for key in REQUIRED_KEYS if key not in draft.front]
    errors.extend(f"SECTION: heading {mark} is missing" for mark in SECTION_MARKS if mark not in draft.sections)
    if draft.front.get("schema") != "direction-draft.v1":
        errors.append("FIELD: schema must be direction-draft.v1")
    if draft.front.get("stage") not in {"discussing", "agreed"}:
        errors.append("FIELD: stage must be discussing or agreed")
    first = draft.sections.get("①", "")
    branches = {row.get("若答案…", "") for _, rows in tables(first) for row in rows}
    for word in ("成立", "不成立", "分不出來"):
        if not any(branch.startswith(word) for branch in branches):
            errors.append(f"PURPOSE: ① lacks a decision row for '{word}'")
    steps = [rows for header, rows in tables(first) if header and header[0] == "步驟"]
    if not (steps and steps[0]) and "0 步" not in first:
        errors.append("PURPOSE: ① needs a 步驟 table with a row, or '0 步' with a reason")
    if "起點 100 元" not in draft.sections.get("④", ""):
        errors.append("LEGEND: ④ must keep the fixed condition-versus-outcome legend (起點 100 元)")
    return errors


def check_log_and_questions(draft: Draft) -> list[str]:
    errors: list[str] = []
    agreed = draft.front.get("stage") == "agreed"
    questions = own_questions(draft)
    question_ids = [row["ID"] for row in questions]
    if not questions and "無" not in draft.sections.get("⑫", ""):
        errors.append("QUESTION: ⑫ needs a question table or '無' with a reason")
    if len(question_ids) != len(set(question_ids)):
        errors.append("QUESTION: duplicate question ID in ⑫")
    for row in questions:
        for column in ("卡在哪", "關閉路徑"):
            if not row.get(column, "").strip():
                errors.append(f"QUESTION: {row['ID']} has an empty {column}")
    log = table_rows(draft.sections.get("⑪", ""), LOG_COLUMNS)
    if not log:
        return [*errors, "LOG: ⑪ needs at least one row"]
    ids = [row["ID"] for row in log]
    if len(ids) != len(set(ids)):
        errors.append("LOG: duplicate row ID in ⑪")
    for row in log:
        name = row["ID"]
        for column in ("分岔", "理由"):
            if not row.get(column, "").strip():
                errors.append(f"LOG-REASON: {name} has an empty {column}")
        if row.get("理由", "").strip() == PENDING:
            errors.append(f"LOG-REASON: {name} reason may not be {PENDING}")
        if row.get("結果") not in LOG_RESULTS:
            errors.append(f"LOG: {name} result must be one of {sorted(LOG_RESULTS)}")
        date, proposer, source = row.get("日期", ""), row.get("提出者", ""), row.get("來源", "")
        ok_source = has_url(source) or CONVERSATION_RE.match(source) or re.match(r"^repo:\s*\S+", source)
        for column, valid in (
            ("日期", DATE_RE.match(date)),
            ("提出者", proposer in PROPOSERS),
            ("來源", ok_source),
        ):
            value = row.get(column, "")
            if value == PENDING:
                if agreed:
                    errors.append(f"LOG-PENDING: {name} {column} is {PENDING} but stage is agreed")
            elif not valid:
                errors.append(f"LOG: {name} has an invalid {column} '{value}'")
        link = row.get("待解", "").strip()
        if link not in {"否", ""} and link not in question_ids:
            errors.append(f"LOG: {name} points to {link}, which ⑫ does not define")
    return errors


def check_promises(draft: Draft) -> list[str]:
    rows = table_rows(draft.sections.get("⑩", ""), PROMISE_COLUMNS)
    if not rows:
        return ["PROMISE: ⑩ needs a 承諾 vs 交付 table"]
    errors: list[str] = []
    if not any(row["主要／次要"].replace("*", "") == "主要" for row in rows):
        errors.append("PROMISE: ⑩ needs at least one 主要 row")
    for row in rows:
        kind = row["主要／次要"].replace("*", "")
        if kind not in {"主要", "次要"}:
            errors.append(f"R4: ⑩ row '{row['承諾']}' must be 主要 or 次要")
        elif kind == "主要" and (not row["對應主格"].strip() or row["對應主格"].startswith("不對應")):
            errors.append(f"R4: ⑩ primary row '{row['承諾']}' has no 對應主格")
    return errors


def check_gate(draft: Draft) -> list[str]:
    errors: list[str] = []
    headlines = headline_lines(draft.sections.get("②", ""))
    if not headlines:
        errors.append("HEADLINE: ② needs headline lines starting with '>'")
    if headlines and not any("▢" in line for line in headlines):
        errors.append("HEADLINE: ② headlines must use ▢ placeholders")
    errors.extend(f"HEADLINE: ② headline shows a real percentage: {line}" for line in headlines if PERCENT_RE.search(line))
    if draft.front.get("stage") != "agreed":
        return errors
    for key in ("owner_purpose_confirmed", "fake_headline_approved"):
        if not has_url(draft.front.get(key)):
            errors.append(f"GATE: stage is agreed but {key} is not a link")
    if PENDING in str(draft.front.get("owner_purpose", "")):
        errors.append("GATE: stage is agreed but owner_purpose is still pending")
    section = draft.sections.get("⑧", "")
    for choice in draft.front.get("open_choices") or []:
        line = next((ln for ln in section.splitlines() if re.search(rf"\b{re.escape(str(choice))}\b", ln) and "- [" in ln), None)
        if line is None or not line.lstrip().startswith("- [x]") or not has_url(line):
            errors.append(f"GATE: stage is agreed but ⑧ choice {choice} is not ticked with a source link")
    return errors


def check_multiples(draft: Draft) -> list[str]:
    errors: list[str] = []
    front = draft.front
    title_errors, found = check_promised_multiples("title", str(front.get("title", "")), front)
    errors.extend(title_errors)
    declared = {float(v) for v in front.get("title_outcome_multiples") or []}
    if found != declared:
        errors.append(f"R2: title promises {sorted(found)} but title_outcome_multiples declares {sorted(declared)}")
    allowed = {float(v) for key in ("primary", "secondary") for v in (front.get("outcome_multiples") or {}).get(key) or []}
    if not declared <= allowed:
        errors.append("R2: title_outcome_multiples is not covered by outcome_multiples")
    for line in headline_lines(draft.sections.get("②", "")):
        errors.extend(check_promised_multiples("headline", line, front)[0])
    texts = [str(front.get("title", ""))]
    study = draft.path.parent / "study.json"
    if draft.path.name == "direction-draft.md" and study.is_file():
        card = json.loads(study.read_text(encoding="utf-8"))
        for key in ("question", "answer"):
            errors.extend(check_promised_multiples(f"study.json {key}", str(card.get(key, "")), front)[0])
            texts.append(str(card.get(key, "")))
    terms = front.get("title_outcome_terms") or {}
    for term in OUTCOME_TERMS:
        if any(term in text for text in texts) and not str(terms.get(term, "")).strip():
            errors.append(f"R1b: '{term}' is used but title_outcome_terms does not define it")
    return errors


def check_predecessors(draft: Draft, root: Path) -> list[str]:
    errors: list[str] = []
    front = draft.front
    for entry in front.get("based_on") or []:
        task_id = (entry or {}).get("task_id", "")
        if not task_id or not (root / "tasks" / task_id).is_dir():
            errors.append(f"PRIOR: based_on task '{task_id}' does not exist")
    carried = {str(r) for r in (front.get("carries") or []) + (front.get("closes") or [])}
    for reference in sorted(carried):
        task_id, question = split_reference(reference)
        if not (root / "tasks" / task_id).is_dir():
            errors.append(f"PRIOR: {reference} points to a task that does not exist")
            continue
        prior = draft_path(root, task_id)
        if prior is None:
            errors.append(f"PRIOR: {reference} has no direction draft; copy the question into this draft's ⑫ instead")
        elif question not in {row["ID"] for row in own_questions(load_draft(prior))}:
            errors.append(f"PRIOR: {reference} is not in the predecessor's ⑫")
    declined = " ".join(row.get("分岔", "") for row in table_rows(draft.sections.get("⑪", ""), LOG_COLUMNS) or [] if row.get("結果") == "不承接")
    for entry in front.get("based_on") or []:
        task_id = (entry or {}).get("task_id", "")
        prior = draft_path(root, task_id) if task_id else None
        if prior is None:
            continue
        for row in own_questions(load_draft(prior)):
            if not row["狀態"].startswith(("open", "carried")):
                continue
            key = row["ID"] if "#" in row["ID"] else f"{task_id}#{row['ID']}"
            if key not in carried and key not in declined:
                errors.append(f"ORPHAN: predecessor question {key} is neither carried, closed nor declined in ⑪")
    return errors


def visible_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return text


def report_section(text: str, heading: str) -> str | None:
    """Body of the ``## <heading>`` section of a report, or None when it is absent."""
    lines: list[str] | None = None
    for line in text.replace("\r\n", "\n").splitlines():
        if line.startswith("## "):
            if lines is not None:
                break
            lines = [] if line[3:].strip() == heading else None
        elif lines is not None:
            lines.append(line)
    return None if lines is None else "\n".join(lines)


def check_closeout(draft: Draft) -> list[str]:
    """R5: the frozen draft keeps promises only; ``report.md`` carries the delivery comparison."""
    folder = draft.path.parent
    report = folder / "report.md"
    if draft.path.name != "direction-draft.md" or draft.front.get("stage") != "agreed" or not report.is_file():
        return []
    errors: list[str] = []
    marker = f"擁有者原話目的：{draft.front.get('owner_purpose')}"
    for target in (report, folder / "web-report" / "index.html"):
        if not target.is_file():
            errors.append(f"R5: {target.name} is missing")
        elif marker not in visible_text(target):
            errors.append(f"R5: {target.name} lacks the verbatim owner purpose line")
    if any("實際交付" in header for header, _ in tables(draft.sections.get("⑩", ""))[0:1]):
        errors.append("R5: the frozen draft must not carry 實際交付; write it in report.md")
    section = report_section(report.read_text(encoding="utf-8"), DELIVERY_HEADING)
    delivered = table_rows(section, DELIVERY_COLUMNS) if section is not None else None
    if delivered is None:
        return [*errors, f"R5: report.md lacks a '## {DELIVERY_HEADING}' table with columns {DELIVERY_COLUMNS}"]
    by_promise = {row["承諾"]: row.get("實際交付", "").strip() for row in delivered}
    for row in table_rows(draft.sections.get("⑩", ""), PROMISE_COLUMNS) or []:
        if row["承諾"] not in by_promise:
            errors.append(f"R5: report.md '{DELIVERY_HEADING}' has no row for promise '{row['承諾']}'")
        elif not by_promise[row["承諾"]]:
            errors.append(f"R5: report.md '{DELIVERY_HEADING}' row '{row['承諾']}' has an empty 實際交付")
    return errors


def validate_draft(path: Path, root: Path = ROOT) -> list[str]:
    draft = load_draft(path)
    errors = check_structure(draft)
    if errors and any(error.startswith(("FIELD", "SECTION")) for error in errors):
        return errors
    for check in (check_log_and_questions, check_promises, check_gate, check_multiples, check_closeout):
        errors.extend(check(draft))
    errors.extend(check_predecessors(draft, root))
    return errors


def repo_drafts() -> list[Path]:
    return sorted((ROOT / "tasks").glob("*/direction-draft.md")) + sorted(EXAMPLES.glob("direction-draft-*.md"))


def codes(errors: list[str]) -> set[str]:
    return {error.split(":", 1)[0] for error in errors}


def test_template_has_every_field_and_section() -> None:
    draft = load_draft(TEMPLATE)
    assert [e for e in check_structure(draft) if not e.startswith("PURPOSE")] == []
    assert table_rows(draft.sections["⑩"], PROMISE_COLUMNS) is not None
    assert table_rows(draft.sections["⑪"], LOG_COLUMNS) is not None
    assert table_rows(draft.sections["⑫"], QUESTION_COLUMNS) is not None
    assert draft.front["stage"] == "discussing"


@pytest.mark.parametrize("path", repo_drafts(), ids=lambda p: p.parent.name if p.name == "direction-draft.md" else p.stem)
def test_repository_drafts_satisfy_the_contract(path: Path) -> None:
    assert validate_draft(path) == []
    assert load_draft(path).front["task_id"] in path.as_posix()


def test_documented_examples_exist() -> None:
    assert {p.name for p in EXAMPLES.glob("direction-draft-*.md")} >= {
        "direction-draft-20261021-momentum-only-doubling.md",
        "direction-draft-20261024-strength-weakening-flags.md",
    }


FIXTURE_EXPECTATIONS = {
    "ok-minimal": set(),
    "pr113-title-overpromise": {"R3"},
    "log-missing-reason": {"LOG-REASON"},
    "agreed-without-approval": {"GATE"},
    "fake-headline-has-digits": {"HEADLINE"},
    "orphaned-predecessor-question": {"ORPHAN"},
}


@pytest.mark.parametrize("case", sorted(FIXTURE_EXPECTATIONS))
def test_fixture_outcomes(case: str) -> None:
    root = FIXTURES / case
    assert root.is_dir()
    target = root / "tasks" / f"20261101-{case}" / "direction-draft.md"
    assert target.is_file()
    errors = validate_draft(target, root)
    if FIXTURE_EXPECTATIONS[case]:
        assert FIXTURE_EXPECTATIONS[case] <= codes(errors), errors
    else:
        assert errors == []


def test_pr113_title_is_caught_and_its_fix_passes() -> None:
    root = FIXTURES / "pr113-title-overpromise"
    path = root / "tasks" / "20261101-pr113-title-overpromise" / "direction-draft.md"
    assert any(e.startswith("R3") and "10" in e for e in validate_draft(path, root))
    fixed = path.read_text(encoding="utf-8").replace("哪些轉弱訊號讓 2／3／5／10 倍機率下降？", "哪些轉弱訊號讓 2 倍機率下降？（另附 3／5／10 倍，次要）")
    assert fixed != path.read_text(encoding="utf-8")
    copy = path.with_name("fixed.md")
    try:
        copy.write_text(fixed, encoding="utf-8")
        assert validate_draft(copy, root) == []
    finally:
        copy.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("讓 2／3／5／10 倍機率下降", {2.0, 3.0, 5.0, 10.0}),
        ("2、3 倍與 5 倍", {2.0, 3.0, 5.0}),
        ("能解釋多少翻倍與大漲機率", {2.0}),
        ("三倍與十倍", {3.0, 10.0}),
        ("條件門檻 1.6 倍且 2.5 倍，結果目標 2 倍", {2.0}),
        ("沒有倍數", set()),
    ],
)
def test_multiple_extraction(text: str, expected: set[float]) -> None:
    mentions, errors = outcome_multiples(text, [1.6, 2.5])
    assert {m.value for m in mentions} == expected
    assert errors == []


def test_range_is_ambiguous() -> None:
    assert outcome_multiples("2–10 倍", [])[1]


def test_secondary_must_share_the_bracket() -> None:
    front = {"outcome_multiples": {"primary": [2], "secondary": [3, 5]}, "condition_thresholds": []}
    assert check_promised_multiples("t", "讓 2 倍下降（另附 3／5 倍，次要）", front)[0] == []
    assert check_promised_multiples("t", "讓 2 倍下降，另附 3／5 倍，次要", front)[0]
    assert check_promised_multiples("t", "讓 2 倍下降（另附 3／10 倍，次要）", front)[0]
    assert check_promised_multiples("h", "次要（附表）：3／5 倍不構成結論", front)[0] == []


def test_undefined_outcome_term_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(FIXTURES / "ok-minimal", root)
    draft = root / "tasks" / "20261101-ok-minimal" / "direction-draft.md"
    text = draft.read_text(encoding="utf-8")
    flagged = text.replace('title: "強勢條件成立後', 'title: "強勢條件成立後的大漲', 1)
    assert flagged != text
    draft.write_text(flagged, encoding="utf-8")
    assert "R1b" in codes(validate_draft(draft, root))
    defined = flagged.replace("title_outcome_multiples:", "title_outcome_terms: {大漲: 一年內最高收盤達起點 1.5 倍以上}\ntitle_outcome_multiples:", 1)
    draft.write_text(defined, encoding="utf-8")
    assert "R1b" not in codes(validate_draft(draft, root))


def agreed_copy(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "root"
    shutil.copytree(FIXTURES / "agreed-without-approval", root)
    folder = root / "tasks" / "20261101-agreed-without-approval"
    draft = folder / "direction-draft.md"
    text = draft.read_text(encoding="utf-8")
    text = re.sub(r"^owner_purpose_confirmed:.*$", "owner_purpose_confirmed: https://example.invalid/pull/1#c1", text, flags=re.M)
    text = re.sub(r"^fake_headline_approved:.*$", "fake_headline_approved: https://example.invalid/pull/1#c2", text, flags=re.M)
    draft.write_text(text, encoding="utf-8")
    assert validate_draft(draft, root) == []
    return root, draft, load_draft(draft).front


def write_report(folder: Path, front: dict, delivery: str | None, *, web: bool = True) -> None:
    purpose = front["owner_purpose"]
    body = f"報告\n\n擁有者原話目的：{purpose}\n"
    if delivery is not None:
        body += f"\n## {DELIVERY_HEADING}\n\n{delivery}\n"
    (folder / "report.md").write_text(body, encoding="utf-8")
    if web:
        (folder / "web-report").mkdir(exist_ok=True)
        (folder / "web-report" / "index.html").write_text(f"<p>擁有者原話目的：{html.escape(purpose)}</p>", encoding="utf-8")


def delivery_table(draft: Path, *, drop: int | None = None, blank: int | None = None) -> str:
    promises = [row["承諾"] for row in table_rows(load_draft(draft).sections["⑩"], PROMISE_COLUMNS) or []]
    lines = ["| 承諾 | 實際交付 |", "| --- | --- |"]
    for index, promise in enumerate(promises):
        if index != drop:
            lines.append(f"| {promise} | {'' if index == blank else '已交付'} |")
    return "\n".join(lines)


def test_closeout_requires_verbatim_purpose(tmp_path: Path) -> None:
    root, draft, front = agreed_copy(tmp_path)
    folder = draft.parent
    (folder / "report.md").write_text("報告\n", encoding="utf-8")
    assert "R5" in codes(validate_draft(draft, root))
    write_report(folder, front, delivery_table(draft))
    assert validate_draft(draft, root) == []


def test_closeout_passes_only_with_frozen_draft_and_complete_report_section(tmp_path: Path) -> None:
    root, draft, front = agreed_copy(tmp_path)
    frozen = draft.read_text(encoding="utf-8")
    write_report(draft.parent, front, delivery_table(draft))
    assert validate_draft(draft, root) == []
    assert draft.read_text(encoding="utf-8") == frozen
    assert "實際交付" not in frozen


def test_closeout_fails_without_delivery_section_or_rows(tmp_path: Path) -> None:
    root, draft, front = agreed_copy(tmp_path)
    folder = draft.parent
    write_report(folder, front, None)
    assert any("lacks" in e for e in validate_draft(draft, root))
    write_report(folder, front, delivery_table(draft, drop=0))
    assert any("has no row for promise" in e for e in validate_draft(draft, root))
    write_report(folder, front, delivery_table(draft, blank=0))
    assert any("empty 實際交付" in e for e in validate_draft(draft, root))
    (folder / "web-report" / "index.html").unlink()
    write_report(folder, front, delivery_table(draft), web=False)
    assert any("index.html is missing" in e for e in validate_draft(draft, root))


def test_closeout_rejects_delivery_column_inside_frozen_draft(tmp_path: Path) -> None:
    root, draft, front = agreed_copy(tmp_path)
    write_report(draft.parent, front, delivery_table(draft))
    text = draft.read_text(encoding="utf-8")
    head, mark, tail = text.partition("## ⑩")
    edited = head + mark + re.sub(r"對應主格\s*\|", "對應主格 | 實際交付 |", tail, count=1)
    assert edited != text
    draft.write_text(edited, encoding="utf-8")
    assert any("frozen draft" in e for e in validate_draft(draft, root))


def test_fixture_drafts_are_text_files_without_python_modules() -> None:
    assert not list(FIXTURES.rglob("*.py"))
