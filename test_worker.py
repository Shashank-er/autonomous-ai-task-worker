"""Focused tests for Relay's Python worker."""

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from app import ApiError, RelayHandler, RelayWorker, WorkerError


class RelayWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.data_file = Path(self.temporary_directory.name) / "relay-data.json"
        self.worker = RelayWorker(self.data_file)

    def test_routine_invoice_is_persisted_and_verified(self) -> None:
        result = self.worker.create_task(
            "Find the latest invoice from Acme Cloud and enter it into finance."
        )

        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["invoice"]["invoice"], "AC-1048")
        self.assertEqual(result["record"]["amount"], 2480)
        self.assertTrue(self.data_file.exists())
        self.assertEqual(result["steps"][-1]["status"], "done")
        self.assertEqual(RelayWorker(self.data_file).snapshot()["entries"][0]["invoice"], "AC-1048")

    def test_high_value_invoice_waits_for_approval_before_writing(self) -> None:
        result = self.worker.create_task(
            "Add the latest invoice from Meridian Office to our finance system."
        )

        self.assertEqual(result["outcome"], "approval_required")
        self.assertEqual(self.worker.snapshot()["entries"], [])

        approved = self.worker.approve(result["taskId"])

        self.assertEqual(approved["outcome"], "completed")
        self.assertEqual(approved["record"]["invoice"], "MO-771")
        self.assertEqual(len(self.worker.snapshot()["entries"]), 1)

    def test_duplicate_invoice_is_not_written_twice(self) -> None:
        request = "Process the latest Northstar Studio invoice in finance."
        first = self.worker.create_task(request)
        duplicate = self.worker.create_task(request)

        self.assertEqual(first["outcome"], "completed")
        self.assertEqual(duplicate["outcome"], "duplicate")
        self.assertEqual(len(self.worker.snapshot()["entries"]), 1)

    def test_missing_vendor_requests_clarification_without_writing(self) -> None:
        result = self.worker.create_task("Find the latest invoice and enter it.")

        self.assertEqual(result["outcome"], "clarification")
        self.assertIn("Which vendor", result["message"])
        self.assertEqual(self.worker.snapshot()["entries"], [])

    def test_lookup_request_extracts_details_without_writing(self) -> None:
        result = self.worker.create_task("Find the latest invoice from Acme Cloud.")

        self.assertEqual(result["outcome"], "lookup")
        self.assertEqual(result["invoice"]["invoice"], "AC-1048")
        self.assertIn("did not change finance records", result["message"])
        self.assertEqual(self.worker.snapshot()["entries"], [])
        self.assertEqual(len(self.worker.snapshot()["activity"]), 1)

    def test_explicitly_read_only_request_does_not_trigger_a_write(self) -> None:
        result = self.worker.create_task(
            "Find the latest invoice from Acme Cloud, but don't add it."
        )

        self.assertEqual(result["outcome"], "lookup")
        self.assertEqual(self.worker.snapshot()["entries"], [])

    def test_ambiguous_action_asks_before_writing(self) -> None:
        result = self.worker.create_task("Acme Cloud invoice, please.")

        self.assertEqual(result["outcome"], "clarification")
        self.assertIn("only find and summarize", result["message"])
        self.assertEqual(self.worker.snapshot()["entries"], [])

    def test_invalid_or_oversized_requests_are_rejected(self) -> None:
        with self.assertRaises(ApiError):
            self.worker.create_task("")
        with self.assertRaises(ApiError):
            self.worker.create_task("x" * 2001)

    def test_storage_failure_does_not_report_success_or_leave_memory_write(self) -> None:
        with patch.object(self.worker, "_save", side_effect=WorkerError("disk unavailable")):
            with self.assertRaisesRegex(WorkerError, "disk unavailable"):
                self.worker.create_task(
                    "Add the latest invoice from Acme Cloud to finance."
                )

        self.assertEqual(self.worker.snapshot()["entries"], [])

    def test_http_api_runs_the_python_worker(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), RelayHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        with patch("app.WORKER", self.worker):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
            self.addCleanup(connection.close)
            connection.request("GET", "/")
            page_response = connection.getresponse()
            page = page_response.read().decode("utf-8")
            self.assertEqual(page_response.status, 200)
            self.assertIn('src="client.js"', page)

            connection.request(
                "POST",
                "/api/tasks",
                body=json.dumps({"taskText": "Process the latest Acme Cloud invoice in finance."}),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            result = json.loads(response.read())

        self.assertEqual(response.status, 200)
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["record"]["invoice"], "AC-1048")


if __name__ == "__main__":
    unittest.main()
