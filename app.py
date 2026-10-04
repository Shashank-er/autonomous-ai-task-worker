"""Relay's local Python worker and standard-library web server."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
import uuid
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DATA_FILE = Path(os.environ.get("RELAY_DATA_FILE", ROOT / "relay-data.json"))
HOST = "127.0.0.1"
PORT = 8000
APPROVAL_THRESHOLD = 5000

INVOICES: list[dict[str, Any]] = [
    {
        "company": "Acme Cloud",
        "invoice": "AC-1048",
        "amount": 2480,
        "dueDate": "October 24, 2026",
        "received": "October 2, 2026",
        "receivedSort": "2026-10-02",
        "email": "billing@acmecloud.example",
        "subject": "Your October Acme Cloud invoice",
    },
    {
        "company": "Acme Cloud",
        "invoice": "AC-1031",
        "amount": 2480,
        "dueDate": "September 24, 2026",
        "received": "September 2, 2026",
        "receivedSort": "2026-09-02",
        "email": "billing@acmecloud.example",
        "subject": "Your September Acme Cloud invoice",
    },
    {
        "company": "Northstar Studio",
        "invoice": "NS-882",
        "amount": 1360,
        "dueDate": "October 18, 2026",
        "received": "October 1, 2026",
        "receivedSort": "2026-10-01",
        "email": "accounts@northstar.example",
        "subject": "Invoice NS-882 — October production",
    },
    {
        "company": "Meridian Office",
        "invoice": "MO-771",
        "amount": 6420,
        "dueDate": "October 20, 2026",
        "received": "October 3, 2026",
        "receivedSort": "2026-10-03",
        "email": "billing@meridian.example",
        "subject": "Meridian Office invoice MO-771",
    },
]

STEP_TITLES = [
    "Understand your request",
    "Search sample inbox",
    "Extract invoice details",
    "Check finance system",
    "Enter and verify invoice",
]


class WorkerError(Exception):
    """An expected task or storage error safe to report to the browser."""


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"[^\W_]+", folded, flags=re.UNICODE))


def new_steps() -> list[dict[str, str]]:
    details = [
        "Identifying the outcome and vendor from your instructions.",
        "Looking for the most recent invoice from your vendor.",
        "Reading the invoice number, amount, and due date.",
        "Checking for an existing record before making changes.",
        "Adding the invoice, then reading it back to confirm.",
    ]
    return [
        {"title": title, "detail": detail, "status": "pending"}
        for title, detail in zip(STEP_TITLES, details)
    ]


class RelayWorker:
    """Runs the sample-inbox workflow and persists simulated finance records."""

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self.data_file = Path(data_file)
        self._lock = threading.RLock()
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.data_file.exists():
            return {"entries": [], "activity": [], "pending": {}}
        try:
            with self.data_file.open("r", encoding="utf-8") as data:
                stored = json.load(data)
        except (OSError, json.JSONDecodeError) as error:
            raise WorkerError(f"Could not read worker data: {error}") from error
        if not isinstance(stored, dict) or any(
            not isinstance(stored.get(key, default), expected)
            for key, default, expected in (
                ("entries", [], list),
                ("activity", [], list),
                ("pending", {}, dict),
            )
        ):
            raise WorkerError("Saved worker data has an invalid format.")
        return {
            "entries": stored.get("entries", []),
            "activity": stored.get("activity", []),
            "pending": stored.get("pending", {}),
        }

    def _save(self) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.data_file.parent,
                delete=False,
                suffix=".tmp",
            ) as temporary:
                temporary_path = temporary.name
                json.dump(self.state, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.data_file)
        except OSError as error:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
            raise WorkerError(f"Could not save worker data: {error}") from error

    def _persist(self, previous: dict[str, Any]) -> None:
        try:
            self._save()
        except WorkerError:
            self.state = previous
            raise

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": list(self.state["entries"]),
                "activity": list(self.state["activity"]),
            }

    def _add_activity(self, task_id: str, title: str, outcome: str) -> dict[str, str]:
        activity = {
            "id": task_id,
            "title": title,
            "outcome": outcome,
            "completedAt": datetime.now(timezone.utc).isoformat(),
        }
        self.state["activity"].insert(0, activity)
        self.state["activity"] = self.state["activity"][:12]
        return activity

    def _finish(
        self,
        outcome: str,
        title: str,
        message: str,
        steps: list[dict[str, str]],
        *,
        invoice: dict[str, Any] | None = None,
        record: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        status = {
            "clarification": ("I need a little more detail", "CLARIFICATION NEEDED", "Waiting for your input"),
            "lookup": ("Invoice details found", "READ-ONLY TASK COMPLETE", "Invoice details verified"),
            "duplicate": ("No duplicate created", "SAFELY COMPLETED", "Duplicate prevented"),
            "approval_required": ("One quick check", "APPROVAL REQUIRED", "Waiting for approval"),
            "completed": ("Task completed", "VERIFIED SUCCESS", "All steps verified"),
        }[outcome]
        return {
            "outcome": outcome,
            "title": title,
            "message": message,
            "steps": steps,
            "invoice": invoice,
            "record": record,
            "taskId": task_id,
            "sessionTitle": status[0],
            "sessionStatus": status[1],
            "progressLabel": status[2],
        }

    def create_task(self, task_text: Any) -> dict[str, Any]:
        if not isinstance(task_text, str) or not task_text.strip():
            raise ApiError(400, "Describe what you would like the worker to do.")
        task_text = task_text.strip()
        if len(task_text) > 2000:
            raise ApiError(400, "Task descriptions must be 2,000 characters or fewer.")

        normalized = normalize(task_text)
        vendors = list(dict.fromkeys(invoice["company"] for invoice in INVOICES))
        matches = [company for company in vendors if normalize(company) in normalized]
        invoice_words = {"invoice", "invoices", "bill", "bills", "finance", "payable"}
        has_invoice_intent = bool(set(normalized.split()) & invoice_words) or "accounts payable" in normalized
        intent_text = re.sub(
            r"\b(?:do not|don t|dont|never|without|not)\s+"
            r"(?:add(?:ed|ing)?|enter(?:ed|ing)?|log(?:ged|ging)?|"
            r"record(?:ed|ing)?|sav(?:e|ed|ing)|submit(?:ted|ting)?|"
            r"process(?:ed|ing)?|pay(?:ing)?)\b",
            " ",
            normalized,
        )
        intent_words = set(intent_text.split())
        write_actions = {
            "add", "added", "adding", "create", "created", "creating",
            "enter", "entered", "entering", "log", "logged", "logging",
            "process", "processed", "processing", "record", "recorded",
            "recording", "save", "saved", "saving", "submit", "submitted",
            "submitting", "pay", "paying",
        }
        lookup_actions = {
            "check", "checking", "extract", "extracting", "find", "found",
            "get", "getting", "look", "lookup", "review", "search",
            "searching", "show", "summarize",
        }
        if intent_words & write_actions:
            action = "write"
        elif intent_words & lookup_actions or "what" in intent_words:
            action = "lookup"
        else:
            action = None
        steps = new_steps()
        task_id = f"task-{uuid.uuid4().hex}"

        if len(matches) > 1:
            return self._clarification(
                task_id, task_text, steps,
                "I found more than one vendor in your request. Please ask me to process one vendor at a time.",
            )
        if not matches:
            return self._clarification(
                task_id, task_text, steps,
                "Which vendor should I look for? I can find invoices from Acme Cloud, Northstar Studio, or Meridian Office.",
            )
        if not has_invoice_intent:
            return self._clarification(
                task_id, task_text, steps,
                "I can process invoices in this workspace. Please tell me to find or add an invoice for a vendor.",
            )
        if action is None:
            return self._clarification(
                task_id, task_text, steps,
                "Should I only find and summarize the invoice, or should I also add it to the finance system?",
            )

        company = matches[0]
        invoice = max(
            (item for item in INVOICES if item["company"] == company),
            key=lambda item: date.fromisoformat(item["receivedSort"]),
        )
        steps[0].update(status="done", detail=f"Request understood for {company}.")
        steps[1].update(status="done", detail=f"Found {invoice['invoice']}, received {invoice['received']}.")
        steps[2].update(
            status="done",
            detail=f"Extracted {self._currency(invoice['amount'])}; due {invoice['dueDate']}.",
        )
        if action == "lookup":
            steps = steps[:3]
            title = f"{company} invoice {invoice['invoice']}"
            message = (
                f"I found {invoice['invoice']} from {company}: "
                f"{self._currency(invoice['amount'])}, due {invoice['dueDate']}. "
                "I only searched the sample inbox; I did not change finance records."
            )
            with self._lock:
                previous = json.loads(json.dumps(self.state))
                activity = self._add_activity(task_id, title, "Found invoice")
                self._persist(previous)
            result = self._finish("lookup", title, message, steps, invoice=invoice)
            result["activity"] = activity
            return result
        with self._lock:
            existing = next(
                (entry for entry in self.state["entries"] if entry.get("invoice") == invoice["invoice"]),
                None,
            )
            if existing:
                previous = json.loads(json.dumps(self.state))
                steps[3].update(
                    status="done",
                    detail="An invoice with this number already exists. No duplicate was created.",
                )
                steps[4].update(
                    status="failed",
                    detail="Stopped safely because the invoice is already recorded.",
                )
                title = f"{company} invoice {invoice['invoice']}"
                activity = self._add_activity(task_id, title, "Already recorded")
                self._persist(previous)
                result = self._finish(
                    "duplicate",
                    title,
                    f"{invoice['invoice']} is recorded as {self._currency(invoice['amount'])}. I stopped before creating a duplicate.",
                    steps,
                    invoice=invoice,
                )
                result["activity"] = activity
                return result

            if invoice["amount"] >= APPROVAL_THRESHOLD:
                previous = json.loads(json.dumps(self.state))
                steps[3].update(
                    status="done",
                    detail="No matching record found. This invoice is above the $5,000 approval limit.",
                )
                steps[4].update(status="active", detail="Waiting for your approval before adding the invoice.")
                self.state["pending"][task_id] = {"taskText": task_text, "invoice": invoice}
                self._persist(previous)
                return self._finish(
                    "approval_required",
                    f"{company} invoice {invoice['invoice']}",
                    f"{company} invoice {invoice['invoice']} is for {self._currency(invoice['amount'])}. I found a match but won’t enter it until you approve.",
                    steps,
                    invoice=invoice,
                    task_id=task_id,
                )

            return self._commit(task_id, task_text, invoice, steps)

    def _clarification(
        self, task_id: str, task_text: str, steps: list[dict[str, str]], message: str
    ) -> dict[str, Any]:
        steps[0].update(
            status="done",
            detail="Reviewed your instructions and checked which connected workflow applies.",
        )
        steps[1].update(status="failed", detail="Need one more detail before it’s safe to take action.")
        title = task_text if len(task_text) <= 48 else f"{task_text[:45]}…"
        with self._lock:
            previous = json.loads(json.dumps(self.state))
            activity = self._add_activity(task_id, title, "Needs your input")
            self._persist(previous)
        result = self._finish("clarification", title, message, steps)
        result["activity"] = activity
        return result

    @staticmethod
    def _currency(amount: int) -> str:
        return f"${amount:,.2f}"

    def _commit(
        self,
        task_id: str,
        task_text: str,
        invoice: dict[str, Any],
        steps: list[dict[str, str]],
    ) -> dict[str, Any]:
        existing = next(
            (entry for entry in self.state["entries"] if entry.get("invoice") == invoice["invoice"]),
            None,
        )
        if existing:
            previous = json.loads(json.dumps(self.state))
            steps[3].update(
                status="done",
                detail="An invoice with this number was already added. No duplicate was created.",
            )
            steps[4].update(
                status="failed",
                detail="Stopped safely because the invoice is already recorded.",
            )
            activity = self._add_activity(
                task_id, f"{invoice['company']} invoice {invoice['invoice']}", "Already recorded"
            )
            self._persist(previous)
            result = self._finish(
                "duplicate",
                f"{invoice['company']} invoice {invoice['invoice']}",
                f"{invoice['invoice']} is already recorded as {self._currency(invoice['amount'])}. I stopped before creating a duplicate.",
                steps,
                invoice=invoice,
            )
            result["activity"] = activity
            return result

        previous = json.loads(json.dumps(self.state))
        record = {
            "id": f"FIN-{len(self.state['entries']) + 1:06d}",
            "vendor": invoice["company"],
            "invoice": invoice["invoice"],
            "amount": invoice["amount"],
            "dueDate": invoice["dueDate"],
            "source": invoice["email"],
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        self.state["entries"].append(record)
        self.state["pending"].pop(task_id, None)
        activity = self._add_activity(
            task_id, f"{invoice['company']} invoice {invoice['invoice']}", "Completed"
        )
        try:
            self._save()
            persisted = json.loads(self.data_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, WorkerError) as error:
            self.state = previous
            raise WorkerError(f"Could not save and verify the finance record: {error}") from error

        saved_record = next(
            (entry for entry in persisted["entries"] if entry.get("id") == record["id"]),
            None,
        )
        expected = ("vendor", "invoice", "amount", "dueDate")
        if not saved_record or any(
            saved_record.get(field) != record[field] for field in expected
        ):
            self.state = previous
            self._save()
            raise WorkerError("The saved finance record could not be read back and verified.")

        steps[3].update(status="done", detail="No matching invoice found in the finance system.")
        steps[4].update(
            status="done",
            detail=f"Added and read back record {record['id']}; all invoice fields match.",
        )
        result = self._finish(
            "completed",
            f"{invoice['company']} invoice {invoice['invoice']}",
            f"I entered {invoice['invoice']} for {invoice['company']} and checked that the saved record matches the email.",
            steps,
            invoice=invoice,
            record=record,
        )
        result["activity"] = activity
        return result

    def approve(self, task_id: Any) -> dict[str, Any]:
        if not isinstance(task_id, str) or not task_id:
            raise ApiError(400, "The approval request is missing its task ID.")
        with self._lock:
            pending = self.state["pending"].get(task_id)
            if not pending:
                raise ApiError(409, "This task is no longer awaiting approval. Refresh and check its status.")
            steps = new_steps()
            invoice = pending["invoice"]
            steps[0].update(status="done", detail=f"Request understood for {invoice['company']}.")
            steps[1].update(status="done", detail=f"Found {invoice['invoice']}, received {invoice['received']}.")
            steps[2].update(
                status="done",
                detail=f"Extracted {self._currency(invoice['amount'])}; due {invoice['dueDate']}.",
            )
            return self._commit(task_id, pending["taskText"], invoice, steps)


WORKER = RelayWorker()


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "RelayWorker/1.0"
    static_files = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/index.html": ("index.html", "text/html; charset=utf-8"),
        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        "/client.js": ("client.js", "text/javascript; charset=utf-8"),
    }

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format_string % args}")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ApiError(400, "Invalid request body length.") from error
        if length <= 0 or length > 32_768:
            raise ApiError(400, "Request body must be between 1 byte and 32 KB.")
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ApiError(400, "Request body must contain valid JSON.") from error
        if not isinstance(payload, dict):
            raise ApiError(400, "Request body must be a JSON object.")
        return payload

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            self._send_json(200, WORKER.snapshot())
            return
        file_spec = self.static_files.get(path)
        if file_spec is None:
            self._send_json(404, {"error": "Page or resource not found."})
            return
        filename, content_type = file_spec
        try:
            content = (ROOT / filename).read_bytes()
        except OSError as error:
            self._send_json(500, {"error": f"Could not read {filename}: {error}"})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/tasks", "/api/approve"}:
            self._send_json(404, {"error": "API route not found."})
            return
        try:
            payload = self._read_json()
            result = (
                WORKER.create_task(payload.get("taskText"))
                if path == "/api/tasks"
                else WORKER.approve(payload.get("taskId"))
            )
            self._send_json(200, result)
        except ApiError as error:
            self._send_json(error.status, {"error": error.message})
        except WorkerError as error:
            self._send_json(500, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), RelayHandler)
    print(f"Relay worker running at http://{HOST}:{PORT}")
    print(f"Finance records are stored in {DATA_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Relay worker.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
