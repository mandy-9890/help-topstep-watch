/* Topstep Watch — static dashboard, no dependencies. */
let DATA = null;
let pageFilter = { q: "", site: "all" };

const app = document.getElementById("app");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function rel(iso) {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  const m = s / 60, h = m / 60, d = h / 24;
  if (m < 60) return Math.round(m) + " min ago";
  if (h < 24) return Math.round(h) + " h ago";
  if (d < 30) return Math.round(d) + " d ago";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
const fmt = (iso) => iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
const siteBadge = (s) => `<span class="badge ${s}">${s === "topstep" ? "Topstep" : "TopstepX"}</span>`;
const kindBadge = (k) => `<span class="badge ${k}">${k.toUpperCase()}</span>`;
const pageHref = (url) => `#/page/${encodeURIComponent(url)}`;

function setActive(nav) {
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === nav));
}

/* ---------- views ---------- */

function viewHome() {
  setActive("home");
  const pages = DATA.pages.filter((p) => p.status === "active");
  const nT = pages.filter((p) => p.site === "topstep").length;
  const nX = pages.filter((p) => p.site === "topstepx").length;
  const ev = DATA.events;
  let html = `
    <h1>Topstep &amp; TopstepX help-center changes</h1>
    <p class="sub">Every rule &amp; platform doc update, with before/after diffs. Watching since ${fmt(DATA.baseline_at)}.</p>
    <div class="stats">
      <div class="stat"><div class="n">${pages.length}</div><div class="l">pages tracked</div></div>
      <div class="stat"><div class="n">${nT}</div><div class="l">Topstep help pages</div></div>
      <div class="stat"><div class="n">${nX}</div><div class="l">TopstepX help pages</div></div>
      <div class="stat"><div class="n">${ev.length}</div><div class="l">changes detected</div></div>
    </div>
    <h2>Recent changes</h2>`;
  if (!ev.length) {
    html += `<div class="empty">No changes detected yet.<br/>Baseline saved ${fmt(DATA.baseline_at)} — any edit to either help center will appear here with a before/after diff.<br/><br/><a href="#/pages">Browse all tracked pages →</a></div>`;
  } else {
    html += ev.slice(0, 40).map(eventCard).join("");
  }
  app.innerHTML = html;
}

function eventCard(e) {
  const inner = `
    <div class="title">${kindBadge(e.kind)} ${siteBadge(e.site)} ${esc(e.title)}</div>
    <div class="meta">detected ${rel(e.detected_at)}${e.kind === "changed" ? ` · page updated ${rel(e.new_lastmod)}` : ""} · <span>${esc(e.url)}</span></div>`;
  return e.kind === "changed"
    ? `<div class="card clickable" onclick="location.hash='#/change/${e.id}'">${inner}</div>`
    : `<div class="card clickable" onclick="location.hash='${pageHref(e.url)}'">${inner}</div>`;
}

function viewPages() {
  setActive("pages");
  app.innerHTML = `
    <h1>All tracked pages</h1>
    <p class="sub">Sorted by last update on the source site. Click a page for its content &amp; history.</p>
    <div class="controls">
      <input id="q" type="search" placeholder="Search pages… (e.g. loss limit, payout, api)" value="${esc(pageFilter.q)}"/>
      <button data-site="all">All</button>
      <button data-site="topstep">Topstep</button>
      <button data-site="topstepx">TopstepX</button>
    </div>
    <div id="plist"></div>`;
  const input = document.getElementById("q");
  input.addEventListener("input", () => { pageFilter.q = input.value; renderPageList(); });
  document.querySelectorAll("[data-site]").forEach((b) => {
    b.addEventListener("click", () => { pageFilter.site = b.dataset.site; renderPageList(); });
  });
  renderPageList();
}

function renderPageList() {
  document.querySelectorAll("[data-site]").forEach((b) => b.classList.toggle("on", b.dataset.site === pageFilter.site));
  const q = pageFilter.q.toLowerCase();
  const rows = DATA.pages.filter((p) =>
    (pageFilter.site === "all" || p.site === pageFilter.site) &&
    (!q || (p.title + " " + p.url).toLowerCase().includes(q))
  );
  const el = document.getElementById("plist");
  if (!rows.length) { el.innerHTML = `<div class="empty">No pages match.</div>`; return; }
  el.innerHTML = `<table><thead><tr><th>Page</th><th>Site</th><th>Updated</th></tr></thead><tbody>` +
    rows.map((p) => `
      <tr onclick="location.hash='${pageHref(p.url)}'" style="cursor:pointer">
        <td><div class="t">${esc(p.title)} ${p.status !== "active" ? `<span class="badge removed">${p.status}</span>` : ""}</div><div class="u">${esc(p.url)}</div></td>
        <td>${siteBadge(p.site)}</td>
        <td class="when" title="${esc(p.lastmod || "")}">${rel(p.lastmod)}</td>
      </tr>`).join("") + `</tbody></table>`;
}

function viewChange(id) {
  setActive("home");
  const e = DATA.events.find((x) => x.id === Number(id));
  if (!e) { app.innerHTML = `<div class="empty">Change not found.</div>`; return; }
  let html = `
    <a class="back" href="#/">← Dashboard</a>
    <h1>${kindBadge(e.kind)} ${esc(e.title)}</h1>
    <p class="sub">${siteBadge(e.site)} <a href="${esc(e.url)}" target="_blank" rel="noopener">open source page ↗</a> · <a href="${pageHref(e.url)}">page history</a></p>
    <div class="card">
      <div class="meta">Change detected: <b>${fmt(e.detected_at)}</b></div>
      ${e.kind === "changed" ? `<div class="meta">Source page updated: ${fmt(e.old_lastmod)} → <b>${fmt(e.new_lastmod)}</b></div>` : ""}
    </div>`;
  if (e.diff) {
    html += `<p class="legend"><span class="r">red = earlier (removed)</span> · <span class="g">green = current (added)</span></p>` + renderDiff(e.diff);
  } else {
    html += `<div class="empty">Page was ${e.kind}. <a href="${pageHref(e.url)}">View page →</a></div>`;
  }
  app.innerHTML = html;
}

function renderDiff(diff) {
  const lines = diff.split("\n").map((l) => {
    let cls = "ctx";
    if (l.startsWith("+++") || l.startsWith("---") || l.startsWith("@@")) cls = "h";
    else if (l.startsWith("+")) cls = "add";
    else if (l.startsWith("-")) cls = "del";
    return `<div class="${cls}">${esc(l) || " "}</div>`;
  });
  return `<div class="diff">${lines.join("")}</div>`;
}

function viewPage(url) {
  setActive("pages");
  const p = DATA.pages.find((x) => x.url === url);
  if (!p) { app.innerHTML = `<div class="empty">Page not tracked.</div>`; return; }
  const evs = DATA.events.filter((e) => e.url === url);
  let html = `
    <a class="back" href="#/pages">← All pages</a>
    <h1>${esc(p.title)}</h1>
    <p class="sub">${siteBadge(p.site)} <a href="${esc(p.url)}" target="_blank" rel="noopener">open source page ↗</a></p>
    <div class="card">
      <div class="meta">Last updated on source: <b>${fmt(p.lastmod)}</b> (${rel(p.lastmod)})</div>
      <div class="meta">Tracking since: ${fmt(p.first_seen)} · last checked: ${rel(p.last_checked)}</div>
    </div>
    <h2>Change history</h2>`;
  html += evs.length
    ? evs.map(eventCard).join("")
    : `<div class="empty">No changes recorded yet — baseline saved ${fmt(p.first_seen)}.</div>`;
  html += `<h2>Current content (snapshot)</h2><div id="snap"><div class="loading">Loading content…</div></div>`;
  app.innerHTML = html;
  fetch(`p/${p.key}.json`)
    .then((r) => r.json())
    .then((d) => {
      const el = document.getElementById("snap");
      if (!el) return;
      el.innerHTML = d.content_html
        ? `<div class="page-content">${d.content_html}</div>`
        : `<pre class="content">${esc(d.content)}</pre>`;
    })
    .catch(() => {
      const el = document.getElementById("snap");
      if (el) el.innerHTML = `<div class="empty">Content unavailable.</div>`;
    });
}

function viewAbout() {
  setActive("about");
  app.innerHTML = `
    <h1>About Topstep Watch</h1>
    <p class="sub">An independent change tracker for Topstep's public documentation.</p>
    <div class="card">
      <p><b>What it watches</b></p>
      <ul>
        <li><a href="https://help.topstep.com/en/" target="_blank" rel="noopener">help.topstep.com</a> — program rules, Trading Combine &amp; Funded Account parameters, payout policy, loss limits, consistency rules</li>
        <li><a href="https://help.topstepx.com/" target="_blank" rel="noopener">help.topstepx.com</a> — platform docs, risk settings, trade limits, API, mobile</li>
      </ul>
      <p><b>How it works</b></p>
      <ul>
        <li>Both sites publish sitemaps with per-page update timestamps.</li>
        <li>An automated job checks them every 30 minutes. When a timestamp moves, the page is re-fetched and its content compared against the stored snapshot.</li>
        <li>Real edits are recorded as <span style="color:var(--red)">before</span>/<span style="color:var(--green)">after</span> diffs. New and deleted pages are flagged too.</li>
        <li>Site-rebuild timestamp bumps with identical content are ignored.</li>
      </ul>
      <p><b>Limitations</b></p>
      <ul>
        <li>History starts ${fmt(DATA.baseline_at)}; earlier versions were not publicly available.</li>
        <li>Checks run roughly every 30 minutes, not instantly.</li>
      </ul>
      <p>Not affiliated with or endorsed by Topstep. All content belongs to Topstep; this site only tracks changes to their public help pages.</p>
    </div>`;
}

/* ---------- router ---------- */

function route() {
  const h = location.hash || "#/";
  if (h.startsWith("#/change/")) viewChange(h.slice(9));
  else if (h.startsWith("#/page/")) viewPage(decodeURIComponent(h.slice(7)));
  else if (h === "#/pages") viewPages();
  else if (h === "#/about") viewAbout();
  else viewHome();
  window.scrollTo(0, 0);
}

fetch("data.json")
  .then((r) => r.json())
  .then((d) => {
    DATA = d;
    document.getElementById("foot-meta").textContent =
      `Last check: ${fmt(d.last_check)} · data generated ${rel(d.generated_at)}`;
    route();
  })
  .catch(() => { app.innerHTML = `<div class="empty">Failed to load data.json.</div>`; });

window.addEventListener("hashchange", route);
