// Ledger web page: talks to the JSON API, no build step.

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) {
    throw new Error((body.errors || ["request failed"]).join("; "));
  }
  return body;
}

function formatCents(cents, currency) {
  const sign = cents < 0 ? "-" : "";
  const value = Math.abs(cents);
  return `${sign}${Math.floor(value / 100)}.${String(value % 100).padStart(2, "0")} ${currency}`;
}

async function loadTransactions() {
  const data = await api("/api/transactions?page=1");
  const rows = document.getElementById("rows");
  rows.innerHTML = "";
  for (const t of data.items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${t.date}</td><td>${t.kind}</td><td>${t.category}</td><td>${t.description}</td><td class="amount">${formatCents(t.amount_cents, "EUR")}</td>`;
    rows.appendChild(tr);
  }
}

async function loadReport() {
  const year = document.getElementById("year").value;
  const month = document.getElementById("month").value;
  const data = await api(`/api/report?year=${year}&month=${month}`);
  document.getElementById("report").textContent = data.lines.join("\n");
}

document.getElementById("load-report").addEventListener("click", () => loadReport().catch(showError));
document.getElementById("add").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.target).entries());
  try {
    await api("/api/transactions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    event.target.reset();
    showError("");
    await loadTransactions();
  } catch (error) {
    showError(error.message);
  }
});

function showError(message) {
  document.getElementById("error").textContent = message;
}

loadTransactions().catch(showError);
