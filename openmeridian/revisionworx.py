"""RevisionWorx: engineering's controlled record. OpenMeridian reads it, and writes one thing: the units its own work
orders built, registered in RevisionWorx's unit register (the Director's decision, 2026-11-07). Nothing else.

Everything goes through RevisionWorx's public command line (`--json`, and `link` for units), so its rules, locks and
integrity checks hold. Items link to controlled documents, work orders record the released revision being built, BOMs are
imported from a released revision by RevisionWorx's own validated BOM reader, and open engineering changes are shown
where they matter.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

from .values import parse_qty

TIMEOUT = 45
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform.startswith("win") else {}


class RevisionWorxError(RuntimeError):
    """RevisionWorx couldn't answer. The message is its own, or says what to do. ``kind`` is RevisionWorx's own word for
    why its ``link`` command refused (``duplicate``, ``txid-used``, ``conflict``, ``busy``...; its docs/INTEGRATION.md),
    or empty."""

    def __init__(self, message: str = "", kind: str = ""):
        super().__init__(message)
        self.kind = kind


def is_workspace(folder: str) -> bool:
    return bool(folder) and os.path.isdir(os.path.join(folder, ".revisionworx"))


def find_cli(configured: str = "") -> list[str] | None:
    for c in (configured, os.environ.get("OPENMERIDIAN_REVISIONWORX", "")):
        if c and (os.path.isfile(c) or shutil.which(c)):
            return [c]
    w = shutil.which("revisionworx")
    if w:
        return [w]
    if not getattr(sys, "frozen", False):
        try:
            if importlib.util.find_spec("revisionworx") is not None:
                return [sys.executable, "-m", "revisionworx"]
        except (ImportError, ValueError):
            pass
    return None


def find_gui(configured: str = "") -> list[str] | None:
    w = shutil.which("revisionworx-gui")
    if w:
        return [w]
    if not getattr(sys, "frozen", False):
        try:
            if importlib.util.find_spec("revisionworx") is not None:
                return [sys.executable, "-m", "revisionworx.gui.app"]
        except (ImportError, ValueError):
            pass
    return None


def child_environment() -> dict:
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        for k in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            env.pop(k, None)
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig is not None:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


@dataclass
class Document:
    id: str
    number: str
    title: str
    rel_path: str
    type_id: str
    latest_label: str
    latest_state: str
    released_label: str
    checked_out_by: str
    project_id: str = ""


@dataclass
class Revision:
    id: str
    label: str
    state: str
    sha256: str
    description: str


@dataclass
class DocumentDetail:
    document: Document
    path: str
    file_state: str
    history: list = field(default_factory=list)     # newest first
    released: Revision | None = None

    def state_sentence(self) -> str:
        if self.released:
            return f"Released: Rev {self.released.label}"
        return f"Nothing released yet. Latest is Rev {self.document.latest_label or '?'} ({self.document.latest_state or 'no state'})"


@dataclass
class Change:
    id: str
    number: str
    kind: str
    title: str
    status: str


class Client:
    def __init__(self, workspace: str, cli: list[str] | None = None, configured: str = ""):
        self.workspace = workspace
        self.cmd = cli if cli is not None else find_cli(configured)

    @property
    def available(self) -> bool:
        return self.cmd is not None and is_workspace(self.workspace)

    def _run(self, *args, as_json=True, workspace_flag=True):
        if self.cmd is None:
            raise RevisionWorxError("RevisionWorx isn't installed, or OpenMeridian can't find it. Set its location in Settings.")
        if not is_workspace(self.workspace):
            raise RevisionWorxError(f"{self.workspace} is not a RevisionWorx workspace.")
        cmd = [*self.cmd]
        if as_json:
            cmd.append("--json")
        if workspace_flag:
            cmd += ["-w", self.workspace]
        try:
            r = subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=TIMEOUT, check=False, encoding="utf-8",
                               errors="replace", env=child_environment(), stdin=subprocess.DEVNULL, **_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RevisionWorxError(f"RevisionWorx could not be run: {e}") from e
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip()
            raise RevisionWorxError(msg[7:] if msg.startswith("error: ") else (msg or f"RevisionWorx exited with code {r.returncode}."))
        if not as_json:
            return r.stdout
        try:
            return json.loads(r.stdout) if r.stdout.strip() else None
        except ValueError as e:
            raise RevisionWorxError("RevisionWorx returned something OpenMeridian could not read.") from e

    def documents(self, text: str = "") -> list[Document]:
        args = ["doc", "list", "--limit", "5000"] + ([text] if text else [])
        out = []
        for d in self._run(*args) or []:
            out.append(Document(d["id"], d.get("number") or "", d.get("title") or "", d.get("rel_path") or "", d.get("type_id") or "",
                                d.get("latest_label") or "", d.get("latest_state") or "", d.get("released_label") or "",
                                d.get("checked_out_by") or "", d.get("project_id") or ""))
        return out

    def detail(self, doc_id: str) -> DocumentDetail:
        s = self._run("doc", "show", doc_id)
        d, status = s["document"], s.get("status") or {}
        revs = [Revision(r["id"], r.get("label", ""), r.get("state", ""), r.get("sha256", ""), r.get("description", ""))
                for r in s.get("history") or []]
        by_id = {r.id: r for r in revs}
        latest = by_id.get(d.get("latest_rev_id"))
        released = by_id.get(d.get("released_rev_id"))
        doc = Document(d["id"], d.get("number") or "", d.get("title") or "", d.get("rel_path") or "", d.get("type_id") or "",
                       latest.label if latest else "", latest.state if latest else "", released.label if released else "",
                       ((s.get("checkout") or {}).get("owner") or {}).get("user", ""), d.get("project_id") or "")
        return DocumentDetail(doc, status.get("path", ""), status.get("state", ""), revs, released)

    def changes(self, open_only: bool = True) -> list[Change]:
        """Engineering changes (ECRs and ECOs), newest first as RevisionWorx lists them."""
        args = ["change", "list", "--json"] + (["--open"] if open_only else [])
        text = self._run(*args, as_json=False, workspace_flag=True)
        try:
            data = json.loads(text) if text.strip() else []
        except ValueError as e:
            raise RevisionWorxError("RevisionWorx returned something OpenMeridian could not read.") from e
        rows = data.get("rows", []) if isinstance(data, dict) else data
        return [Change(c.get("id", ""), c.get("number", ""), c.get("kind", ""), c.get("title", ""), c.get("status") or c.get("state", ""))
                for c in rows or []]

    def _link(self, *args) -> dict:
        """``revisionworx -w WORKSPACE link ...``: one JSON object back, ``ok`` or not, whatever the exit code."""
        if self.cmd is None:
            raise RevisionWorxError("RevisionWorx isn't installed, or OpenMeridian can't find it. Set its location in Settings.")
        if not is_workspace(self.workspace):
            raise RevisionWorxError(f"{self.workspace} is not a RevisionWorx workspace.")
        try:
            r = subprocess.run([*self.cmd, "-w", self.workspace, "link", *args], capture_output=True, text=True,
                               timeout=TIMEOUT, check=False, encoding="utf-8", errors="replace", env=child_environment(),
                               stdin=subprocess.DEVNULL, **_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RevisionWorxError(f"RevisionWorx could not be run: {e}") from e
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        try:
            data = json.loads(lines[-1]) if lines else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise RevisionWorxError((r.stderr or r.stdout).strip() or f"RevisionWorx exited with code {r.returncode}.")
        if not data.get("ok"):
            raise RevisionWorxError(str(data.get("error") or "RevisionWorx refused."), str(data.get("kind") or ""))
        return data

    def has(self, feature: str) -> bool:
        """True when this RevisionWorx announces ``feature`` (``link version``). Ask before using a newer command."""
        if not hasattr(self, "_features"):
            self._features = set(self._link("version").get("features") or [])
        return feature in self._features

    def units(self) -> list[dict]:
        """Every unit in the unit register, as summaries: id, label, status, customer, site, location, identifiers."""
        if not self.has("units"):
            raise RevisionWorxError("This RevisionWorx has no unit register. Update it (1.0.0 or later).")
        return [u for u in self._link("units").get("units") or [] if isinstance(u, dict) and isinstance(u.get("id"), str)]

    def where_used(self, part_number: str, lot: str = "", history: bool = True) -> list[dict]:
        """Units RevisionWorx records ``lot`` of ``part_number`` fitted in, now or (``history``) ever, each with the unit's
        summary (``link where-used``, feature unit-where-used). Read-only."""
        args = ["where-used", f"--part-number={part_number}"] + ([f"--lot={lot}"] if lot else [])
        return [r for r in self._link(*args, *(["--history"] if history else [])).get("rows") or []
                if isinstance(r, dict) and isinstance(r.get("unit"), dict)]

    def register_units(self, txid: str, serials: list[str], *, model: str, name: str, built: str, document: str = "",
                       evidence: str = "", lots: list[dict] | None = None) -> list[tuple[str, str]]:
        """Register units a work order built in RevisionWorx's unit register, all of them or none (``link unit-register``).
        ``txid`` is the same for every attempt at one completion, so RevisionWorx records them once however often it is
        asked. ``document`` is the revision they were built to, ``DOC@REV`` (ids). The serials are this organization's
        (no issuer). ``lots`` are the lots the completion used, ``[{number, lot, quantity}]``: each unit records them in
        the same entry (feature ``unit-lots``). Returns (serial, RevisionWorx unit id) pairs for the units it lists."""
        features = self._link("version").get("features") or []
        if "unit-records" not in features:
            raise RevisionWorxError("This RevisionWorx can't register units. Update it (1.0.0 or later).")
        if lots and "unit-lots" not in features:
            raise RevisionWorxError("This RevisionWorx can't record the lots the units were built from, so they weren't "
                                    "registered. Update it (1.0.0 or later).")
        # --option=value throughout, so a value starting with "-" (a serial like -0042, say) stays a value
        args = ["unit-register", f"--txid={txid}", f"--model={model}", "--status=built", f"--built={built}"]
        args += [f"--serial={sn}" for sn in serials]
        if name:
            args.append(f"--name={name}")
        if document:
            args.append(f"--doc={document}")
        if evidence:
            args.append(f"--evidence={evidence}")
        with tempfile.TemporaryDirectory(prefix="openmeridian-") as d:
            if lots:                                 # a file: a completion's lots can be longer than a command line
                path = os.path.join(d, "lots.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(lots, f, ensure_ascii=False)
                args.append(f"--lots-file={path}")
            answer = self._link(*args)
        out = []
        for u in answer.get("units") or []:
            if not isinstance(u, dict) or not isinstance(u.get("id"), str):
                continue
            for i in u.get("identifiers") or []:
                if (isinstance(i, dict) and i.get("scheme") == "serial" and not i.get("issuer")
                        and isinstance(i.get("value"), str)):
                    out.append((i["value"], u["id"]))
        return out

    def read_bom(self, doc_id: str, allow_unreleased: bool = False) -> dict:
        """The BOM in a document's released revision, read by RevisionWorx's own BOM reader.

        Returns {"root", "parts", "lines", "source"}. Fails closed: with nothing released, nothing is imported
        unless the caller asked for the latest revision on purpose."""
        det = self.detail(doc_id)
        rev = det.released
        if rev is None:
            if not allow_unreleased:
                raise RevisionWorxError(f"{det.document.number or det.document.title} has no released revision, so there is no "
                                        "controlled BOM to import.")
            rev = next((r for r in det.history if r.label == det.document.latest_label), None)
            if rev is None:
                raise RevisionWorxError("This document has no revisions.")
        ext = os.path.splitext(det.document.rel_path)[1] or ".csv"
        with tempfile.TemporaryDirectory(prefix="openmeridian-") as d:
            exported = os.path.join(d, "bom" + ext)
            self._run("rev", "export", rev.id, exported)
            out = os.path.join(d, "bom.json")
            self._run("bom", "-o", out, "convert", exported, as_json=False, workspace_flag=False)
            with open(out, encoding="utf-8") as f:
                snap = json.load(f)
        s = snap.get("structure") or {}
        parts = {p["part_id"]: p for p in s.get("parts", [])}
        root = parts.get(snap.get("root_id"), {}).get("number", "")
        lines = []
        for l in s.get("lines", []):
            if l["parent_id"] not in parts or l["child_id"] not in parts:
                raise RevisionWorxError("The BOM has a line that refers to an unknown part.")
            lines.append({"parent": parts[l["parent_id"]]["number"], "child": parts[l["child_id"]]["number"],
                          "qty": parse_qty(l["quantity"]), "find": l.get("find_number", "")})
        return {"root": root, "parts": [{"number": p["number"], "description": p.get("description", ""), "unit": p.get("unit", "")} for p in parts.values()],
                "lines": lines, "source": {"document": doc_id, "revision": rev.id, "label": rev.label, "sha256": rev.sha256,
                                           "number": det.document.number, "released": det.released is not None}}


def build_stamp(detail: DocumentDetail | None) -> dict:
    """What a work order records about the revision it's building."""
    if detail is None:
        return {"rw_document": "", "rw_revision": "", "rw_label": "", "rw_note": "No controlled document linked"}
    if detail.released is None:
        return {"rw_document": detail.document.id, "rw_revision": "", "rw_label": "",
                "rw_note": f"Released with no released revision of {detail.document.number or detail.document.title}"}
    return {"rw_document": detail.document.id, "rw_revision": detail.released.id, "rw_label": detail.released.label, "rw_note": ""}


@dataclass
class Drift:
    text: str
    page: str
    record_id: int


def find_drift(company, client: Client) -> list[Drift]:
    """Where the shop's records no longer match engineering's released revision."""
    out = []
    cache: dict = {}

    def detail(doc_id):
        if doc_id not in cache:
            try:
                cache[doc_id] = client.detail(doc_id)
            except RevisionWorxError:
                cache[doc_id] = None
        return cache[doc_id]
    for w in company.work_orders("released"):
        if not w["rw_document"]:
            continue
        det = detail(w["rw_document"])
        if det is None or det.released is None:
            continue
        if w["build_rw_revision"] != det.released.id:
            built = f"Rev {w['build_rw_label']}" if w["build_rw_label"] else "no released revision"
            out.append(Drift(f"{w['number']} is building {w['item_number']} to {built}, but Rev {det.released.label} is now released",
                             "production", w["id"]))
    for i in company.items():
        if not i["bom_rw_document"]:
            continue
        det = detail(i["bom_rw_document"])
        if det is None or det.released is None:
            continue
        if i["bom_rw_revision"] != det.released.id:
            out.append(Drift(f"{i['number']}: the BOM here is from Rev {i['bom_rw_label'] or '?'}, but Rev {det.released.label} is now released",
                             "items", i["id"]))
    return out
