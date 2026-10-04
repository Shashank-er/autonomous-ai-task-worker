# Relay — Autonomous AI task worker prototype

Relay is a small, browser-based prototype for handing an outcome to a worker and seeing how it gets done. It focuses on one end-to-end workflow: find a vendor's latest invoice in a simulated inbox, extract its details, add it to a simulated finance system, and verify the saved record.

## Setup

- Python 3.10 or newer.
- A modern browser.
- No third-party Python packages, API keys, database, or frontend build tools are required. The server uses only Python's standard library.

Download or clone the project, then open a terminal in the project folder (the folder containing `app.py`). An optional virtual environment can keep the project isolated:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On Command Prompt, activate it with:

```bat
.\.venv\Scripts\activate.bat
```

Skip virtual-environment setup if you already have Python 3.10+ available. There are no dependencies to install.

## Run

From the project folder, start the local web server:

```powershell
python app.py
```

If `python` does not resolve to Python 3.10+, select an installed supported version with the Python launcher (for example, Python 3.10):

```powershell
py -3.10 app.py
```

Once the terminal reports that Relay is running, open **http://127.0.0.1:8000** in your browser. Keep the terminal open while using the app; press **Ctrl+C** there to stop the server.

The app binds to `127.0.0.1` and port `8000`. If that port is already in use, stop the other local server using it before starting Relay. Task history and finance records are written to `relay-data.json` in the project folder. Set the `RELAY_DATA_FILE` environment variable before launch to store this data at another path.

Run the worker test suite from the same folder with:

```powershell
python -m unittest -v test_worker.py
```

## Try it

- Process a routine invoice: “Find the latest invoice from Acme Cloud, enter it into our finance system, and tell me when it’s done.”
- Look up an invoice without writing: “Find the latest invoice from Acme Cloud.”
- See an approval checkpoint: “Add the latest invoice from Meridian Office to our finance system.” The $6,420 invoice is held until you approve it.
- See a safe clarification: “Find the latest invoice and enter it.” The worker asks which vendor and makes no changes.
- See an intent clarification: “Acme Cloud invoice, please.” The worker asks whether you want a lookup or a finance-system entry.
- Run a task twice to see duplicate detection prevent a second finance record.

## Try it

- Process a routine invoice: “Find the latest invoice from Acme Cloud, enter it into our finance system, and tell me when it’s done.”
- Look up an invoice without writing: “Find the latest invoice from Acme Cloud.”
- See an approval checkpoint: “Add the latest invoice from Meridian Office to our finance system.” The $6,420 invoice is held until you approve it.
- See a safe clarification: “Find the latest invoice and enter it.” The worker asks which vendor and makes no changes.
- See an intent clarification: “Acme Cloud invoice, please.” The worker asks whether you want a lookup or a finance-system entry.
- Run a task twice to see duplicate detection prevent a second finance record.

The supported simulated vendors are Acme Cloud, Northstar Studio, and Meridian Office. `app.py` owns request interpretation, sample inbox search, read-versus-write intent, duplicate detection, approval gating, finance record persistence, and read-back verification. Lookup requests are read-only; only explicit write requests can create finance records. `client.js` only connects the browser interface to the Python API and renders the worker's responses. The prototype does not connect to real email, a real finance system, or a language model. Its execution plan, checks, approval gate, saved record, and evidence are interactive rather than static mockups.

## Architecture

The browser UI (`index.html`, `styles.css`, and `client.js`) sends task and approval requests to the local standard-library HTTP server in `app.py`. The Python worker interprets the task, searches the sample inbox, applies read-only, duplicate, and approval checks, and persists finance records and activity to `relay-data.json`. After a write, it reads the saved record back before reporting success. No third-party services or external accounts are involved.

## Safety and verification

Invoices of $5,000 or more require explicit approval before the worker writes anything. It checks for an existing invoice number before creating a record, then reads the newly saved local record back to verify it. Unrecognized or ambiguous requests stop and ask for more information. No external side effects occur.
