// pywebview 브리지 헬퍼 — 모든 API 호출은 여기로
const api = (name, ...args) => window.pywebview.api[name](...args);
const $ = (sel) => document.querySelector(sel);

let tradesCache = [];

// ── 탭 전환 ──
document.querySelectorAll(".tab").forEach(btn => btn.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".pane").forEach(p => p.classList.remove("active"));
  btn.classList.add("active");
  $("#tab-" + btn.dataset.tab).classList.add("active");
  if (btn.dataset.tab === "trades") loadTrades();
  if (btn.dataset.tab === "reports") loadReports();
  if (btn.dataset.tab === "settings") loadSettings();
  if (btn.dataset.tab === "equity" || btn.dataset.tab === "positions") loadDashboard();
}));

// ── 상태 폴링 (3초) ──
const STATUS_LABEL = { ours: "● 실행중", external: "● 실행중(외부)", stopping: "● 종료 대기중", stopped: "● 정지됨" };
async function pollStatus() {
  try {
    const s = await api("get_status");
    if (s.error) return;
    $("#bot-version").textContent = s.bot_version;
    const badge = $("#bot-status");
    badge.textContent = STATUS_LABEL[s.bot] || s.bot;
    badge.className = "badge " + s.bot;
    const acc = $("#account-badge");
    acc.textContent = s.demo ? "데모 계좌" : "⚠ 실전 계좌";
    acc.className = "badge " + (s.demo ? "demo" : "real");
    $("#btn-start").disabled = s.bot !== "stopped";
    $("#btn-stop").disabled = s.bot === "stopped";
    const log = $("#log-view");
    const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
    log.innerHTML = s.log_tail.map(l =>
      l.includes("ALERT") ? `<span class="alert">${escapeHtml(l)}</span>` : escapeHtml(l)
    ).join("\n");
    if (stick) log.scrollTop = log.scrollHeight;
  } catch (e) { /* 브리지 준비 전 */ }
}
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

// ── 봇 제어 ──
$("#btn-start").addEventListener("click", async () => {
  $("#btn-start").disabled = true;
  const r = await api("start_bot");
  $("#start-problems").textContent = (r.problems || []).join(" / ") || (r.error || "");
  pollStatus();
});
$("#btn-stop").addEventListener("click", async () => {
  if (!confirm("봇을 정지할까요? (1분 내 안전하게 종료됩니다. 보유 포지션의 손절은 거래소에 등록돼 있어 유지됩니다)")) return;
  await api("stop_bot");
  pollStatus();
});

// ── 자산 + 포지션 ──
let chart = null;
async function loadDashboard() {
  const d = await api("get_dashboard");
  if (d.error) { $("#equity-now").textContent = d.error; return; }
  $("#equity-now").textContent = "$" + d.equity.toLocaleString(undefined, { minimumFractionDigits: 2 });
  const pts = d.history.map(h => ({ x: h.ts, y: h.equity }));
  const ctx = $("#equity-chart").getContext("2d");
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: "line",
    data: { datasets: [{ data: pts, borderColor: "#4a9eff", pointRadius: 0, tension: 0.2 }] },
    options: { animation: false, plugins: { legend: { display: false } },
      scales: { x: { type: "category", ticks: { color: "#9aa5b3", maxTicksLimit: 8,
                     callback: (v, i) => (pts[i] ? pts[i].x.slice(5, 16) : "") } },
                y: { ticks: { color: "#9aa5b3" } } } }
  });
  const tbody = $("#pos-table tbody");
  tbody.innerHTML = d.positions.map(p => `<tr>
    <td>${p.symbol}</td><td>${p.side}</td><td>${p.size}</td><td>${p.entry}</td><td>${p.mark}</td>
    <td class="${p.unrealised >= 0 ? "pos" : "neg"}">${p.unrealised >= 0 ? "+" : ""}$${p.unrealised}</td>
    <td>${p.stop_loss}</td></tr>`).join("");
  $("#pos-empty").style.display = d.positions.length ? "none" : "block";
}

// ── 거래기록 ──
async function loadTrades() {
  const t = await api("get_trades");
  if (t.error) {
    $("#trade-summary").innerHTML = `<div class="stat"><div class="stat-label">오류</div><div class="stat-value neg">${t.error}</div></div>`;
    return;
  }
  const s = t.summary;
  $("#trade-summary").innerHTML = `
    <div class="stat"><div class="stat-label">누적 실현손익 (정본)</div><div class="stat-value ${s.total >= 0 ? "pos" : "neg"}">$${s.total.toLocaleString()}</div></div>
    <div class="stat"><div class="stat-label">거래 수</div><div class="stat-value">${s.n}건</div></div>
    <div class="stat"><div class="stat-label">승률</div><div class="stat-value">${s.win_rate}%</div></div>
    <div class="stat"><div class="stat-label">건당 기대값</div><div class="stat-value">$${s.ev}</div></div>
    <div class="stat"><div class="stat-label">잭팟 (손절각오 7.8배↑)</div><div class="stat-value">${s.jackpots}건</div></div>`;
  tradesCache = t.rows;
  $("#trades-empty").classList.toggle("hidden", !t.empty);
  $("#trade-table").classList.toggle("hidden", !!t.empty);
  renderTrades();
}
function renderTrades() {
  const q = $("#f-symbol").value.trim().toUpperCase();
  const mode = $("#f-result").value;
  const rows = tradesCache.filter(r =>
    (!q || r.symbol.includes(q)) &&
    (mode === "" || (mode === "win" && r.pnl > 0) || (mode === "loss" && r.pnl <= 0) || (mode === "jackpot" && r.jackpot)));
  $("#trade-table tbody").innerHTML = rows.map(r => `<tr class="${r.jackpot ? "jackpot" : ""}">
    <td>${r.ts}</td><td>${r.symbol}</td><td>${r.side}</td><td>${r.entry}</td><td>${r.exit}</td>
    <td class="${r.pnl >= 0 ? "pos" : "neg"}">${r.pnl >= 0 ? "+" : ""}${r.pnl}</td>
    <td>${r.hold_h}</td><td>${r.arm}</td></tr>`).join("");
}
$("#f-symbol").addEventListener("input", renderTrades);
$("#f-result").addEventListener("change", renderTrades);

// ── 리포트 ──
async function loadReports() {
  const r = await api("get_reports");
  if (r.error) { $("#report-body").textContent = r.error; return; }
  $("#report-list").innerHTML = r.days.map(d => `<li data-day="${d}">${d}</li>`).join("");
  document.querySelectorAll("#report-list li").forEach(li => li.addEventListener("click", async () => {
    document.querySelectorAll("#report-list li").forEach(x => x.classList.remove("sel"));
    li.classList.add("sel");
    const rep = await api("get_report", li.dataset.day);
    $("#report-body").innerHTML = marked.parse(rep.md || "");
  }));
  if (r.days.length) {
    document.querySelector("#report-list li").click();
  } else {
    $("#report-body").textContent = "아직 생성된 리포트가 없습니다 — 매일 00:30에 자동 생성됩니다.";
  }
}

// ── 설정 ──
async function loadSettings() {
  const s = await api("get_settings");
  if (s.error) { $("#app-msg").textContent = s.error; return; }
  $("#cur-key").textContent = s.api_key_masked;
  $("#cur-secret").textContent = s.api_secret_masked;
  (s.demo ? $("#mode-demo") : $("#mode-real")).checked = true;
  $("#real-confirm-row").classList.toggle("hidden", s.demo);
  $("#chk-auto-report").checked = s.auto_report;
  $("#chk-autostart").checked = s.boot_autostart;
  const c = await api("get_config_view");
  $("#config-view").textContent = c.yaml || c.error;
}
document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener("change", () => {
  $("#real-confirm-row").classList.toggle("hidden", $("#mode-demo").checked);
}));
$("#btn-save-keys").addEventListener("click", async () => {
  const r = await api("save_api_keys", $("#in-key").value, $("#in-secret").value);
  $("#keys-msg").textContent = r.msg || r.error;
  if (r.ok) { $("#in-key").value = ""; $("#in-secret").value = ""; loadSettings(); }
});
$("#btn-save-mode").addEventListener("click", async () => {
  const demo = $("#mode-demo").checked;
  const r = await api("set_demo_mode", demo, $("#in-real-confirm").value);
  $("#mode-msg").textContent = r.msg || r.error;
  if (r.ok) loadSettings();
});
$("#chk-auto-report").addEventListener("change", async (e) => {
  const r = await api("set_app_setting", "auto_report", e.target.checked);
  $("#app-msg").textContent = r.msg || r.error;
});
$("#chk-autostart").addEventListener("change", async (e) => {
  const r = await api("set_app_setting", "boot_autostart", e.target.checked);
  $("#app-msg").textContent = r.msg || r.error;
});

// ── 시작 ──
window.addEventListener("pywebviewready", () => {
  pollStatus();
  setInterval(pollStatus, 3000);
  setInterval(() => {
    if ($("#tab-equity").classList.contains("active") || $("#tab-positions").classList.contains("active")) loadDashboard();
  }, 20000);
});
