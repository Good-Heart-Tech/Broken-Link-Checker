// SPDX-License-Identifier: AGPL-3.0-or-later
// Broken Link Checker front end. Plain JavaScript, no build step.
// Scanned content is untrusted: everything is added with textContent, never innerHTML.
import { toCsv, toTsv, toMarkdown, toJson, download, copyText } from "/export.js";

const $ = (id) => document.getElementById(id);
const PHASES = {
  queued: "Waiting for a free spot",
  profile: "Looking at your website",
  crawl: "Finding pages and checking links",
  second_chance: "Double-checking links that blocked our first try",
};
const KINDS = { a: "Link", area: "Link", img: "Image", script: "Script", link: "Stylesheet", iframe: "Frame", video: "Media", audio: "Media", source: "Media", sitemap: "Sitemap" };
const ICON = { broken: "✕", blocked: "?", warning: "!", ok: "✓", skipped: "–" };
const FILE_EXT = /\.(?:jpe?g|png|gif|webp|svg|ico|avif|css|js|pdf|docx?|xlsx?|pptx?|zip|mp[34]|woff2?)$/i;

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
const plural = (n, one, many) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
const hostOf = (u) => { try { return new URL(u).hostname; } catch { return ""; } };
const pathOf = (u) => { try { const x = new URL(u); return (x.pathname + x.search) || "/"; } catch { return u; } };
const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

const S = fresh();
function fresh() {
  return { id: null, es: null, kind: "scan", site: "", mode: "quick", rows: [], newRows: [], profile: null, stats: {}, hostNotes: [],
    partial: null, truncated: false, jsNotice: false, done: false, ignored: new Set(), okHosts: new Set(), limit: {}, recheck: null, paused: false };
}

// ---------- views ----------
function show(view) {
  $("start").hidden = view !== "start";
  $("progress").hidden = view !== "progress";
  $("results").hidden = !(view === "results" || (view === "progress" && S.rows.length > 0));
  $("failure").hidden = view !== "failure";
}
function toast(msg) { $("toast").textContent = msg; $("sr-status").textContent = msg; }

// ---------- search bar ----------
// The button says "Scan again" when the address is the site we just scanned, otherwise "Scan".
const normHost = (v) => { try { return new URL(/^https?:\/\//i.test(v) ? v : "https://" + v).hostname.toLowerCase().replace(/^www\./, ""); } catch { return ""; } };
function updateButton() {
  const typed = $("site-url").value.trim();
  $("scan-btn").textContent = S.site && typed && normHost(typed) === normHost(S.site) ? "Scan again" : "Scan";
}
$("site-url").addEventListener("input", updateButton);

// Clear everything from the previous scan so nothing old is left on the page.
function wipe() {
  if (S.es) S.es.close();
  if (S.id && !S.done) fetch(`/api/scans/${S.id}/cancel`, { method: "POST" }).catch(() => {});
  Object.assign(S, fresh());
  for (const id of ["t-broken", "t-blocked", "t-warn", "t-ok", "t-skip", "banners", "summary"]) $(id).replaceChildren();
  $("q").value = "";
  $("q-ok").value = "";
  $("filter").value = "all";
  $("group").checked = false;
  $("ex-all").checked = false;
  $("toast").textContent = "";
  $("platform-tip").hidden = true;
  $("unignore").hidden = true;
  document.querySelectorAll("details.fold").forEach((d) => (d.open = false));
}

$("scan-form").addEventListener("submit", (e) => { e.preventDefault(); startScan(); });

async function startScan() {
  const url = $("site-url").value.trim();
  const err = $("form-error");
  err.hidden = true;
  if (!url) { err.textContent = "Please enter your website address."; err.hidden = false; $("site-url").focus(); return; }
  const body = {
    url, scope: document.querySelector("input[name=scope]:checked").value,
    mode: document.querySelector("input[name=mode]:checked").value, check_social: $("check-social").checked,
  };
  $("scan-btn").disabled = true;
  try {
    const r = await fetch("/api/scans", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { err.textContent = data.detail || "Something went wrong. Please try again."; err.hidden = false; return; }
    wipe();
    Object.assign(S, { mode: body.mode, kind: "scan", site: url });
    updateButton();
    $("options").open = false;
    begin(data.id, `Scanning ${url.replace(/^https?:\/\//, "")}`, data.position);
  } catch {
    err.textContent = "We could not reach the server. Please check your connection and try again.";
    err.hidden = false;
  } finally {
    $("scan-btn").disabled = false;
  }
}

const pre = new URLSearchParams(location.search).get("url");
if (pre) $("site-url").value = pre;

function begin(id, title, position) {
  S.id = id;
  $("progress-title").textContent = title;
  $("phase").textContent = position > 0 ? `You are number ${position} in line. We will start soon.` : PHASES.profile;
  $("bar").removeAttribute("value");
  for (const k of ["c-pages", "c-broken", "c-blocked"]) $(k).textContent = "0";
  $("c-links").textContent = "0 of 0";
  $("c-time").textContent = "0:00";
  $("current").textContent = "";
  $("pause").textContent = "Pause";
  $("pause").disabled = $("stop").disabled = false;
  show("progress");
  $("progress-title").focus();
  connect(id);
}

// ---------- live stream ----------
function connect(id) {
  const es = new EventSource(`/api/scans/${id}/events`);
  S.es = es;
  const on = (name, fn) => es.addEventListener(name, (e) => fn(JSON.parse(e.data)));
  on("profile", (d) => { S.profile = d; });
  on("phase", (d) => { $("phase").textContent = PHASES[d.phase] || ""; $("sr-status").textContent = PHASES[d.phase] || ""; });
  on("queue", (d) => { $("phase").textContent = `You are number ${d.position} in line. We will start soon.`; });
  on("progress", onProgress);
  on("rows", (d) => {
    const into = S.kind === "recheck" ? S.newRows : S.rows;
    if (d.removeTargets && S.kind !== "recheck") {
      const gone = new Set(d.removeTargets);
      S.rows = S.rows.filter((r) => !(r.bucket === "blocked" && gone.has(r.target)));
    }
    into.push(...d.rows);
    if (S.kind !== "recheck") scheduleRender();
  });
  on("notice", (d) => { if (d.kind === "js_heavy") S.jsNotice = true; });
  on("done", (d) => { es.close(); if (S.kind === "scan") S.stats = d.stats; S.hostNotes = d.hostNotes || []; S.partial = d.partial ? d.partialReason : null; S.truncated = d.truncated; finish(); });
  on("scan_error", (d) => { es.close(); fail(d.message); });
  es.onerror = async () => {
    try {
      const r = await fetch(`/api/scans/${id}`);
      if (r.status === 404) { es.close(); fail("This scan expired or the service restarted. Please start again."); }
    } catch { /* browser keeps retrying */ }
  };
}

function onProgress(d) {
  if (S.kind !== "recheck") S.stats = d;
  S.paused = d.paused;
  const found = d.links_found || 0, checked = d.links_checked || 0;
  if (found > 0 && d.phase !== "profile") {
    $("bar").max = Math.max(found, 1);
    $("bar").value = Math.min(checked, found);
  }
  $("c-pages").textContent = (d.pages_scanned || 0).toLocaleString();
  $("c-links").textContent = `${checked.toLocaleString()} of ${found.toLocaleString()}${d.phase === "crawl" ? " found so far" : ""}`;
  $("c-broken").textContent = (d.broken || 0).toLocaleString();
  $("c-blocked").textContent = (d.blocked || 0).toLocaleString();
  $("c-time").textContent = clock(d.elapsed || 0);
  $("current").textContent = d.current || "";
  if (d.paused) $("phase").textContent = "Paused";
  if (S.kind !== "recheck" && S.rows.length) { $("results").hidden = false; scheduleRender(); }
}

$("pause").addEventListener("click", async () => {
  if (!S.id) return;
  const resume = S.paused;
  await fetch(`/api/scans/${S.id}/${resume ? "resume" : "pause"}`, { method: "POST" });
  $("pause").textContent = resume ? "Pause" : "Resume";
});
$("stop").addEventListener("click", async () => {
  if (!S.id) return;
  $("stop").disabled = $("pause").disabled = true;
  $("phase").textContent = "Stopping and gathering what we found";
  await fetch(`/api/scans/${S.id}/cancel`, { method: "POST" });
});

function fail(msg) {
  S.done = true;
  $("failure-msg").textContent = msg;
  show("failure");
}
$("failure-back").addEventListener("click", () => { $("failure").hidden = true; $("site-url").focus(); $("site-url").select(); });

function finish() {
  S.done = true;
  if (S.kind === "recheck") return finishRecheck();
  show("results");
  render();
  $("results-title").focus();
  const n = new Set(visible("broken").map((r) => r.target)).size;
  toast(n ? `Scan finished. ${plural(n, "broken link", "broken links")} found.` : "Scan finished. No broken links found.");
}

// ---------- results ----------
let pending = false;
function scheduleRender() {
  if (pending) return;
  pending = true;
  setTimeout(() => { pending = false; render(); }, 500);
}

const hidden = (r) => S.ignored.has(r.id) || S.okHosts.has(hostOf(r.target));
const visible = (bucket) => S.rows.filter((r) => r.bucket === bucket && !hidden(r));
const uniq = (rows) => new Set(rows.map((r) => r.target)).size;

function render() {
  $("results").hidden = false;
  const broken = visible("broken"), blocked = visible("blocked"), warn = visible("warning");
  const ok = S.rows.filter((r) => r.bucket === "ok"), skipped = S.rows.filter((r) => r.bucket === "skipped");
  const st = S.stats;
  $("results-title").textContent = S.kind === "recheck" ? "Re-check results" : `Results for ${S.site.replace(/^https?:\/\//, "").replace(/\/$/, "")}`;
  $("results-sub").textContent = S.done ? `${S.mode === "thorough" ? "Thorough" : "Quick"} scan finished in ${clock(st.elapsed || 0)}` : "Still scanning. Results update as we go.";

  // banners
  const b = $("banners");
  b.replaceChildren();
  if (S.partial === "time") b.append(h("p", { class: "banner" }, "We stopped at the 10 minute limit, so these results are partial."));
  else if (S.partial) b.append(h("p", { class: "banner info" }, "You stopped the scan early. These are the results so far."));
  if (S.truncated) b.append(h("p", { class: "banner" }, "This website has more than 5,000 links. We checked the first 5,000."));
  if (S.jsNotice) b.append(h("p", { class: "banner" }, "Some of this website's content loads with JavaScript, so we may have found fewer links than are really there."));
  if (S.done && S.mode === "quick" && blocked.length && S.kind === "scan") {
    b.append(h("p", { class: "banner info" }, `${plural(uniq(blocked), "link", "links")} blocked our quick check. A Thorough scan tries harder to verify them.`,
      h("button", { type: "button", class: "btn", onclick: () => { $("site-url").value = S.site; document.querySelector("input[name=mode][value=thorough]").checked = true; startScan(); } }, "Run a Thorough scan")));
  }

  // summary
  const sum = $("summary");
  sum.replaceChildren(
    stat("Pages scanned", (st.pages_scanned || 0).toLocaleString(), ""),
    stat("Links checked", (st.links_checked || 0).toLocaleString(), ""),
    stat("Broken", uniq(broken).toLocaleString(), "s-broken"),
    stat("Could not verify", uniq(blocked).toLocaleString(), "s-blocked"),
    stat("Worth a look", uniq(warn).toLocaleString(), "s-warn"),
    stat("Working", (S.done ? ok.length : st.ok || 0).toLocaleString(), "s-ok"),
  );
  if (S.profile && S.profile.id !== "unknown") {
    sum.prepend(h("div", { class: "stat" }, h("b", { text: S.profile.name }), h("span", { text: "Platform detected" })));
  }

  // un-ignore control
  const hiddenCount = S.ignored.size + S.okHosts.size;
  const un = $("unignore");
  un.hidden = !hiddenCount;
  un.textContent = `Show ${hiddenCount} hidden`;

  // platform tip
  const tip = $("platform-tip");
  if (S.profile && S.profile.fixSteps && broken.length) { tip.hidden = false; tip.textContent = `${S.profile.name} tip: ${S.profile.fixSteps}`; } else tip.hidden = true;

  // broken table
  const q = $("q").value.trim().toLowerCase(), f = $("filter").value;
  const shown = broken.filter((r) => {
    if (f === "internal" && r.external) return false;
    if (f === "external" && !r.external) return false;
    if (f === "files" && !(FILE_EXT.test(pathOf(r.target).split("?")[0]) || !["a", "area", "sitemap"].includes(r.element))) return false;
    return !q || [r.target, r.text, r.page, r.where, r.title, r.pageTitle].some((x) => (x || "").toLowerCase().includes(q));
  });
  const tb = $("t-broken");
  if (!broken.length) tb.replaceChildren(h("p", { class: "empty" }, S.done ? "No broken links found. Nice work." : "No broken links so far."));
  else if (!shown.length) tb.replaceChildren(h("p", { class: "muted" }, "Nothing matches your search."));
  else tb.replaceChildren($("group").checked ? groupView(shown) : rowTable(shown, "broken"));
  $("h-broken").textContent = broken.length ? `Broken links (${plural(uniq(broken), "link", "links")} in ${plural(broken.length, "place", "places")})` : "Broken links";

  // could not verify
  $("sec-blocked").hidden = !blocked.length;
  $("t-blocked").replaceChildren(...hostCards(blocked));

  // worth a look and working
  $("n-warn").textContent = plural(uniq(warn), "link", "links");
  $("t-warn").replaceChildren(warn.length ? rowTable(warn, "warn") : h("p", { class: "muted" }, "Nothing here."));
  $("sec-warn").hidden = !warn.length;
  $("n-ok").textContent = S.done ? plural(ok.length, "link", "links") : plural(st.ok || 0, "link so far", "links so far");
  renderOk(ok, skipped);
}

function stat(label, value, cls) { return h("div", { class: `stat ${cls}` }, h("b", { text: value }), h("span", { text: label })); }

function badge(r) {
  return h("span", { class: `badge b-${r.bucket}` }, h("i", { "aria-hidden": "true", text: ICON[r.bucket] }), r.title);
}

function copyBtn(text, label = "Copy link") {
  return h("button", { type: "button", class: "small-btn", onclick: async (e) => { const ok = await copyText(text); toast(ok ? "Copied" : "Could not copy"); e.target.blur(); } }, label);
}

function suggestion(r) {
  const s = r.suggest;
  if (!s) return null;
  if (s.kind === "did_you_mean") return h("p", {}, "Did you mean ", h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", text: pathOf(s.url) }), "? ", copyBtn(s.url, "Copy"));
  if (s.kind === "new_address") return h("p", {}, "Update the link to ", h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", text: s.url }), " ", copyBtn(s.url, "Copy"));
  if (s.kind === "archive") return h("p", {}, h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, "Look for it in the Internet Archive"));
  return null;
}

function cells(r, withFix = true) {
  const link = h("td", { "data-label": "Link" },
    h("a", { class: "url", href: r.target, target: "_blank", rel: "noopener noreferrer", text: r.target }),
    r.final ? h("span", { class: "sub", text: `Ends at ${r.final}` }) : null,
    h("div", { class: "url-actions" }, copyBtn(r.target)));
  const text = h("td", { "data-label": "Link text or element" },
    r.text, h("span", { class: "kind", text: KINDS[r.element] || r.element }),
    r.snippet ? h("details", { class: "snippet" }, h("summary", { text: "Show HTML" }), h("code", { text: r.snippet })) : null);
  const page = h("td", { "data-label": "Page it is on" },
    r.pageTitle ? h("strong", { text: r.pageTitle }) : null, r.pageTitle ? h("br") : null,
    r.page ? h("a", { href: r.page, target: "_blank", rel: "noopener noreferrer", text: pathOf(r.page) }) : "",
    r.editUrl ? h("div", { class: "url-actions" }, h("a", { class: "sub", href: r.editUrl, target: "_blank", rel: "noopener noreferrer" }, "Edit this page in WordPress")) : null);
  const fix = h("td", { class: "fix", "data-label": "How to fix" },
    h("p", { text: r.fix || r.explain }), suggestion(r),
    h("button", { type: "button", class: "small-btn", onclick: () => { S.ignored.add(r.id); render(); } }, "Ignore"));
  return [h("td", { "data-label": "Status" }, badge(r), r.code ? h("span", { class: "code", text: `Code ${r.code}` }) : null), link, text, h("td", { "data-label": "Where on the page", text: r.where || "" }), page, withFix ? fix : null];
}

function rowTable(rows, key) {
  const limit = (S.limit[key] ||= 200);
  const head = h("tr", {}, ...["Status", "Link", "Link text or element", "Where on the page", "Page it is on", "How to fix"].map((t) => h("th", { scope: "col", text: t })));
  const body = h("tbody", {}, rows.slice(0, limit).map((r) => h("tr", {}, ...cells(r))));
  const frag = document.createDocumentFragment();
  frag.append(h("table", { class: "tbl" }, h("thead", {}, head), body));
  if (rows.length > limit) frag.append(h("p", { class: "more" }, h("button", { type: "button", class: "btn", onclick: () => { S.limit[key] = limit + 300; render(); } }, `Show more (${(rows.length - limit).toLocaleString()} left)`)));
  return frag;
}

function groupView(rows) {
  const groups = new Map();
  for (const r of rows) (groups.get(r.target) || groups.set(r.target, []).get(r.target)).push(r);
  const limit = (S.limit.group ||= 100);
  const out = document.createDocumentFragment();
  [...groups.entries()].slice(0, limit).forEach(([target, list]) => {
    const first = list[0];
    const inner = h("div", { class: "inner" },
      h("p", { class: "fix", text: first.fix }), suggestion(first),
      h("table", { class: "tbl" },
        h("thead", {}, h("tr", {}, ...["Link text or element", "Where on the page", "Page it is on", ""].map((t) => h("th", { scope: "col", text: t })))),
        h("tbody", {}, list.map((r) => h("tr", {},
          h("td", { "data-label": "Link text or element" }, r.text, h("span", { class: "kind", text: KINDS[r.element] || r.element })),
          h("td", { "data-label": "Where on the page", text: r.where }),
          h("td", { "data-label": "Page it is on" }, r.pageTitle ? h("strong", { text: r.pageTitle + " " }) : null, h("a", { href: r.page, target: "_blank", rel: "noopener noreferrer", text: pathOf(r.page) })),
          h("td", {}, h("button", { type: "button", class: "small-btn", onclick: () => { S.ignored.add(r.id); render(); } }, "Ignore")))))));
    out.append(h("details", { class: "group" },
      h("summary", {}, badge(first), h("span", { text: target }), h("span", { class: "count", text: plural(list.length, "place", "places") })), inner));
  });
  if (groups.size > limit) out.append(h("p", { class: "more" }, h("button", { type: "button", class: "btn", onclick: () => { S.limit.group = limit + 100; render(); } }, "Show more")));
  return out;
}

function hostCards(blocked) {
  const by = new Map();
  for (const r of blocked) { const k = hostOf(r.target); (by.get(k) || by.set(k, []).get(k)).push(r); }
  return [...by.entries()].sort((a, b) => b[1].length - a[1].length).map(([host, rows]) => {
    const vendor = rows.find((r) => r.vendor)?.vendor;
    const n = uniq(rows);
    const why = vendor ? `${host} uses ${vendor} bot protection and blocked our check` : `${host} would not let us check`;
    return h("div", { class: "hostcard" },
      h("h4", { text: `${host} (${plural(n, "link", "links")})` }),
      h("p", { text: `${why}. This is usually not a broken link. Open one in your browser to confirm.` }),
      h("div", { class: "btn-row" },
        h("a", { class: "btn", href: rows[0].target, target: "_blank", rel: "noopener noreferrer" }, "Open one to check"),
        h("button", { type: "button", class: "btn", onclick: () => { S.okHosts.add(host); render(); } }, "I checked, this site is fine")),
      h("details", {}, h("summary", { text: `Show the ${plural(rows.length, "place", "places")}` }), rowTable(rows, `host-${host}`)));
  });
}

function renderOk(ok, skipped) {
  const q = $("q-ok").value.trim().toLowerCase();
  const list = (rows, key) => {
    const m = rows.filter((r) => !q || r.target.toLowerCase().includes(q));
    const limit = (S.limit[key] ||= 300);
    const frag = document.createDocumentFragment();
    frag.append(h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, ...["Link", "Result", "Used on"].map((t) => h("th", { scope: "col", text: t })))),
      h("tbody", {}, m.slice(0, limit).map((r) => h("tr", {},
        h("td", { "data-label": "Link" }, h("a", { href: r.target, target: "_blank", rel: "noopener noreferrer", text: r.target })),
        h("td", { "data-label": "Result" }, h("span", { class: `badge b-${r.bucket}` }, h("i", { "aria-hidden": "true", text: ICON[r.bucket] }), r.title)),
        h("td", { "data-label": "Used on", text: plural(r.pages || 0, "page", "pages") }))))));
    if (m.length > limit) frag.append(h("p", { class: "more" }, h("button", { type: "button", class: "btn", onclick: () => { S.limit[key] = limit + 300; render(); } }, "Show more")));
    return frag;
  };
  $("t-ok").replaceChildren(ok.length ? list(ok, "ok") : h("p", { class: "muted", text: S.done ? "No working links to list." : "The full list appears when the scan finishes." }));
  $("h-skip").hidden = !skipped.length;
  $("t-skip").replaceChildren(skipped.length ? list(skipped, "skip") : "");
}

for (const id of ["q", "filter", "group"]) $(id).addEventListener("input", () => { S.limit = {}; render(); });
$("q-ok").addEventListener("input", () => { S.limit.ok = 300; render(); });
$("unignore").addEventListener("click", () => { S.ignored.clear(); S.okHosts.clear(); render(); });

// ---------- exports ----------
function exportRows() {
  const keep = ["broken", "blocked", "warning"];
  if ($("ex-all").checked) keep.push("ok", "skipped");
  return S.rows.filter((r) => keep.includes(r.bucket) && !hidden(r));
}
function meta() {
  return { site: S.site, date: new Date().toISOString().slice(0, 10), pages: S.stats.pages_scanned || 0, links: S.stats.links_checked || 0, platform: S.profile && S.profile.id !== "unknown" ? S.profile.name : "" };
}
function fname(ext) { return `broken-links-${hostOf(/^https?:/.test(S.site) ? S.site : "https://" + S.site) || "site"}-${meta().date}.${ext}`; }
$("ex-csv").addEventListener("click", () => { download(fname("csv"), toCsv(exportRows()), "text/csv;charset=utf-8"); toast("CSV downloaded"); });
$("ex-json").addEventListener("click", () => { download(fname("json"), toJson(exportRows(), meta()), "application/json"); toast("JSON downloaded"); });
$("ex-md").addEventListener("click", async () => toast((await copyText(toMarkdown(S.rows.filter((r) => !hidden(r)), meta()))) ? "Copied. Paste it into an email or ticket." : "Could not copy"));
$("ex-tsv").addEventListener("click", async () => toast((await copyText(toTsv(exportRows()))) ? "Copied. Paste it into Google Sheets or Excel." : "Could not copy"));
$("ex-print").addEventListener("click", () => { document.querySelectorAll("details.fold").forEach((d) => (d.open = true)); window.print(); });

// ---------- re-check ----------
$("recheck").addEventListener("click", async () => {
  const seen = new Set();
  const items = [];
  for (const r of S.rows.filter((x) => (x.bucket === "broken" || x.bucket === "blocked") && !hidden(x))) {
    const k = r.target + "|" + r.page;
    if (seen.has(k) || items.length >= 200) continue;
    seen.add(k);
    items.push({ target: r.target, page: r.page, text: r.text, element: r.element, where: r.where, snippet: r.snippet });
  }
  if (!items.length) { toast("Nothing to re-check."); return; }
  const res = await fetch("/api/recheck", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items, mode: S.mode, site: /^https?:/.test(S.site) ? S.site : "https://" + S.site }) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { toast(data.detail || "Could not start the re-check."); return; }
  S.recheck = { targets: new Set(items.map((i) => i.target)), count: new Set(items.map((i) => i.target)).size };
  S.kind = "recheck";
  S.newRows = [];
  S.done = false;
  $("progress-title").textContent = `Re-checking ${plural(S.recheck.count, "link", "links")}`;
  $("phase").textContent = PHASES.crawl;
  $("pause").disabled = $("stop").disabled = false;
  S.id = data.id;
  $("progress").hidden = false;
  connect(data.id);
});

function finishRecheck() {
  const targets = S.recheck.targets;
  const still = S.newRows.filter((r) => r.bucket === "broken" || r.bucket === "blocked" || r.bucket === "warning");
  S.rows = S.rows.filter((r) => !(r.bucket !== "ok" && r.bucket !== "skipped" && targets.has(r.target))).concat(S.newRows);
  const fixed = S.recheck.count - uniq(still.filter((r) => r.bucket !== "warning"));
  S.kind = "scan";
  S.done = true;
  $("progress").hidden = true;
  render();
  toast(`Re-checked ${plural(S.recheck.count, "link", "links")}. ${fixed} now ${fixed === 1 ? "works" : "work"}.`);
  S.recheck = null;
}
