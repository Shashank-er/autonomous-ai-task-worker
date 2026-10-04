(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const input = $("#task-input");
  const runButton = $("#run-task");
  const dialog = $("#task-dialog");
  const stepList = $("#step-list");
  const progressLabel = $("#progress-label");
  const progressFill = $("#progress-fill");
  const approvalCard = $("#approval-card");
  const approveButton = $("#approve-task");
  const resultCard = $("#result-card");
  const evidenceCard = $("#evidence-card");
  const doneButton = $("#done-button");
  const toast = $("#toast");
  const stepTitles = [
    "Understand your request",
    "Search sample inbox",
    "Extract invoice details",
    "Check finance system",
    "Enter and verify invoice"
  ];
  let currentRun = null;
  let toastTimer = null;

  async function api(path, body) {
    const response = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status}).`);
    return payload;
  }

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("visible"), 3400);
  }

  function formatCurrency(amount) {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount);
  }

  function renderSteps(steps) {
    stepList.replaceChildren();
    steps.forEach((step, index) => {
      const item = document.createElement("li");
      item.className = `step-item ${step.status}`;
      const marker = document.createElement("span");
      marker.className = "step-marker";
      marker.textContent = step.status === "done" ? "✓" : step.status === "failed" ? "!" : step.status === "active" ? "·" : String(index + 1);
      const copy = document.createElement("span");
      copy.className = "step-copy";
      const title = document.createElement("strong");
      title.textContent = step.title;
      const detail = document.createElement("span");
      detail.textContent = step.detail;
      copy.append(title, detail);
      item.append(marker, copy);
      stepList.append(item);
    });
  }

  function setSessionTitle(title, status) {
    $("#dialog-title").firstChild.textContent = title;
    $("#dialog-state").textContent = status;
  }

  function setProgress(steps, label) {
    renderSteps(steps);
    const completed = steps.filter((step) => step.status === "done").length;
    progressFill.style.width = `${Math.round((completed / steps.length) * 100)}%`;
    progressLabel.textContent = label;
  }

  function hideOutcomes() {
    approvalCard.hidden = true;
    resultCard.hidden = true;
    resultCard.className = "result-card";
    evidenceCard.hidden = true;
    doneButton.hidden = true;
  }

  function prepareDialog(taskText) {
    hideOutcomes();
    $("#dialog-description").textContent = `“${taskText}”`;
    setSessionTitle("Working on your task", "WORKER SESSION");
    progressLabel.textContent = "Planning steps";
    progressFill.style.width = "0%";
    const steps = stepTitles.map((title) => ({ title, status: "pending", detail: "Waiting for the worker." }));
    currentRun = { taskText, steps, result: null, inProgress: true };
    $("#close-dialog").disabled = true;
    renderSteps(steps);
    dialog.showModal();
  }

  function showResult(title, message, isError) {
    resultCard.className = `result-card${isError ? " error" : ""}`;
    resultCard.replaceChildren();
    const heading = document.createElement("strong");
    heading.textContent = title;
    const description = document.createElement("span");
    description.textContent = message;
    resultCard.append(heading, description);
    resultCard.hidden = false;
    doneButton.hidden = false;
  }

  function showEvidence(invoice, record, readOnly) {
    const grid = $("#evidence-grid");
    grid.replaceChildren();
    [
      ["Vendor", invoice.company],
      ["Invoice number", invoice.invoice],
      ["Amount", formatCurrency(invoice.amount)],
      ["Due date", invoice.dueDate]
    ].forEach(([label, value]) => {
      const field = document.createElement("div");
      field.className = "evidence-field";
      const labelElement = document.createElement("span");
      labelElement.textContent = label;
      const valueElement = document.createElement("strong");
      valueElement.textContent = value;
      field.append(labelElement, valueElement);
      grid.append(field);
    });
    $(".evidence-heading strong").textContent = readOnly
      ? "Found in sample inbox"
      : "Verified in finance system";
    $("#evidence-ref").textContent = readOnly
      ? `SOURCE: ${invoice.email} · ${invoice.subject}`
      : `RECORD ${record.id} · SOURCE: ${invoice.email} · ${invoice.subject}`;
    evidenceCard.hidden = false;
  }

  function renderActivity(activities) {
    const body = $("#activity-body");
    body.replaceChildren();
    if (!activities.length) {
      const row = document.createElement("tr");
      row.className = "empty-row";
      const cell = document.createElement("td");
      cell.colSpan = 4;
      const icon = document.createElement("span");
      icon.className = "empty-icon";
      icon.textContent = "◷";
      const heading = document.createElement("strong");
      heading.textContent = "No tasks yet";
      const description = document.createElement("span");
      description.textContent = "Your completed tasks will show up here.";
      cell.append(icon, heading, description);
      row.append(cell);
      body.append(row);
      return;
    }

    activities.forEach((activity) => {
      const row = document.createElement("tr");
      row.className = "activity-row";
      const titleCell = document.createElement("td");
      titleCell.className = "activity-task";
      const icon = document.createElement("span");
      icon.className = "activity-task-icon";
      icon.textContent = "▤";
      const title = document.createElement("span");
      title.textContent = activity.title;
      titleCell.append(icon, title);
      const statusCell = document.createElement("td");
      const pill = document.createElement("span");
      pill.className = "status-pill";
      pill.textContent = activity.outcome;
      statusCell.append(pill);
      const dateCell = document.createElement("td");
      dateCell.className = "activity-date";
      dateCell.textContent = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(activity.completedAt));
      const actionCell = document.createElement("td");
      const openButton = document.createElement("button");
      openButton.className = "row-open";
      openButton.type = "button";
      openButton.setAttribute("aria-label", `View task: ${activity.title}`);
      openButton.textContent = "↗";
      openButton.addEventListener("click", () => showToast(`${activity.title} — ${activity.outcome}`));
      actionCell.append(openButton);
      row.append(titleCell, statusCell, dateCell, actionCell);
      body.append(row);
    });
  }

  async function refreshActivity() {
    try {
      const state = await api("/api/state");
      renderActivity(state.activity);
    } catch (error) {
      showToast(`Couldn’t load saved tasks: ${error.message}`);
    }
  }

  function showTaskOutcome(result) {
    if (!currentRun) return;
    currentRun.result = result;
    currentRun.inProgress = false;
    $("#close-dialog").disabled = false;
    setProgress(result.steps, result.progressLabel);
    setSessionTitle(result.sessionTitle, result.sessionStatus);
    if (result.outcome === "clarification") {
      showResult("I haven’t changed anything.", result.message, true);
    } else if (result.outcome === "lookup") {
      showResult("Invoice details found.", result.message);
      showEvidence(result.invoice, null, true);
    } else if (result.outcome === "duplicate") {
      showResult("This invoice is already in your finance system.", result.message);
    } else if (result.outcome === "approval_required") {
      $("#approval-message").textContent = result.message;
      approvalCard.hidden = false;
      approveButton.disabled = false;
    } else if (result.outcome === "completed") {
      showResult("Invoice added and verified.", result.message);
      showEvidence(result.invoice, result.record, false);
    }
    refreshActivity();
  }

  async function animateResult(result, run) {
    const invoice = result.invoice;
    const details = [
      "Identified your request from the instructions.",
      invoice ? `Found ${invoice.invoice}, received ${invoice.received}.` : "Checking the request against the available workflow.",
      invoice ? `Extracted ${formatCurrency(invoice.amount)}; due ${invoice.dueDate}.` : "Checking whether more information is needed.",
      "Checking saved finance records for a duplicate.",
      "Waiting for the worker’s verified result."
    ];
    const limit = result.outcome === "clarification" ? 2 : result.outcome === "lookup" ? 3 : 5;
    for (let index = 0; index < limit; index++) {
      if (currentRun !== run || !dialog.open) return;
      if (index > 0) run.steps[index - 1] = { ...run.steps[index - 1], status: "done" };
      run.steps[index] = { ...run.steps[index], status: "active", detail: details[index] };
      setProgress(run.steps, ["Understanding request", "Searching sample inbox", "Extracting details", "Checking for duplicates", "Verifying outcome"][index]);
      await new Promise((resolve) => setTimeout(resolve, result.outcome === "clarification" ? 380 : 420));
    }
    if (currentRun === run && dialog.open) showTaskOutcome(result);
  }

  async function startTask() {
    const taskText = input.value.trim();
    if (!taskText) {
      input.focus();
      showToast("Describe what you’d like your worker to do first.");
      return;
    }
    runButton.disabled = true;
    runButton.querySelector("span:first-child").textContent = "Working…";
    prepareDialog(taskText);
    const run = currentRun;
    try {
      const result = await api("/api/tasks", { taskText });
      if (currentRun === run) await animateResult(result, run);
    } catch (error) {
      if (currentRun === run) {
        run.inProgress = false;
        $("#close-dialog").disabled = false;
        run.steps[0] = { ...run.steps[0], status: "failed", detail: error.message };
        setProgress(run.steps, "Worker request failed");
        setSessionTitle("I couldn’t complete that request", "ACTION FAILED");
        showResult("No completion could be verified.", `The worker returned an error: ${error.message} Please check the saved records before retrying.`, true);
      }
    } finally {
      runButton.disabled = false;
      runButton.querySelector("span:first-child").textContent = "Start task";
    }
  }

  runButton.addEventListener("click", startTask);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      startTask();
    }
  });
  document.querySelectorAll(".suggestion-card").forEach((card) => {
    card.addEventListener("click", () => {
      input.value = card.dataset.prompt || "";
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    });
  });
  $("#show-all-tasks").addEventListener("click", () => input.focus());
  $("#close-dialog").addEventListener("click", () => {
    if (!currentRun?.inProgress) dialog.close();
  });
  $("#done-button").addEventListener("click", () => dialog.close());
  dialog.addEventListener("cancel", (event) => {
    if (currentRun?.inProgress) {
      event.preventDefault();
      showToast("The worker is finishing this action. You can close this window when it’s done.");
    }
  });
  dialog.addEventListener("close", () => {
    currentRun = null;
    $("#close-dialog").disabled = false;
  });
  approveButton.addEventListener("click", async () => {
    if (!currentRun?.result?.taskId) return;
    approveButton.disabled = true;
    approvalCard.hidden = true;
    progressLabel.textContent = "Adding approved invoice";
    try {
      const result = await api("/api/approve", { taskId: currentRun.result.taskId });
      showTaskOutcome(result);
    } catch (error) {
      approveButton.disabled = false;
      showResult("Approval could not be completed.", error.message, true);
    }
  });

  refreshActivity();
})();
