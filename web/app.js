"use strict";

// Vanilla JS, no build step. SECURITY: every server-supplied string (assistant message,
// citations, proposed action, trace) is inserted with textContent / createTextNode — never
// innerHTML — so model output or retrieved text can never inject markup into the page.

const chat = document.getElementById("chat");
const form = document.getElementById("composer");
const input = document.getElementById("message");
const sendBtn = document.getElementById("send");
const backdrop = document.getElementById("modal-backdrop");
const modalPreview = document.getElementById("modal-preview");
const modalAction = document.getElementById("modal-action");
const approveBtn = document.getElementById("approve");
const declineBtn = document.getElementById("decline");

// A fresh session id per page load → an isolated per-session checkpoint (thread) on the server.
const SESSION_ID = "web-" + Math.random().toString(36).slice(2, 10);

const SUGGESTIONS = [
  "What's the difference between the Gold and Platinum maintenance plans?",
  "Is there a surcharge for a Sunday appointment?",
  "There's a burning smell coming from my electrical panel!",
  "Book an HVAC tune-up at ZIP 22030 for 15th May 2026 in the morning. Customer id CID-5000.",
  "What's the status of booking BK-003?",
];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text; // textContent: safe by construction
  return node;
}

function addUser(text) {
  chat.appendChild(el("div", "msg user", text));
  scroll();
}

function addSystem(text) {
  chat.appendChild(el("div", "msg system", text));
  scroll();
}

function addAssistant(data) {
  const kind = data.kind === "handoff" ? "assistant handoff" : "assistant";
  const bubble = el("div", "msg " + kind);
  bubble.appendChild(el("div", "text", data.message || ""));

  const citations = data.citations || [];
  if (citations.length) {
    const box = el("div", "citations");
    box.appendChild(el("span", "cite-label", "Sources: "));
    citations.forEach((c) => box.appendChild(el("span", "cite-chip", c)));
    bubble.appendChild(box);
  }

  const trace = data.trace;
  if (trace && trace.committed && trace.committed_booking_id) {
    bubble.appendChild(el("div", "committed", "✓ Booking committed: " + trace.committed_booking_id));
  }

  if (trace) {
    const details = el("details", "trace");
    details.appendChild(el("summary", null, "trace"));
    details.appendChild(el("pre", null, traceSummary(trace)));
    bubble.appendChild(details);
  }

  chat.appendChild(bubble);
  scroll();
}

function traceSummary(trace) {
  // Build a compact, human-readable trace (textContent, so it cannot inject markup).
  const lines = [];
  lines.push("intent: " + (trace.intent ?? "—"));
  lines.push("route:  " + (trace.route ?? "—"));
  if (trace.retrieval_confidence) lines.push("retrieval: " + trace.retrieval_confidence);
  if (trace.tool_calls && trace.tool_calls.length) {
    const tools = trace.tool_calls
      .map((t) => t.name + (t.capability === "mutating" ? "*" : "") + (t.ok ? "" : "(failed)"))
      .join(", ");
    lines.push("tools:  " + tools);
  }
  if (trace.confirmation_required) {
    lines.push("confirm: " + (trace.confirmation_decision ?? "pending"));
  }
  if (trace.committed) lines.push("committed: " + (trace.committed_booking_id ?? "yes"));
  if (trace.emergency) lines.push("emergency: true");
  if (trace.handoff) lines.push("handoff: " + (trace.handoff_category ?? "yes"));
  return lines.join("\n");
}

function scroll() {
  window.scrollTo(0, document.body.scrollHeight);
}

function setBusy(busy) {
  input.disabled = busy;
  sendBtn.disabled = busy;
  if (!busy) input.focus();
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

function handleResult(data) {
  if (data.kind === "confirmation_required") {
    showConfirm(data);
    return;
  }
  addAssistant(data);
}

async function sendMessage(text) {
  addUser(text);
  setBusy(true);
  try {
    const data = await postJSON(`/api/sessions/${SESSION_ID}/messages`, { message: text });
    handleResult(data);
  } catch (e) {
    addSystem("Network error — is the demo server running?");
  } finally {
    setBusy(false);
  }
}

// ---- Confirm-before-commit modal ---------------------------------------------------------------
// The booking is created/changed ONLY when the user clicks Approve, which POSTs the decision to
// /confirm; the server resumes the paused graph and the commit node runs. Decline mutates nothing.

function showConfirm(data) {
  modalPreview.textContent = data.preview || data.message || "Proceed?";
  modalAction.textContent = JSON.stringify(data.proposed_action || {}, null, 2);
  backdrop.classList.remove("hidden");
}

function hideConfirm() {
  backdrop.classList.add("hidden");
}

async function decide(decision) {
  hideConfirm();
  addSystem("You chose to " + decision + ".");
  setBusy(true);
  try {
    const data = await postJSON(`/api/sessions/${SESSION_ID}/confirm`, { decision });
    handleResult(data);
  } catch (e) {
    addSystem("Network error during confirmation.");
  } finally {
    setBusy(false);
  }
}

approveBtn.addEventListener("click", () => decide("approve"));
declineBtn.addEventListener("click", () => decide("decline"));

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendMessage(text);
});

// ---- Suggestion chips --------------------------------------------------------------------------
const chipBox = document.getElementById("suggestion-chips");
SUGGESTIONS.forEach((s) => {
  const chip = el("button", "chip", s.length > 60 ? s.slice(0, 57) + "…" : s);
  chip.type = "button";
  chip.title = s;
  chip.addEventListener("click", () => {
    if (input.disabled) return;
    sendMessage(s);
  });
  chipBox.appendChild(chip);
});

addSystem("Connected. Ask a policy question, or try booking — you'll be asked to confirm first.");
input.focus();
