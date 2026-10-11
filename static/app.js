const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

let STATE = null;

const money = (n, sign = false) => {
  const v = Number(n) || 0;
  const abs = Math.abs(v).toLocaleString(undefined, { style: "currency", currency: "USD" });
  if (!sign) return v < 0 ? `-${abs.replace("-", "")}` : abs;
  if (v > 0) return `+${abs}`;
  if (v < 0) return `-${abs}`;
  return abs;
};

const clsAmt = (n) => (n < 0 ? "neg" : n > 0 ? "pos" : "");

async function api(path, opts) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

async function load() {
  STATE = await api("/api/state");
  $("#household-label").textContent = STATE.summary.household + " · " + STATE.summary.today;
  $("#buffer").value = STATE.summary.buffer;
  renderAll();
}

function renderAll() {
  renderCommand();
  renderCalendar();
  renderAccounts();
  renderBills();
  renderDebts();
  renderBudget();
  renderStrategy();
  const show = STATE.summary.show_strategy !== false;
  const btn = $("#tab-btn-strategy");
  if (btn) btn.style.display = show ? "" : "none";
  if (!show && $("#tab-strategy")?.classList.contains("active")) {
    $$("#tabs button").forEach((b) => b.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    $('[data-tab="command"]').classList.add("active");
    $("#tab-command").classList.add("active");
  }
}

function renderCommand() {
  const s = STATE.summary;
  const remaining = STATE.events.filter((e) => {
    return e.date.slice(0, 7) === s.month && e.date >= s.today && !e.paid;
  });
  const upcoming = remaining.slice(0, 10);
  const demo = s.demo
    ? `<div class="demo-banner">
        Demo household is loaded so the calendar is not empty.
        <span class="actions">
          <button class="ghost" id="backup-db">Export DB</button>
          <button class="ghost" id="restore-db">Import DB</button>
          <button class="ghost" id="cleanup-once">Clean paid one-time bills</button>
          <button class="ghost" id="wipe">Start empty</button>
          <button class="ghost" id="reset-demo">Reload demo</button>
        </span>
      </div>`
    : `<div class="toolbar"><span class="muted">Live household data</span>
        <span class="actions">
          <button class="ghost" id="backup-db">Export DB</button>
          <button class="ghost" id="restore-db">Import DB</button>
          <button class="ghost" id="cleanup-once">Clean paid one-time bills</button>
          <button class="ghost" id="reset-demo">Load demo data</button>
        </span></div>`;
  // hidden file input for restore
  if (!$("#restore-file")) {
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = ".db,application/octet-stream";
    inp.id = "restore-file";
    inp.style.display = "none";
    document.body.appendChild(inp);
  }
  const strategyHint =
    s.show_strategy === false
      ? `<div class="demo-banner" style="background:#121923;border-color:var(--line);color:var(--muted)">
          Strategy / Coach is hidden.
          <button class="ghost" id="show-strategy-again">Show Strategy tab</button>
        </div>`
      : "";

  const lows = (s.account_lows || [])
    .filter((l) => l.type === "checking" || l.type === "savings")
    .map(
      (l) => `<div class="row">
        <div>${escapeHtml(l.account_name)}<div class="muted">low ${l.low_date}</div></div>
        <div class="amt ${clsAmt(l.low_balance)}">${money(l.low_balance)}</div>
      </div>`
    )
    .join("");

  const tips = (s.advice || [])
    .map(
      (t) => `<article class="tip ${t.level}"><h4>${escapeHtml(t.title)}</h4><p>${escapeHtml(t.body)}</p></article>`
    )
    .join("");

  const sub = STATE.subscriptions || { items: [], monthly_total: 0, annual_total: 0, count: 0 };
  const topSubs = (sub.items || []).slice(0, 5);
  const subCard = `<article class="card" style="margin-top:14px">
      <div class="toolbar">
        <h2 style="margin:0">Subscriptions this year</h2>
        <span class="muted">${sub.count} · ${money(sub.monthly_total)}/mo · <strong class="neg">${money(sub.annual_total)}/yr</strong></span>
      </div>
      ${
        topSubs
          .map((it) => {
            const flag = (it.flags || [])[0];
            return `<div class="row">
              <span>${escapeHtml(it.name)}${flag ? ` <span class="flag ${escapeHtml(flag.code)}">${escapeHtml(flag.label)}</span>` : ""}</span>
              <span class="amt">${money(it.monthly)} <span class="muted">→ ${money(it.annual)}/yr</span></span>
            </div>`;
          })
          .join("") || `<p class="muted">No subscription-like bills on the books.</p>`
      }
      <p class="muted" style="margin:10px 0 0">Review Keep / Pause / Cancel on the Bills tab. Yearly cost is the number that should sting.</p>
    </article>`;

  const rw = (STATE.allocation && STATE.allocation.runway) || {};
  const rwMonths = rw.months;
  const rwTarget = rw.target || 3;
  const rwPct = rw.pct_of_target == null ? 0 : Math.min(100, rw.pct_of_target);
  const rwCats = (rw.categories || [])
    .map(
      (c) =>
        `<div class="row"><span>${escapeHtml(c.category)}</span><span class="amt">${money(c.monthly)}/mo</span></div>`
    )
    .join("");
  const rwAccts = (rw.accounts || [])
    .map(
      (a) =>
        `<div class="row"><span>${escapeHtml(a.name)}</span><span class="amt">${money(a.balance)}</span></div>`
    )
    .join("");
  const eta =
    rw.months_to_target != null
      ? `Safety job ${money(rw.safety_monthly)}/mo fills the gap in ~${rw.months_to_target} months.`
      : rw.gap_cash > 0
        ? "Assign leftover to Safety on Budget to give this a close date."
        : "Floor is at or above target.";
  const runwayCard = `<article class="card runway ${escapeHtml(rw.status || "")}" style="margin-top:14px">
      <div class="toolbar">
        <h2 style="margin:0">Emergency fund runway</h2>
        <span class="muted">Savings only · checking buffer is operating cash</span>
      </div>
      <div class="grid cols-3">
        <div>
          <div class="label muted">Months of fixed bills covered</div>
          <div class="runway-num">${rwMonths == null ? "—" : rwMonths.toFixed(1)} <span class="muted">/ ${rwTarget}</span></div>
          <div class="bar thick"><span style="width:${rwPct}%"></span></div>
          <p class="${rw.status === "ok" || rw.status === "strong" ? "pos" : rw.status === "short" || rw.status === "critical" || rw.status === "empty" ? "warn" : "muted"}">${escapeHtml(rw.headline || "")}</p>
        </div>
        <div>
          <div class="row"><span>Fixed bills</span><span class="amt">${money(rw.fixed_monthly || 0)}/mo</span></div>
          <div class="row"><span>Savings in the fund</span><span class="amt">${money(rw.savings || 0)}</span></div>
          ${
            (STATE.sinking && STATE.sinking.earmarked)
              ? `<div class="row"><span>Sinking earmarks pulled out</span><span class="amt">${money(STATE.sinking.earmarked)}</span></div>`
              : ""
          }
          <div class="row"><span>Cash to hit target</span><span class="amt">${money(rw.gap_cash || 0)}</span></div>
          <p class="muted">${escapeHtml(eta)}</p>
        </div>
        <div>
          <h3 style="margin:0 0 8px;font-size:13px">What “fixed” means</h3>
          ${rwCats || '<p class="muted">Recurring outs except savings sweeps.</p>'}
          ${rwAccts ? `<h3 style="margin:12px 0 8px;font-size:13px">Counted savings</h3>${rwAccts}` : `<p class="muted">Add a savings account to measure the floor.</p>`}
        </div>
      </div>
    </article>`;

  const al = STATE.allocation || {};
  const jobRows = (al.buckets || [])
    .map(
      (x) => `<div class="row">
        <span>${escapeHtml(x.name)} · ${x.pct}%</span>
        <span class="amt">${money(x.amount)}</span>
      </div>`
    )
    .join("");
  const allocCard = `<article class="card" style="margin-top:14px">
      <div class="toolbar">
        <h2 style="margin:0">Leftover jobs</h2>
        <span class="muted">${money(al.leftover || 0)} to assign · ${
          al.runway_months == null ? "no runway yet" : al.runway_months.toFixed(1) + " mo safety"
        }</span>
      </div>
      ${jobRows || `<p class="muted">No leftover after bills and buffer.</p>`}
      <p class="muted" style="margin:10px 0 0">${escapeHtml(al.why || "Open Budget to change the split or apply transfers.")}</p>
    </article>`;

  const sk = STATE.sinking || { items: [], monthly_need: 0, earmarked: 0 };
  const skRows = (sk.items || [])
    .slice(0, 5)
    .map(
      (f) => `<div class="row">
        <span>${escapeHtml(f.name)} <span class="muted">${escapeHtml(f.due || "")}</span></span>
        <span class="amt">${money(f.monthly_need)}/mo <span class="muted">${money(f.reserved)}/${money(f.target_amount)}</span></span>
      </div>`
    )
    .join("");
  const sinkCard = `<article class="card" style="margin-top:14px">
      <div class="toolbar">
        <h2 style="margin:0">Sinking funds</h2>
        <span class="muted">${money(sk.earmarked)} earmarked · ${money(sk.monthly_need)}/mo to stay on track</span>
      </div>
      ${skRows || `<p class="muted">No annual hits reserved yet. Add them on Bills so December is not a surprise.</p>`}
      <p class="muted" style="margin:10px 0 0">Earmarks come out of emergency-fund runway. Manage on the Bills tab.</p>
    </article>`;

  const snaps = STATE.snapshots || [];
  const nwMin = snaps.length ? Math.min(...snaps.map((x) => x.net_worth)) : 0;
  const nwMax = snaps.length ? Math.max(...snaps.map((x) => x.net_worth)) : 1;
  const span = nwMax - nwMin || 1;
  const spark = snaps
    .map((x) => {
      const h = Math.max(8, Math.round(((x.net_worth - nwMin) / span) * 36));
      return `<span title="${x.as_of} ${money(x.net_worth)}" style="display:inline-block;width:8px;height:${h}px;background:var(--accent);margin-right:2px;vertical-align:bottom;border-radius:2px"></span>`;
    })
    .join("");
  const lastNw = snaps.length ? snaps[snaps.length - 1] : null;
  const firstNw = snaps.length ? snaps[0] : null;
  const nwDelta = lastNw && firstNw ? lastNw.net_worth - firstNw.net_worth : 0;
  const snapCard = `<article class="card" style="margin-top:14px">
      <div class="toolbar">
        <h2 style="margin:0">Net worth snapshots</h2>
        <span class="muted">${snaps.length} day(s)${firstNw && lastNw && firstNw.as_of !== lastNw.as_of ? ` · ${escapeHtml(firstNw.as_of)} → ${escapeHtml(lastNw.as_of)} ${nwDelta >= 0 ? "+" : ""}${money(nwDelta)}` : ""}</span>
      </div>
      <div style="height:40px;display:flex;align-items:flex-end">${spark || '<span class="muted">A point is stored each day you open Command.</span>'}</div>
    </article>`;

  const subChoices = (STATE.subscriptions?.items || [])
    .slice(0, 8)
    .map(
      (it) => `<label class="row">
        <span><input type="checkbox" data-whatif="${it.id}" style="width:auto" /> ${escapeHtml(it.name)} <span class="muted">${money(it.monthly)}/mo</span></span>
      </label>`
    )
    .join("");
  const whatifCard = `<article class="card" style="margin-top:14px">
      <div class="toolbar">
        <h2 style="margin:0">What-if</h2>
        <span class="muted">Cancel subs + extra debt, then apply if the lows look safe</span>
      </div>
      ${subChoices || '<p class="muted">Add subscriptions to cancel in a preview.</p>'}
      <div class="form-grid" style="margin-top:10px">
        <label>Extra debt / mo
          <input id="whatif-extra" type="number" min="0" step="25" value="${STATE.summary.extra_debt ?? 0}" />
        </label>
      </div>
      <div class="form-actions" style="justify-content:flex-start">
        <button class="ghost" id="whatif-preview">Preview 90 days</button>
        <button class="primary" id="whatif-apply">Apply to books</button>
      </div>
      <div id="whatif-out" class="muted" style="margin-top:10px"></div>
    </article>`;

  const hits = upcoming
    .map(
      (e) => `<div class="row">
        <div>
          <strong>${escapeHtml(e.vendor)}</strong>
          <div class="muted">${e.date} · ${escapeHtml(e.account_name)}</div>
        </div>
        <div class="amt ${e.direction === "in" ? "pos" : "neg"}">${e.direction === "in" ? "+" : "−"}${money(e.amount)}</div>
      </div>`
    )
    .join("") || `<p class="muted">No remaining hits from today through month-end.</p>`;

  $("#tab-command").innerHTML = `
    ${demo}
    ${strategyHint}
    <div class="grid kpis">
      <article class="card kpi"><div class="label">Cash</div><div class="value">${money(s.cash)}</div></article>
      <article class="card kpi"><div class="label">Investments</div><div class="value">${money(s.investments)}</div></article>
      <article class="card kpi"><div class="label">Crypto</div><div class="value">${money(s.crypto)}</div></article>
      <article class="card kpi"><div class="label">Debt</div><div class="value neg">${money(s.debt)}</div></article>
      <article class="card kpi"><div class="label">Net worth</div><div class="value">${money(s.net_worth)}</div></article>
    </div>
    ${runwayCard}
    <div class="grid cols-2" style="margin-top:14px">
      <article class="card">
        <h2>This month’s cash reality</h2>
        <div class="row"><span>Income still coming this month</span><span class="amt pos">${money(s.remaining_in)}</span></div>
        <div class="row"><span>Bills still unpaid this month</span><span class="amt neg">${money(-s.remaining_out)}</span></div>
        <div class="row"><span>Already paid / past due dates</span><span class="amt">${money(-s.already_out)}</span></div>
        <div class="row"><span>Next 30 days in / out</span><span class="amt">${money(s.next30_in)} / ${money(-s.next30_out)}</span></div>
        <div class="row"><span>Safety buffer</span><span class="amt">${money(-s.buffer)}</span></div>
        <div class="row"><span>Safe to spend this month</span><strong class="amt ${clsAmt(s.safe_to_spend)}">${money(s.safe_to_spend)}</strong></div>
        <div class="row"><span>Safe after next 30 days of bills</span><strong class="amt ${clsAmt(s.next30_safe)}">${money(s.next30_safe)}</strong></div>
        ${
          s.primary_low
            ? `<p class="muted" style="margin:12px 0 0">
                ${escapeHtml(s.primary_low.account_name)} projected low
                <strong class="${clsAmt(s.primary_low.low_balance)}">${money(s.primary_low.low_balance)}</strong>
                on ${s.primary_low.low_date}.
              </p>`
            : ""
        }
      </article>
      <article class="card">
        <h2>Projected lows</h2>
        ${lows || '<p class="muted">Add a checking or savings account to project lows.</p>'}
      </article>
    </div>
    <div class="grid cols-2" style="margin-top:14px">
      <article class="card">
        <h2>Upcoming hits</h2>
        ${hits}
      </article>
      <article class="card">
        <h2>Advice</h2>
        <div class="advice">${tips}</div>
      </article>
    </div>
    ${subCard}
    ${allocCard}
    ${sinkCard}
    ${snapCard}
    ${whatifCard}
  `;
  $("#wipe")?.addEventListener("click", async () => {
    if (confirm("Erase demo data and start with empty books?")) {
      await api("/api/wipe", { method: "POST", body: "{}" });
      await load();
    }
  });
  $("#reset-demo")?.addEventListener("click", async () => {
    await api("/api/reset-demo", { method: "POST", body: "{}" });
    await load();
  });
  $("#show-strategy-again")?.addEventListener("click", async () => {
    await savePrefs({ show_strategy: true });
  });
  $("#backup-db")?.addEventListener("click", () => {
    window.location.href = "/api/backup";
  });
  $("#restore-db")?.addEventListener("click", () => {
    const inp = $("#restore-file");
    if (!inp) return;
    inp.value = "";
    inp.onchange = async () => {
      const file = inp.files?.[0];
      if (!file) return;
      if (
        !confirm(
          "Replace the current database with this backup? Everything now in the app will be overwritten."
        )
      ) {
        return;
      }
      const body = new FormData();
      body.append("file", file);
      const res = await fetch("/api/restore", { method: "POST", body });
      if (!res.ok) {
        alert(await res.text());
        return;
      }
      await load();
      alert("Backup restored.");
    };
    inp.click();
  });
  $("#cleanup-once")?.addEventListener("click", async () => {
    if (
      !confirm(
        "Remove all one-time bills that have been marked paid? Recurring bills are left alone."
      )
    ) {
      return;
    }
    const res = await api("/api/cleanup", { method: "POST", body: "{}" });
    await load();
    alert(`Removed ${res.removed} paid one-time bill(s).`);
  });
  const whatifBody = () => ({
    cancel_ids: $$("[data-whatif]:checked").map((el) => Number(el.dataset.whatif)),
    extra_debt: Number($("#whatif-extra")?.value || 0),
  });
  $("#whatif-preview")?.addEventListener("click", async () => {
    const res = await api("/api/whatif", { method: "POST", body: JSON.stringify(whatifBody()) });
    const low = res.primary_low
      ? `${res.primary_low.account_name} low ${money(res.primary_low.low_balance)} on ${res.primary_low.low_date}`
      : "no primary low";
    $("#whatif-out").innerHTML =
      `Safe this month ${money(res.safe_to_spend)} · leftover ${money(res.leftover)} · ${low}. ` +
      `Debt plan ${res.debt_months || "—"} mo, interest ${money(res.debt_interest || 0)}, done ${res.debt_payoff || "—"}.`;
  });
  $("#whatif-apply")?.addEventListener("click", async () => {
    const body = whatifBody();
    if (!confirm("Cancel checked subscriptions and set extra debt to this preview?")) return;
    const res = await api("/api/whatif/apply", { method: "POST", body: JSON.stringify(body) });
    await load();
    alert((res.notes || []).join("\n") || "Applied.");
  });
}

function renderCalendar() {
  const s = STATE.summary;
  const [y, m] = s.month.split("-").map(Number);
  const first = new Date(y, m - 1, 1);
  const last = new Date(y, m, 0);
  const startPad = (first.getDay() + 6) % 7; // Monday first
  const eventsByDay = {};
  for (const e of STATE.events.filter((ev) => ev.date.startsWith(s.month))) {
    const day = Number(e.date.slice(8, 10));
    (eventsByDay[day] ||= []).push(e);
  }

  const dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    .map((d) => `<div class="dow">${d}</div>`)
    .join("");
  let cells = "";
  for (let i = 0; i < startPad; i++) cells += `<div class="day empty"></div>`;
  for (let day = 1; day <= last.getDate(); day++) {
    const iso = `${s.month}-${String(day).padStart(2, "0")}`;
    const list = eventsByDay[day] || [];
    const outTotal = list.filter((e) => e.direction === "out" && !e.paid).reduce((a, e) => a + e.amount, 0);
    const tight = outTotal >= 400;
    const hits = list
      .map((e) => {
        const paid = e.paid || e.date < s.today ? "paid" : "";
        return `<div class="hit ${e.direction} ${paid}" title="${escapeHtml(e.account_name)}">
          <span>${escapeHtml(e.vendor)}</span>
          <span>${e.direction === "in" ? "+" : "−"}${e.amount.toFixed(0)}</span>
        </div>`;
      })
      .join("");
    cells += `<div class="day ${iso === s.today ? "today" : ""} ${tight ? "tight" : ""}">
      <div class="num">${day}</div>${hits}
    </div>`;
  }

  const vendors = {};
  for (const e of STATE.events.filter((ev) => ev.date.startsWith(s.month) && ev.direction === "out")) {
    vendors[e.vendor] = (vendors[e.vendor] || 0) + e.amount;
  }
  const vendorRows = Object.entries(vendors)
    .sort((a, b) => b[1] - a[1])
    .map(([name, amt]) => `<div class="row"><span>${escapeHtml(name)}</span><span class="amt neg">${money(amt)}</span></div>`)
    .join("");

  $("#tab-calendar").innerHTML = `
    <div class="toolbar">
      <h2 style="margin:0">Payout calendar · ${s.month}</h2>
      <span class="muted">Committed out ${money(s.month_out)} · in ${money(s.month_in)}</span>
    </div>
    <div class="grid cols-2">
      <article class="card"><div class="cal">${dow}${cells}</div></article>
      <article class="card">
        <h2>By vendor this month</h2>
        ${vendorRows || '<p class="muted">No bills on the books.</p>'}
      </article>
    </div>
  `;
}

function renderAccounts() {
  const rows = STATE.accounts
    .map((a) => {
      return `<tr>
        <td><strong>${escapeHtml(a.name)}</strong><div class="muted">${escapeHtml(a.institution || "")}</div></td>
        <td>${escapeHtml(a.type)}</td>
        <td class="${clsAmt(a.balance)}">${money(a.balance)}</td>
        <td>${a.apr != null ? a.apr + "%" : "—"}</td>
        <td>${a.min_payment != null ? money(a.min_payment) : "—"}</td>
        <td>${a.due_day != null ? a.due_day : "—"}</td>
        <td class="actions">
          <button class="ghost" data-edit-account="${a.id}">Edit</button>
          <button class="danger" data-del-account="${a.id}">Delete</button>
        </td>
      </tr>`;
    })
    .join("");

  const rec = STATE.reconciliation || { missing: [], drifted: [], unplanned: [], hits: [] };
  const recRows = [
    ...(rec.drifted || []).map(
      (r) => `<tr>
        <td><strong>${escapeHtml(r.name)}</strong><div class="muted">due ${r.occur_date} · statement ${r.tx_date || ""}</div></td>
        <td>drift</td>
        <td class="amt">${money(r.expected)}</td>
        <td class="amt">${money(r.actual)}</td>
        <td><button class="ghost" data-adopt="${r.obligation_id}" data-amt="${r.actual}">Use statement amount</button></td>
      </tr>`
    ),
    ...(rec.missing || []).map(
      (r) => `<tr>
        <td><strong>${escapeHtml(r.name)}</strong><div class="muted">expected ${r.occur_date}</div></td>
        <td>missing</td>
        <td class="amt">${money(r.expected)}</td>
        <td class="muted">—</td>
        <td class="muted">No matching charge in imports</td>
      </tr>`
    ),
    ...(rec.unplanned || []).slice(0, 8).map(
      (r) => `<tr>
        <td>${escapeHtml(r.description)}<div class="muted">${r.tx_date}</div></td>
        <td>unplanned</td>
        <td class="muted">—</td>
        <td class="amt ${clsAmt(r.amount)}">${money(r.amount)}</td>
        <td class="muted">Not in the bill book</td>
      </tr>`
    ),
  ].join("");

  $("#tab-accounts").innerHTML = `
    <div class="toolbar">
      <h2 style="margin:0">Accounts</h2>
      <span class="actions">
        <label class="buffer" style="margin:0">
          <input id="post-paid" type="checkbox" ${STATE.summary.post_paid ? "checked" : ""} style="width:auto" />
          Post paid hits to balances
        </label>
        <button class="ghost" id="import-statement">Import statement</button>
        <button class="primary" id="add-account">Add account</button>
      </span>
    </div>
    <p class="muted">
      Balances are snapshots as of <strong>${escapeHtml(STATE.summary.balances_as_of || STATE.summary.today)}</strong>.
      Checking “paid” only removes a hit from the projection unless “Post paid hits to balances” is on.
      Import a statement with a Balance column (or edit the account) to refresh cash.
    </p>
    <article class="card">
      <table>
        <thead><tr><th>Name</th><th>Type</th><th>Balance</th><th>APR</th><th>Min</th><th>Due day</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="7" class="muted">No accounts yet.</td></tr>`}</tbody>
      </table>
    </article>
    <article class="card" style="margin-top:14px">
      <div class="toolbar">
        <h2 style="margin:0">This month vs statements</h2>
        <span class="muted">${rec.tx_count || 0} imported lines · ${rec.matched || 0} matched · unplanned out ${money(rec.unplanned_out || 0)}</span>
      </div>
      <p class="muted">After you import a CSV, this is how you keep the bill book honest. Drift = same vendor, different amount.</p>
      <table>
        <thead><tr><th>Item</th><th></th><th>Book</th><th>Statement</th><th></th></tr></thead>
        <tbody>${recRows || `<tr><td colspan="5" class="muted">Import a statement to compare. No drift or missing hits in the current file set.</td></tr>`}</tbody>
      </table>
    </article>
  `;
  $("#add-account").onclick = () => openAccountForm();
  $("#import-statement").onclick = () => openStatementImport();
  $("#post-paid")?.addEventListener("change", async (e) => {
    await savePrefs({ post_paid: e.target.checked });
  });
  $$("[data-adopt]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Set this bill’s amount to the statement charge?")) return;
      await api("/api/reconcile/adopt", {
        method: "POST",
        body: JSON.stringify({ obligation_id: Number(b.dataset.adopt), amount: Number(b.dataset.amt) }),
      });
      await load();
    };
  });
  $$("[data-edit-account]").forEach((b) => {
    b.onclick = () => openAccountForm(STATE.accounts.find((a) => a.id === Number(b.dataset.editAccount)));
  });
  $$("[data-del-account]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Delete this account and its bills?")) return;
      await api("/api/accounts/" + b.dataset.delAccount, { method: "DELETE" });
      await load();
    };
  });
}

function openStatementImport() {
  if (!STATE.accounts.length) {
    alert("Add an account first, then import a statement into it.");
    return;
  }
  const acctOpts = STATE.accounts
    .map((a) => `<option value="${a.id}">${escapeHtml(a.name)} (${escapeHtml(a.type)})</option>`)
    .join("");
  openModal("Import bank / card statement", `
    <p class="muted">CSV or Excel export. Supported headers include Date, Description/Comments, Check Number, Amount, Balance. Amounts like <code>($25.00)</code> are treated as withdrawals.</p>
    <div class="form-grid">
      <label class="full">Account
        <select name="account_id">${acctOpts}</select>
      </label>
      <label class="full">Statement file
        <input name="file" type="file" accept=".csv,.tsv,.txt,.xlsx,.xls,text/csv" required />
      </label>
      <label class="full">
        <span style="display:flex;gap:8px;align-items:center">
          <input name="update_balance" type="checkbox" checked style="width:auto" />
          Update account balance from statement Balance column
        </span>
      </label>
    </div>
    <div id="import-preview" class="muted" style="margin-top:10px"></div>
    <div class="form-actions">
      <button type="button" class="ghost" id="preview-stmt">Preview</button>
      <button type="submit" class="primary">Import</button>
    </div>
  `, async (fd) => {
    const fileInput = $("#modal-form input[name=file]");
    const file = fileInput?.files?.[0];
    if (!file) {
      alert("Choose a file");
      throw new Error("no file");
    }
    const preview = await previewStatementFile(file);
    if (!preview.transactions?.length) {
      alert("No transactions found.\n" + (preview.errors || []).join("\n"));
      throw new Error("empty");
    }
    const res = await api("/api/statements/commit", {
      method: "POST",
      body: JSON.stringify({
        account_id: Number(fd.get("account_id")),
        transactions: preview.transactions,
        update_balance: !!fd.get("update_balance"),
      }),
    });
    closeModal();
    await load();
    alert(`Imported ${res.inserted} new transactions (${res.skipped} duplicates skipped).`);
  });

  $("#preview-stmt").onclick = async (e) => {
    e.preventDefault();
    const file = $("#modal-form input[name=file]")?.files?.[0];
    if (!file) {
      alert("Choose a file first");
      return;
    }
    const preview = await previewStatementFile(file);
    const box = $("#import-preview");
    if (!preview.transactions?.length) {
      box.innerHTML = `<p class="neg">No rows parsed. ${(preview.errors || []).map(escapeHtml).join("; ")}</p>`;
      return;
    }
    const s = preview.summary;
    const sample = preview.transactions
      .slice(0, 8)
      .map(
        (t) =>
          `<div class="row"><span>${t.date} · ${escapeHtml(t.description).slice(0, 48)}</span>
           <span class="amt ${clsAmt(t.amount)}">${money(t.amount)}</span></div>`
      )
      .join("");
    box.innerHTML = `
      <p><strong>${s.count}</strong> transactions · ${s.date_min} → ${s.date_max}<br/>
      In ${money(s.credits)} · Out ${money(s.debits)} · Net ${money(s.net)}
      ${s.latest_balance != null ? ` · Stmt balance ${money(s.latest_balance)}` : ""}</p>
      ${sample}
      ${preview.errors?.length ? `<p class="warn">${preview.errors.length} row warnings</p>` : ""}
    `;
    // stash for submit
    $("#modal-form").dataset.preview = JSON.stringify(preview.transactions);
  };
}

async function previewStatementFile(file) {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch("/api/statements/preview", { method: "POST", body });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function renderBills() {
  const rows = STATE.obligations
    .map((o) => {
      const acct = STATE.accounts.find((a) => a.id === o.account_id);
      return `<tr>
        <td><strong>${escapeHtml(o.name)}</strong><div class="muted">${escapeHtml(o.vendor || "")}</div></td>
        <td>${escapeHtml(acct ? acct.name : "")}</td>
        <td class="${o.direction === "in" ? "pos" : "neg"}">${o.direction === "in" ? "+" : "−"}${money(o.amount)}</td>
        <td>${escapeHtml(o.cadence)}</td>
        <td>${
          o.cadence === "semimonthly"
            ? `${o.due_day ?? "?"}${
                Number(o.due_day_2) === -1 || o.due_day_2 == null
                  ? " & last weekday"
                  : o.due_day_2 != null
                    ? " & " + o.due_day_2
                    : ""
              }`
            : o.due_day ?? o.next_date ?? "—"
        }</td>
        <td>${escapeHtml(o.category || "")}</td>
        <td>${
          !o.active
            ? (o.end_date ? "Ended " + o.end_date : "Cancelled")
            : o.end_date
              ? "Ends " + o.end_date
              : "On"
        }</td>
        <td class="actions">
          <button class="ghost" data-edit-ob="${o.id}">Edit</button>
          <button class="danger" data-del-ob="${o.id}">Delete</button>
        </td>
      </tr>`;
    })
    .join("");

  const upcoming = STATE.events.filter((e) => e.date >= STATE.summary.today).slice(0, 16);
  const checks = upcoming
    .map((e) => {
      return `<label class="row">
        <span>
          <input type="checkbox" data-pay="${e.obligation_id}" data-date="${e.date}" ${e.paid ? "checked" : ""} />
          ${e.date} · ${escapeHtml(e.vendor)} · ${escapeHtml(e.account_name)}
        </span>
        <span class="amt ${e.direction === "in" ? "pos" : "neg"}">${e.direction === "in" ? "+" : "−"}${money(e.amount)}</span>
      </label>`;
    })
    .join("");

  const sub = STATE.subscriptions || { items: [], redirects: [], monthly_total: 0, annual_total: 0, count: 0 };
  const redirectOpts = (sub.redirects || [])
    .map((r) => `<option value="${escapeHtml(r.id)}">${escapeHtml(r.label)}</option>`)
    .join("");
  const subRows = (sub.items || [])
    .map((it) => {
      const flags = (it.flags || [])
        .map((f) => `<span class="flag ${escapeHtml(f.code)}">${escapeHtml(f.label)}</span>`)
        .join("");
      return `<tr>
        <td>
          <strong>${escapeHtml(it.name)}</strong>
          <div class="muted">${escapeHtml(it.vendor)}${it.cluster ? " · " + it.cluster : ""}</div>
          <div class="flags">${flags}</div>
        </td>
        <td class="amt">${money(it.monthly)}</td>
        <td class="amt neg">${money(it.annual)}</td>
        <td class="muted">${escapeHtml(it.cadence)}${it.due_day ? " · day " + it.due_day : ""}</td>
        <td>
          <div class="actions sub-actions">
            <button class="ghost" data-sub-pause="${it.id}">Pause</button>
            <button class="danger" data-sub-cancel="${it.id}">Cancel</button>
          </div>
        </td>
      </tr>`;
    })
    .join("");

  const sink = STATE.sinking || { items: [], monthly_need: 0, earmarked: 0, count: 0 };
  const sinkRows = (sink.items || [])
    .map((f) => {
      return `<tr>
        <td>
          <strong>${escapeHtml(f.name)}</strong>
          <div class="muted">${escapeHtml(f.vendor || "")} · ${escapeHtml(f.category || "")}</div>
          <span class="flag ${f.status === "funded" || f.status === "on_track" ? "easy" : f.status === "due_soon" ? "high" : "stale"}">${escapeHtml(f.status.replace("_", " "))}</span>
        </td>
        <td class="amt">${money(f.target_amount)}</td>
        <td class="amt">${money(f.reserved)} <span class="muted">${f.pct}%</span></td>
        <td>${escapeHtml(f.due || "—")}<div class="muted">${f.months_left} mo left</div></td>
        <td class="amt">${money(f.monthly_need)}</td>
        <td>
          <div class="actions sub-actions">
            <button class="ghost" data-sink-edit="${f.id}">Edit</button>
            <button class="ghost" data-sink-reserve="${f.id}">Put reserve on calendar</button>
            <button class="ghost" data-sink-payout="${f.id}">Put hit on calendar</button>
            <button class="danger" data-sink-del="${f.id}">Delete</button>
          </div>
        </td>
      </tr>`;
    })
    .join("");

  $("#tab-bills").innerHTML = `
    <div class="toolbar">
      <h2 style="margin:0">Bill book</h2>
      <span class="actions">
        <button class="ghost" id="bulk-import">Bulk import</button>
        <button class="primary" id="add-ob">Add bill or paycheck</button>
      </span>
    </div>
    <article class="card" style="margin-bottom:14px">
      <div class="toolbar">
        <h2 style="margin:0">Sinking funds</h2>
        <span class="actions">
          <span class="muted">${sink.count} · ${money(sink.earmarked)} set aside · ${money(sink.monthly_need)}/mo still needed</span>
          <button class="primary" id="add-sink">Add known hit</button>
        </span>
      </div>
      <p class="muted" style="margin-top:0">
        Annual insurance lumps, registration, tires, holidays. Reserve monthly into savings so the month of the hit is boring.
        Earmarked cash is subtracted from emergency-fund runway — it is not the floor.
      </p>
      <table>
        <thead><tr><th>Hit</th><th>Target</th><th>Set aside</th><th>Next due</th><th>/mo</th><th></th></tr></thead>
        <tbody>${sinkRows || `<tr><td colspan="6" class="muted">No sinking funds yet. Add the bills that wreck “good” months.</td></tr>`}</tbody>
      </table>
    </article>
    <article class="card" style="margin-bottom:14px">
      <div class="toolbar">
        <h2 style="margin:0">Subscription kill list</h2>
        <span class="muted">${sub.count} live · ${money(sub.monthly_total)}/mo · ${money(sub.annual_total)}/yr</span>
      </div>
      <p class="muted" style="margin-top:0">
        Monthly feels small. Yearly is the real leak. Pause stops charges after next month-end.
        Cancel stops future hits after today. Redirect sends that monthly amount to debt or savings.
      </p>
      <label class="muted" style="display:grid;gap:6px;max-width:420px;margin-bottom:12px">
        When I pause or cancel, send the money to
        <select id="sub-redirect">${redirectOpts}</select>
      </label>
      <table>
        <thead><tr><th>Service</th><th>/mo</th><th>/yr</th><th>Cadence</th><th></th></tr></thead>
        <tbody>${subRows || `<tr><td colspan="5" class="muted">No subscription-like bills. Tag a bill category as subscriptions or name it (Netflix, Spotify, gym…).</td></tr>`}</tbody>
      </table>
    </article>
    <div class="grid cols-2">
      <article class="card">
        <table>
          <thead><tr><th>Name</th><th>Account</th><th>Amount</th><th>Cadence</th><th>Day</th><th>Category</th><th></th><th></th></tr></thead>
          <tbody>${rows || `<tr><td colspan="8" class="muted">No obligations yet.</td></tr>`}</tbody>
        </table>
      </article>
      <article class="card">
        <h2>Mark paid</h2>
        <p class="muted">Checking a hit takes it out of the projected balance.</p>
        ${checks || '<p class="muted">Nothing upcoming.</p>'}
      </article>
    </div>
  `;
  $("#add-ob").onclick = () => openObligationForm();
  $("#bulk-import").onclick = () => openImportForm();
  $("#add-sink")?.addEventListener("click", () => openSinkingForm());
  $$("[data-sink-edit]").forEach((b) => {
    b.onclick = () =>
      openSinkingForm((STATE.sinking.items || []).find((f) => f.id === Number(b.dataset.sinkEdit)));
  });
  $$("[data-sink-del]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Delete this sinking fund? Calendar reserves already created stay unless you delete those bills too.")) return;
      await api("/api/sinking/" + b.dataset.sinkDel, { method: "DELETE" });
      await load();
    };
  });
  const applySink = async (id, action) => {
    const res = await api("/api/sinking/" + id + "/apply", {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    await load();
    if (res.notes) alert(res.notes.join("\n"));
  };
  $$("[data-sink-reserve]").forEach((b) => {
    b.onclick = () => applySink(b.dataset.sinkReserve, "reserve");
  });
  $$("[data-sink-payout]").forEach((b) => {
    b.onclick = () => applySink(b.dataset.sinkPayout, "payout");
  });
  $$("[data-edit-ob]").forEach((b) => {
    b.onclick = () => openObligationForm(STATE.obligations.find((o) => o.id === Number(b.dataset.editOb)));
  });
  $$("[data-del-ob]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Delete this obligation?")) return;
      await api("/api/obligations/" + b.dataset.delOb, { method: "DELETE" });
      await load();
    };
  });
  $$("[data-pay]").forEach((box) => {
    box.onchange = async () => {
      await api("/api/payments", {
        method: "POST",
        body: JSON.stringify({
          obligation_id: Number(box.dataset.pay),
          occur_date: box.dataset.date,
          paid: box.checked ? 1 : 0,
          post_balance: !!STATE.summary.post_paid,
        }),
      });
      await load();
    };
  });
  const runSub = async (id, decision) => {
    const redirect = $("#sub-redirect")?.value || "none";
    const label = decision === "cancel" ? "Cancel this subscription" : decision === "pause" ? "Pause through next month-end" : "Keep";
    if (decision === "keep") return;
    if (!confirm(label + "?")) return;
    const res = await api("/api/subscriptions/action", {
      method: "POST",
      body: JSON.stringify({ obligation_id: Number(id), decision, redirect }),
    });
    await load();
    if (res.notes && res.notes.length) alert(res.notes.join("\n"));
  };
  $$("[data-sub-pause]").forEach((b) => {
    b.onclick = () => runSub(b.dataset.subPause, "pause");
  });
  $$("[data-sub-cancel]").forEach((b) => {
    b.onclick = () => runSub(b.dataset.subCancel, "cancel");
  });
}

async function savePrefs(partial) {
  const s = STATE.summary;
  const llm = STATE.llm || {};
  const body = {
    buffer: Number($("#buffer").value || s.buffer || 0),
    household: s.household || "Household",
    debt_strategy: partial.debt_strategy ?? s.debt_strategy,
    extra_debt: partial.extra_debt ?? s.extra_debt,
    show_strategy: partial.show_strategy ?? s.show_strategy,
  };
  if (partial.llm_enabled !== undefined) body.llm_enabled = partial.llm_enabled;
  if (partial.llm_provider !== undefined) body.llm_provider = partial.llm_provider;
  if (partial.llm_base_url !== undefined) body.llm_base_url = partial.llm_base_url;
  if (partial.llm_model !== undefined) body.llm_model = partial.llm_model;
  if (partial.llm_api_key !== undefined) body.llm_api_key = partial.llm_api_key;
  if (partial.alloc_mode !== undefined) body.alloc_mode = partial.alloc_mode;
  if (partial.alloc_debt_pct !== undefined) body.alloc_debt_pct = partial.alloc_debt_pct;
  if (partial.alloc_safety_pct !== undefined) body.alloc_safety_pct = partial.alloc_safety_pct;
  if (partial.alloc_build_pct !== undefined) body.alloc_build_pct = partial.alloc_build_pct;
  if (partial.safety_months !== undefined) body.safety_months = partial.safety_months;
  if (partial.post_paid !== undefined) body.post_paid = partial.post_paid;
  await api("/api/settings", { method: "POST", body: JSON.stringify(body) });
  await load();
}

function renderDebts() {
  const debts = STATE.debts || [];
  const plan = STATE.debt_plan || { order: [], totals: {}, strategy_meta: {} };
  const compare = STATE.debt_compare || [];
  const s = STATE.summary;
  const meta = plan.strategy_meta || {};
  const totals = plan.totals || {};

  const rows = debts
    .map((d) => {
      const step = (plan.order || []).find((o) => o.id === d.id);
      return `<tr>
        <td><strong>${escapeHtml(d.name)}</strong><div class="muted">${escapeHtml(d.institution)} · ${escapeHtml(d.type)}</div></td>
        <td class="neg">${money(-d.principal)}</td>
        <td>${d.apr ? d.apr + "%" : "—"}</td>
        <td>${money(d.min_payment)}</td>
        <td>${d.due_day ?? "—"}</td>
        <td>${step ? "#" + step.rank : "—"}</td>
        <td>${step?.payoff_date ? step.payoff_date + " · " + step.months + " mo" : "—"}</td>
      </tr>`;
    })
    .join("");

  const orderCards = (plan.order || [])
    .map(
      (o) => `<div class="row">
        <div><strong>#${o.rank} ${escapeHtml(o.name)}</strong>
          <div class="muted">${o.apr}% APR · min ${money(o.min_payment)} · ${escapeHtml(o.status)}</div>
        </div>
        <div class="amt">${o.payoff_date ? o.payoff_date : "—"}</div>
      </div>`
    )
    .join("");

  const cmp = compare
    .map(
      (c) => `<tr>
        <td>${escapeHtml(c.label)}</td>
        <td>${c.months || "—"} mo</td>
        <td>${money(c.interest)}</td>
        <td>${escapeHtml(c.first_target || "—")}</td>
        <td>${c.payoff_date || "—"}</td>
      </tr>`
    )
    .join("");

  $("#tab-debts").innerHTML = `
    <div class="toolbar">
      <h2 style="margin:0">Debts</h2>
      <span class="muted">${debts.length} accounts · principal ${money(totals.principal || 0)}</span>
    </div>
    <div class="grid cols-2">
      <article class="card">
        <h2>Payoff controls</h2>
        <div class="form-grid">
          <label>Strategy
            <select id="debt-strategy">
              <option value="avalanche">Avalanche — highest interest first</option>
              <option value="snowball">Snowball — lowest balance first</option>
              <option value="highest_balance">Highest balance first</option>
              <option value="lowest_apr">Lowest interest first</option>
            </select>
          </label>
          <label>Extra monthly payment
            <input id="extra-debt" type="number" min="0" step="25" value="${s.extra_debt ?? 0}" />
          </label>
        </div>
        <p class="muted">${escapeHtml(meta.blurb || "")}${s.extra_debt_auto ? " Extra defaulted to 20% of leftover budget." : ""}</p>
        <div class="form-actions" style="justify-content:flex-start">
          <button class="primary" id="apply-debt-plan">Apply plan</button>
        </div>
      </article>
      <article class="card">
        <h2>Plan totals</h2>
        <div class="row"><span>Minimums combined</span><span class="amt">${money(totals.min_payments || 0)}/mo</span></div>
        <div class="row"><span>Extra applied</span><span class="amt">${money(plan.extra_monthly || 0)}/mo</span></div>
        <div class="row"><span>Estimated interest</span><span class="amt neg">${money(totals.interest || 0)}</span></div>
        <div class="row"><span>Months to clear</span><span class="amt">${totals.months || "—"}</span></div>
        <div class="row"><span>Payoff date</span><span class="amt">${totals.payoff_date || "—"}</span></div>
        ${plan.note ? `<p class="warn">${escapeHtml(plan.note)}</p>` : ""}
      </article>
    </div>
    <article class="card" style="margin-top:14px">
      <h2>Debt accounts</h2>
      <table>
        <thead><tr><th>Account</th><th>Balance</th><th>APR</th><th>Min</th><th>Due</th><th>Order</th><th>In this plan</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="7" class="muted">No credit cards or loans with a balance. Add them on Accounts.</td></tr>`}</tbody>
      </table>
    </article>
    <div class="grid cols-2" style="margin-top:14px">
      <article class="card">
        <h2>Attack order</h2>
        ${orderCards || '<p class="muted">Nothing to sequence.</p>'}
      </article>
      <article class="card">
        <h2>Compare strategies</h2>
        <table>
          <thead><tr><th>Strategy</th><th>Time</th><th>Interest</th><th>First target</th><th>Done</th></tr></thead>
          <tbody>${cmp || `<tr><td colspan="5" class="muted">Add debts to compare.</td></tr>`}</tbody>
        </table>
      </article>
    </div>
  `;
  const sel = $("#debt-strategy");
  if (sel) {
    const v = s.debt_strategy || "avalanche";
    // lowest_balance was removed from the UI; treat it as snowball
    sel.value = v === "lowest_balance" ? "snowball" : v;
  }
  $("#apply-debt-plan")?.addEventListener("click", async () => {
    await savePrefs({
      debt_strategy: $("#debt-strategy").value,
      extra_debt: Number($("#extra-debt").value || 0),
    });
  });
}

function renderStrategy() {
  const s = STATE.summary;
  const c = STATE.coach || { overview: [], cuts: [] };
  const llm = STATE.llm || { providers: {}, enabled: false };
  const shown = s.show_strategy !== false;
  const cuts = (c.cuts || [])
    .map((x) => `<article class="tip info"><h4>${escapeHtml(x.title)}</h4><p>${escapeHtml(x.body)}</p></article>`)
    .join("");
  const overview = (c.overview || []).map((p) => `<p>${escapeHtml(p)}</p>`).join("");
  const providerOpts = Object.entries(llm.providers || {})
    .map(
      ([k, v]) =>
        `<option value="${k}" ${llm.provider === k ? "selected" : ""}>${escapeHtml(v.label)}</option>`
    )
    .join("");

  $("#tab-strategy").innerHTML = `
    <div class="toolbar">
      <h2 style="margin:0">Overview / Strategy</h2>
      <label class="buffer">
        <input id="toggle-strategy" type="checkbox" ${shown ? "checked" : ""} style="width:auto" />
        Show this tab
      </label>
    </div>
    <p class="muted">Built-in coach uses only local rules and your numbers. Advanced Coach is optional and calls an LLM you configure — key stays on this machine in the app database.</p>
    <div class="grid cols-2">
      <article class="card">
        <h2>Where you stand</h2>
        ${overview || '<p class="muted">Add accounts to get a briefing.</p>'}
        <p class="muted">Recommended starting point: <strong>${escapeHtml(c.recommended_strategy || "avalanche")}</strong>${c.focus ? " · extra goes to " + escapeHtml(c.focus) : ""}.</p>
      </article>
      <article class="card">
        <h2>Places to cut / flex</h2>
        <div class="advice">${cuts}</div>
      </article>
    </div>
    <article class="card" style="margin-top:14px">
      <h2>Encouragement</h2>
      <p>${escapeHtml(c.encouragement || "")}</p>
    </article>
    <article class="card" style="margin-top:14px">
      <h2>Advanced Coach (LLM)</h2>
      <p class="muted">OpenAI-compatible APIs: OpenAI, OpenRouter, Groq, local Ollama, or a custom base URL. Leave off to keep advice fully offline.</p>
      <div class="form-grid">
        <label class="full"><span style="display:flex;gap:8px;align-items:center"><input id="llm-enabled" type="checkbox" ${llm.enabled ? "checked" : ""} style="width:auto" /> Enable Advanced Coach</span></label>
        <label>Provider
          <select id="llm-provider">${providerOpts}</select>
        </label>
        <label>Model
          <input id="llm-model" type="text" value="${escapeAttr(llm.model || "")}" placeholder="gpt-4o-mini" />
        </label>
        <label class="full">Base URL
          <input id="llm-base-url" type="text" value="${escapeAttr(llm.base_url || "")}" placeholder="https://api.openai.com/v1" />
        </label>
        <label class="full">API key ${llm.has_api_key ? `(saved ${escapeHtml(llm.api_key_hint || "")})` : ""}
          <input id="llm-api-key" type="password" autocomplete="off" placeholder="${llm.has_api_key ? "Leave blank to keep saved key" : "sk-…"}" />
        </label>
      </div>
      <div class="form-actions" style="justify-content:flex-start">
        <button class="primary" id="save-llm">Save LLM settings</button>
      </div>
    </article>
    <article class="card" style="margin-top:14px">
      <h2>Ask the coach</h2>
      <p class="muted">Try: “avalanche or snowball?”, “what can I cut?”, “is this month safe?”, “should I invest instead?”</p>
      <div class="form-grid">
        <label class="full">Question
          <input id="coach-q" type="text" placeholder="Ask about payoff order, cuts, or this month…" />
        </label>
        <label class="full"><span style="display:flex;gap:8px;align-items:center"><input id="coach-advanced" type="checkbox" ${llm.enabled ? "" : "disabled"} style="width:auto" /> Use Advanced Coach (LLM) for this answer</span></label>
      </div>
      <div class="form-actions" style="justify-content:flex-start">
        <button class="primary" id="ask-coach">Ask</button>
      </div>
      <div id="coach-reply" class="advice" style="margin-top:12px"></div>
    </article>
  `;
  $("#toggle-strategy")?.addEventListener("change", async (e) => {
    await savePrefs({ show_strategy: e.target.checked });
  });
  $("#llm-provider")?.addEventListener("change", () => {
    const p = $("#llm-provider").value;
    const meta = (llm.providers || {})[p];
    if (meta) {
      if (meta.base_url) $("#llm-base-url").value = meta.base_url;
      if (meta.default_model) $("#llm-model").value = meta.default_model;
    }
  });
  $("#save-llm")?.addEventListener("click", async () => {
    const key = $("#llm-api-key").value.trim();
    const partial = {
      llm_enabled: $("#llm-enabled").checked,
      llm_provider: $("#llm-provider").value,
      llm_base_url: $("#llm-base-url").value.trim(),
      llm_model: $("#llm-model").value.trim(),
    };
    if (key) partial.llm_api_key = key;
    await savePrefs(partial);
  });
  $("#ask-coach")?.addEventListener("click", async () => {
    const q = $("#coach-q").value;
    const advanced = $("#coach-advanced")?.checked && llm.enabled;
    try {
      const res = await api("/api/coach", {
        method: "POST",
        body: JSON.stringify({ question: q, advanced: !!advanced }),
      });
      const label = res.mode === "advanced" ? "Advanced Coach" : "Local coach";
      $("#coach-reply").innerHTML = `<article class="tip ok"><h4>${label}</h4><p style="white-space:pre-wrap">${escapeHtml(res.reply)}</p></article>`;
    } catch (err) {
      $("#coach-reply").innerHTML = `<article class="tip critical"><h4>Coach error</h4><p>${escapeHtml(err.message)}</p></article>`;
    }
  });
}

function renderBudget() {
  const s = STATE.summary;
  const a = STATE.allocation || {};
  const b = s.budget || { buckets: [] };
  const rec = a.recommended || {};
  const mode = a.mode || "auto";
  const buckets = (a.buckets || b.buckets || [])
    .map((x) => {
      const key = x.key || "";
      return `<div class="row">
        <div style="flex:1">
          <div>${escapeHtml(x.name)} · ${x.pct}%</div>
          <div class="bar"><span style="width:${a.leftover > 0 ? Math.max(x.pct, 0) : 0}%"></span></div>
        </div>
        <strong class="amt">${money(x.amount)}</strong>
        ${key ? `<input data-alloc-pct="${key}" type="number" min="0" max="100" step="5" value="${x.pct}" style="width:72px" />` : ""}
      </div>`;
    })
    .join("");

  const runway = a.runway_months;
  const target = a.safety_months_target || 3;
  const runwayPct = runway == null || target <= 0 ? 0 : Math.min(100, Math.round((runway / target) * 100));
  const hot = (a.high_apr || []).map((d) => `${escapeHtml(d.name)} ${d.apr}%`).join(", ");

  const byCat = {};
  for (const e of STATE.events.filter((ev) => ev.date.startsWith(s.month) && ev.direction === "out")) {
    const c = e.category || "uncategorized";
    byCat[c] = (byCat[c] || 0) + e.amount;
  }
  const cats = Object.entries(byCat)
    .sort((x, y) => y[1] - x[1])
    .map(([name, amt]) => `<div class="row"><span>${escapeHtml(name)}</span><span class="amt neg">${money(amt)}</span></div>`)
    .join("");

  $("#tab-budget").innerHTML = `
    <div class="grid cols-2">
      <article class="card">
        <h2>Leftover jobs</h2>
        <p class="muted">${escapeHtml(a.note || b.note || "")}</p>
        <div class="row"><span>Assignable leftover</span><strong class="amt ${clsAmt(a.leftover)}">${money(a.leftover)}</strong></div>
        <p class="muted">${escapeHtml(a.why || "")}</p>
        <p class="muted">Mode: <strong>${mode === "manual" ? "your split" : "recommended"}</strong>${
          rec.debt != null
            ? ` · suggested ${rec.debt}/${rec.safety}/${rec.build}`
            : ""
        }</p>
        ${buckets}
        <div class="form-grid" style="margin-top:12px">
          <label>Safety target (months of fixed bills)
            <input id="safety-months" type="number" min="1" max="12" step="1" value="${target}" />
          </label>
        </div>
        <div class="form-actions" style="justify-content:flex-start;flex-wrap:wrap">
          <button class="primary" id="save-alloc">Save split</button>
          <button class="ghost" id="use-rec-alloc">Use recommended</button>
          <button class="ghost" id="apply-alloc">Apply as transfers</button>
        </div>
        <p class="muted" style="margin:10px 0 0">Apply sets extra debt to the Debt extra job and writes monthly “Leftover: Safety” / “Leftover: Build” transfers from checking. Those then show on the calendar.</p>
      </article>
      <article class="card">
        <h2>Emergency fund runway</h2>
        <p class="muted">${escapeHtml((a.runway && a.runway.headline) || "")}</p>
        <div class="runway-num" style="font-size:28px">${runway == null ? "—" : runway.toFixed(1)} <span class="muted">/ ${target} mo</span></div>
        <div class="row"><span>Fixed bills / month</span><span class="amt">${money(a.fixed_monthly || 0)}</span></div>
        <div class="row"><span>Savings in the fund</span><span class="amt">${money(a.savings || 0)}</span></div>
        <div class="bar thick" style="margin:10px 0 14px"><span style="width:${runwayPct}%"></span></div>
        <div class="row"><span>Cash still needed for target</span><span class="amt">${money(a.safety_gap_cash || 0)}</span></div>
        <p class="muted">${
          a.runway && a.runway.months_to_target
            ? `At the Safety job ${money(a.runway.safety_monthly)}/mo, target in ~${a.runway.months_to_target} months.`
            : "Checking buffer is not this fund."
        }</p>
        ${hot ? `<p class="warn">High-APR: ${hot}</p>` : `<p class="muted">No 15%+ APR balances.</p>`}
        <h2 style="margin-top:18px">Committed spend by category</h2>
        ${cats || '<p class="muted">Add bills to see category totals.</p>'}
      </article>
    </div>
  `;
  $("#save-alloc")?.addEventListener("click", async () => {
    const debt = Number($('[data-alloc-pct="debt"]')?.value || 0);
    const safety = Number($('[data-alloc-pct="safety"]')?.value || 0);
    const build = Number($('[data-alloc-pct="build"]')?.value || 0);
    await savePrefs({
      alloc_mode: "manual",
      alloc_debt_pct: debt,
      alloc_safety_pct: safety,
      alloc_build_pct: build,
      safety_months: Number($("#safety-months")?.value || target),
    });
  });
  $("#use-rec-alloc")?.addEventListener("click", async () => {
    await savePrefs({
      alloc_mode: "auto",
      safety_months: Number($("#safety-months")?.value || target),
    });
  });
  $("#apply-alloc")?.addEventListener("click", async () => {
    if (
      !confirm(
        "Set extra debt to the Debt extra job and create/update Safety and Build transfers from checking?"
      )
    )
      return;
    const res = await api("/api/allocation/apply", { method: "POST", body: "{}" });
    await load();
    alert((res.notes || []).join("\n") || "Applied.");
  });
}

function openSinkingForm(existing) {
  const checking = STATE.accounts.find((a) => a.type === "checking");
  const savings = STATE.accounts.find((a) => a.type === "savings");
  const f = existing || {
    name: "",
    vendor: "",
    category: "other",
    target_amount: 0,
    reserved: 0,
    next_date: "",
    cadence: "yearly",
    account_id: checking?.id || "",
    dest_account_id: savings?.id || "",
    active: 1,
    notes: "",
  };
  const acctOpts = (sel) =>
    STATE.accounts
      .map((a) => `<option value="${a.id}" ${Number(sel) === a.id ? "selected" : ""}>${escapeHtml(a.name)}</option>`)
      .join("");
  openModal(existing ? "Edit sinking fund" : "Add known hit", `
    <div class="form-grid">
      <label>Name<input name="name" required value="${escapeAttr(f.name)}" placeholder="Holiday gifts" /></label>
      <label>Vendor<input name="vendor" value="${escapeAttr(f.vendor || "")}" /></label>
      <label>Target amount<input name="target_amount" type="number" step="0.01" required value="${f.target_amount || 0}" /></label>
      <label>Already set aside<input name="reserved" type="number" step="0.01" value="${f.reserved || 0}" /></label>
      <label class="full">Next due date
        <input name="next_date" type="text" required placeholder="YYYY-MM-DD" pattern="\\d{4}-\\d{2}-\\d{2}" value="${escapeAttr(f.next_date || f.due || "")}" />
      </label>
      <label>Cadence
        <select name="cadence">
          <option value="yearly" ${f.cadence === "yearly" ? "selected" : ""}>yearly</option>
          <option value="once" ${f.cadence === "once" ? "selected" : ""}>once</option>
        </select>
      </label>
      <label>Category
        <select name="category">
          ${["insurance", "transport", "other", "housing", "utilities"].map((c) => `<option ${f.category === c ? "selected" : ""}>${c}</option>`).join("")}
        </select>
      </label>
      <label>Reserve from
        <select name="account_id"><option value="">—</option>${acctOpts(f.account_id)}</select>
      </label>
      <label>Hold in
        <select name="dest_account_id"><option value="">—</option>${acctOpts(f.dest_account_id)}</select>
      </label>
      <label class="full">Notes<input name="notes" value="${escapeAttr(f.notes || "")}" /></label>
    </div>
    <p class="muted">Monthly reserve = what’s left ÷ months until due (minimum 1 month). Put reserve on the calendar after saving.</p>
    <div class="form-actions"><button type="submit" class="primary">Save fund</button></div>
  `, async (fd) => {
    const body = {
      name: fd.get("name"),
      vendor: fd.get("vendor"),
      category: fd.get("category"),
      target_amount: Number(fd.get("target_amount") || 0),
      reserved: Number(fd.get("reserved") || 0),
      next_date: fd.get("next_date"),
      cadence: fd.get("cadence"),
      account_id: fd.get("account_id") ? Number(fd.get("account_id")) : null,
      dest_account_id: fd.get("dest_account_id") ? Number(fd.get("dest_account_id")) : null,
      active: 1,
      notes: fd.get("notes"),
    };
    if (existing) await api("/api/sinking/" + existing.id, { method: "PUT", body: JSON.stringify(body) });
    else await api("/api/sinking", { method: "POST", body: JSON.stringify(body) });
    closeModal();
    await load();
  });
}

function openAccountForm(existing) {
  const a = existing || {
    name: "",
    institution: "",
    type: "checking",
    balance: 0,
    apr: "",
    min_payment: "",
    due_day: "",
    notes: "",
  };
  openModal(existing ? "Edit account" : "Add account", `
    <div class="form-grid">
      <label>Name<input name="name" required value="${escapeAttr(a.name)}" /></label>
      <label>Institution<input name="institution" value="${escapeAttr(a.institution || "")}" /></label>
      <label>Type
        <select name="type">
          ${["checking", "savings", "brokerage", "crypto", "credit", "loan", "other"]
            .map((t) => `<option ${a.type === t ? "selected" : ""}>${t}</option>`)
            .join("")}
        </select>
      </label>
      <label>Balance<input name="balance" type="number" step="0.01" value="${a.balance}" /></label>
      <label>APR %<input name="apr" type="number" step="0.01" value="${a.apr ?? ""}" /></label>
      <label>Minimum payment<input name="min_payment" type="number" step="0.01" value="${a.min_payment ?? ""}" /></label>
      <label>Due day<input name="due_day" type="number" min="1" max="31" value="${a.due_day ?? ""}" /></label>
      <label class="full">Notes<input name="notes" value="${escapeAttr(a.notes || "")}" /></label>
    </div>
    <div class="form-actions"><button type="submit" class="primary">Save account</button></div>
  `, async (fd) => {
    const body = {
      name: fd.get("name"),
      institution: fd.get("institution"),
      type: fd.get("type"),
      balance: Number(fd.get("balance") || 0),
      apr: fd.get("apr") === "" ? null : Number(fd.get("apr")),
      min_payment: fd.get("min_payment") === "" ? null : Number(fd.get("min_payment")),
      due_day: fd.get("due_day") === "" ? null : Number(fd.get("due_day")),
      notes: fd.get("notes"),
    };
    if (existing) await api("/api/accounts/" + existing.id, { method: "PUT", body: JSON.stringify(body) });
    else await api("/api/accounts", { method: "POST", body: JSON.stringify(body) });
    closeModal();
    await load();
  });
}

function openObligationForm(existing) {
  const o = existing || {
    name: "",
    vendor: "",
    account_id: STATE.accounts[0]?.id || "",
    dest_account_id: "",
    amount: 0,
    direction: "out",
    cadence: "monthly",
    due_day: 1,
    due_day_2: "",
    next_date: "",
    end_date: "",
    category: "",
    active: 1,
  };
  const acctOpts = STATE.accounts
    .map((a) => `<option value="${a.id}" ${Number(o.account_id) === a.id ? "selected" : ""}>${escapeHtml(a.name)}</option>`)
    .join("");
  openModal(existing ? "Edit obligation" : "Add bill or paycheck", `
    <div class="form-grid">
      <label>Name<input name="name" required value="${escapeAttr(o.name)}" /></label>
      <label>Vendor<input name="vendor" value="${escapeAttr(o.vendor || "")}" /></label>
      <label>From account<select name="account_id">${acctOpts}</select></label>
      <label>Transfer to
        <select name="dest_account_id">
          <option value="">— none —</option>
          ${STATE.accounts.map((a) => `<option value="${a.id}" ${Number(o.dest_account_id) === a.id ? "selected" : ""}>${escapeHtml(a.name)}</option>`).join("")}
        </select>
      </label>
      <label>Amount<input name="amount" type="number" step="0.01" required value="${o.amount}" /></label>
      <label>Direction
        <select name="direction">
          <option value="out" ${o.direction === "out" ? "selected" : ""}>Payout</option>
          <option value="in" ${o.direction === "in" ? "selected" : ""}>Income</option>
        </select>
      </label>
      <label>Cadence
        <select name="cadence" id="ob-cadence">
          ${["monthly", "semimonthly", "weekly", "biweekly", "yearly", "once"]
            .map((c) => `<option value="${c}" ${o.cadence === c ? "selected" : ""}>${c === "semimonthly" ? "semimonthly (2 days/month)" : c}</option>`).join("")}
        </select>
      </label>
      <label id="lbl-due-day">First payday (day of month)
        <input name="due_day" type="number" min="1" max="31" value="${o.due_day ?? 15}" />
      </label>
      <label id="lbl-due-day-2">Second payday
        <select name="due_day_2">
          <option value="-1" ${o.due_day_2 == null || Number(o.due_day_2) === -1 ? "selected" : ""}>Last weekday of month</option>
          ${Array.from({ length: 31 }, (_, i) => i + 1)
            .map((d) => `<option value="${d}" ${Number(o.due_day_2) === d ? "selected" : ""}>${d}</option>`)
            .join("")}
        </select>
      </label>
      <label id="lbl-next-date" class="full">Anchor / one-time date
        <input name="next_date" type="text" inputmode="numeric" placeholder="YYYY-MM-DD" pattern="\\d{4}-\\d{2}-\\d{2}" value="${escapeAttr(o.next_date || "")}" />
      </label>
      <label>Category
        <select name="category">
          ${["housing", "utilities", "insurance", "debt", "subscriptions", "income", "savings", "food", "transport", "other"]
            .map((c) => `<option ${o.category === c ? "selected" : ""}>${c}</option>`).join("")}
        </select>
      </label>
      <label>Status
        <select name="status" id="ob-status">
          <option value="active" ${o.active && !o.end_date ? "selected" : ""}>Active (ongoing)</option>
          <option value="ends" ${o.active && o.end_date ? "selected" : ""}>Ends on date</option>
          <option value="cancelled" ${!o.active ? "selected" : ""}>Cancelled / completed</option>
        </select>
      </label>
      <label id="lbl-end-date">End date (last charge)
        <input name="end_date" type="text" inputmode="numeric" placeholder="YYYY-MM-DD" pattern="\\d{4}-\\d{2}-\\d{2}" value="${escapeAttr(o.end_date || "")}" />
      </label>
      <p class="muted full" style="margin:0">Semimonthly paychecks: 15th + last weekday (weekends roll to Friday). Set an end date so the bill stops after that day but stays in history. Cancelled/completed removes future hits; past paid dates remain if an end date is set.</p>
    </div>
    <div class="form-actions"><button type="submit" class="primary">Save obligation</button></div>
  `, async (fd) => {
    const body = {
      name: fd.get("name"),
      vendor: fd.get("vendor"),
      account_id: Number(fd.get("account_id")),
      dest_account_id: fd.get("dest_account_id") ? Number(fd.get("dest_account_id")) : null,
      amount: Number(fd.get("amount")),
      direction: fd.get("direction"),
      cadence: fd.get("cadence"),
      due_day: fd.get("due_day") === "" ? null : Number(fd.get("due_day")),
      due_day_2: fd.get("due_day_2") === "" ? null : Number(fd.get("due_day_2")),
      next_date: fd.get("next_date") || null,
      end_date: fd.get("end_date") || null,
      category: fd.get("category"),
      active: 1,
    };
    const status = fd.get("status");
    if (status === "cancelled") {
      body.active = 0;
      if (!body.end_date) {
        body.end_date = STATE.summary.today;
      }
    } else if (status === "ends") {
      body.active = 1;
      if (!body.end_date) {
        alert("Pick an end date (YYYY-MM-DD) for when this bill’s last charge hits.");
        throw new Error("end_date required");
      }
    } else {
      body.active = 1;
      body.end_date = null;
    }
    if (existing) await api("/api/obligations/" + existing.id, { method: "PUT", body: JSON.stringify(body) });
    else await api("/api/obligations", { method: "POST", body: JSON.stringify(body) });
    closeModal();
    await load();
  });
}

function openImportForm() {
  const sample = `{
  "replace": true,
  "buffer": 750,
  "household": "My household",
  "accounts": [
    {"name": "Checking", "institution": "Bank", "type": "checking", "balance": 2500},
    {"name": "Savings", "institution": "Bank", "type": "savings", "balance": 8000},
    {"name": "Visa", "institution": "Chase", "type": "credit", "balance": -1200, "apr": 22.9, "min_payment": 50, "due_day": 14}
  ],
  "obligations": [
    {"name": "Paycheck", "account": "Checking", "amount": 2400, "direction": "in", "cadence": "semimonthly", "due_day": 15, "due_day_2": -1, "category": "income"},
    {"name": "Rent", "account": "Checking", "amount": 1600, "direction": "out", "cadence": "monthly", "due_day": 1, "category": "housing"},
    {"name": "Visa min", "account": "Checking", "amount": 50, "direction": "out", "cadence": "monthly", "due_day": 14, "category": "debt"},
    {"name": "Netflix", "account": "Checking", "amount": 15.49, "direction": "out", "cadence": "monthly", "due_day": 4, "category": "subscriptions"}
  ]
}`;
  openModal("Bulk import (JSON)", `
    <p class="muted">Paste accounts and bills in one shot. Use account <strong>names</strong> on obligations. Set <code>replace: true</code> to wipe existing data first.</p>
    <div class="form-grid">
      <label class="full">JSON
        <textarea name="payload" spellcheck="false" style="min-height:280px;font-family:ui-monospace,monospace;font-size:12px">${escapeAttr(sample)}</textarea>
      </label>
    </div>
    <div class="form-actions"><button type="submit" class="primary">Import</button></div>
  `, async (fd) => {
    let payload;
    try {
      payload = JSON.parse(String(fd.get("payload") || ""));
    } catch (err) {
      alert("Invalid JSON: " + err.message);
      throw err;
    }
    const res = await api("/api/import", { method: "POST", body: JSON.stringify(payload) });
    closeModal();
    await load();
    alert(`Imported ${res.accounts} accounts and ${res.obligations} obligations.`);
  });
}

function openModal(title, html, onSubmit) {
  $("#modal-title").textContent = title;
  $("#modal-form").innerHTML = html;
  $("#modal").classList.remove("hidden");
  $("#modal-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await onSubmit(new FormData(e.target));
    } catch (_) {
      /* keep modal open on validation/import errors */
    }
  };
  // Keep native/OS date widgets and number fields from bubbling "outside" clicks that close the dialog.
  const card = $("#modal .modal-card");
  if (card) {
    card.onmousedown = (e) => e.stopPropagation();
    card.onclick = (e) => e.stopPropagation();
  }
}
function closeModal() {
  $("#modal").classList.add("hidden");
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function escapeAttr(s) {
  return escapeHtml(s);
}

$$("#tabs button").forEach((btn) => {
  btn.onclick = () => {
    $$("#tabs button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".panel").forEach((p) => p.classList.remove("active"));
    $("#tab-" + btn.dataset.tab).classList.add("active");
  };
});
$("#modal-close").onclick = closeModal;
$("#modal").addEventListener("mousedown", (e) => {
  // Only close when pressing on the dimmed backdrop, not the card or OS date UI.
  if (e.target.id === "modal") closeModal();
});
$("#save-settings").onclick = async () => {
  await savePrefs({});
};

load().catch((err) => {
  document.querySelector("main").innerHTML = `<article class="card"><h2>Could not load</h2><p>${escapeHtml(err.message)}</p></article>`;
});
