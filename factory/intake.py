"""Read-only architect intake. Source documents are data, never instructions.
`needs_clarification` is a success outcome."""
from __future__ import annotations

import hashlib
import json
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import engines, state
from .evidence import now, sha256_text, write_result
from .models import ConfigError
from .process import run_process
from .workspace import git

QUESTION = {"type": "object",
            "properties": {"id": {"type": "string"}, "question": {"type": "string"},
                           "rationale": {"type": "string"}, "blocking": {"type": "boolean"},
                           "source_excerpt": {"type": "string"}},
            "required": ["id", "question", "rationale", "blocking", "source_excerpt"],
            "additionalProperties": False}
INTAKE_SCHEMA = {"type": "object",
                 "properties": {"decision": {"type": "string",
                                             "enum": ["needs_clarification", "ready_for_planning"]},
                                "questions": {"type": "array", "items": QUESTION},
                                "assumptions": {"type": "array", "items": {"type": "string"}}},
                 "required": ["decision", "questions", "assumptions"], "additionalProperties": False}
PROMPT = (Path(__file__).parent / "prompts" / "intake.md")


def extract_source(source: Path) -> str:
    ext = source.suffix.lower()
    if ext == ".docx":
        with zipfile.ZipFile(source) as z:
            root = ET.fromstring(z.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return "\n".join("".join(t.text or "" for t in p.findall(".//w:t", ns))
                         for p in root.findall(".//w:p", ns))
    if ext not in (".md", ".txt"):
        raise ValueError("intake supports .docx, .md and .txt sources")
    return source.read_text()


def _req(d, keys, what):
    if not isinstance(d, dict) or set(d) != set(keys):
        raise ValueError(f"invalid {what}: expected exactly keys {sorted(keys)}")


def _ne(v, what):
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{what} must be a non-empty string")


def validate_report(report: dict) -> None:
    _req(report, ("decision", "questions", "assumptions"), "architect report")
    if report["decision"] not in ("needs_clarification", "ready_for_planning") \
            or not isinstance(report["questions"], list) or not isinstance(report["assumptions"], list):
        raise ValueError("invalid architect report")
    ids = set()
    for q in report["questions"]:
        _req(q, QUESTION["required"], "question")
        for k in ("id", "question", "rationale", "source_excerpt"):
            _ne(q[k], f"question.{k}")
        if q["id"] in ids or not isinstance(q["blocking"], bool):
            raise ValueError("duplicate question id or non-boolean blocking")
        ids.add(q["id"])
    for a in report["assumptions"]:
        _ne(a, "assumption")
    if (report["decision"] == "needs_clarification") != any(q["blocking"] for q in report["questions"]):
        raise ValueError("decision contradicts blocking questions")


def _load_report(engine: str, last: Path, info: dict, log: Path) -> dict:
    if info.get("structured_output") is not None:
        return info["structured_output"]
    text = last.read_text() if last.exists() else (info.get("final") or log.read_text(errors="replace"))
    dec = json.JSONDecoder()
    idx = 0
    while True:
        pos = text.find("{", idx)
        if pos < 0:
            break
        try:
            obj, end = dec.raw_decode(text, pos)
            if isinstance(obj, dict) and "decision" in obj:
                return obj
            idx = end
        except json.JSONDecodeError:
            idx = pos + 1
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def run_intake(source: Path, engine: str, *, timeout_s: int = 1200, cfg: dict | None = None,
               base_dir: Path | None = None) -> dict:
    source = Path(source)
    content = extract_source(source)
    _ne(content, "source document")
    run_id = f"intake-{uuid.uuid4().hex[:8]}"
    run_dir = (base_dir or state.home() / "intake") / run_id
    ws = run_dir / "workspace"
    ws.mkdir(parents=True)
    (ws / "intake.txt").write_text(content)
    git(ws, "init", "-q", "-b", "intake")
    prompt = PROMPT.read_text()
    result = {"schema_version": 1, "run_id": run_id, "status": "running", "engine": engine,
              "run_dir": str(run_dir), "workspace": str(ws), "source_name": source.name,
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "extracted_sha256": sha256_text(content), "started": now()}
    write_result(run_dir, result)
    try:
        pf = run_dir / "prompt.md"
        pf.write_text(prompt)
        inv = engines.build_invocation(engine, role="intake", worktree=ws, prompt=prompt,
                                       prompt_file=pf, run_dir=run_dir, cfg=cfg or {"engines": {}},
                                       frozen=[], read_only=True, schema=INTAKE_SCHEMA)
        log = run_dir / "architect.log"
        p = run_process(inv.argv, ws, timeout_s, log, inv.stdin_text, inv.env)
        result["process"] = p.to_dict()
        if p.timed_out:
            result["status"] = "timed_out"
        elif p.returncode:
            result.update(status="failed", reason=f"{engine} intake process failed (rc={p.returncode}); see {log}")
        else:
            info = engines.parse_output(engine, log, inv.last_message)
            report = _load_report(engine, inv.last_message, info, log)
            validate_report(report)
            paths = sorted(f.relative_to(ws).as_posix() for f in ws.rglob("*")
                           if ".git" not in f.relative_to(ws).parts and f.is_file())
            if paths != ["intake.txt"] or (ws / "intake.txt").read_text() != content:
                raise ValueError("architect modified the intake workspace (read-only violated)")
            if git(ws, "status", "--porcelain").strip() not in ("?? intake.txt",):
                raise ValueError("architect modified the intake workspace (read-only violated)")
            result.update(status=report["decision"], report=report)
    except KeyboardInterrupt:
        result["status"] = "interrupted"
    except Exception as e:
        result.update(status="failed", reason=f"{type(e).__name__}: {e}")
    result["finished"] = now()
    write_result(run_dir, result)
    return result
