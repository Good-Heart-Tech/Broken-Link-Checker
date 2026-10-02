// SPDX-License-Identifier: AGPL-3.0-or-later
// Export helpers. Pure functions: rows in, text out. Everything runs in the browser, nothing is uploaded.

const BUCKET_LABEL = { broken: "Broken", blocked: "Could not verify", warning: "Worth a look", ok: "Working", skipped: "Not checked" };

export function sortRows(rows) {
  return [...rows].sort((a, b) => (a.page || "").localeCompare(b.page || "") || a.target.localeCompare(b.target));
}

function betterAddress(r) {
  return r.suggest && r.suggest.kind !== "archive" ? r.suggest.url : "";
}

function fixText(r) {
  let t = r.fix || "";
  if (r.suggest && r.suggest.kind === "did_you_mean") t += ` Did you mean ${r.suggest.url}?`;
  if (r.suggest && r.suggest.kind === "new_address") t += ` New address: ${r.suggest.url}`;
  return t.trim();
}

const COLUMNS = [
  ["Status", (r) => BUCKET_LABEL[r.bucket] || r.bucket],
  ["Problem", (r) => r.title],
  ["HTTP code", (r) => (r.code ? String(r.code) : "")],
  ["Link", (r) => r.target],
  ["Link text or element", (r) => r.text || ""],
  ["Where on the page", (r) => r.where || ""],
  ["Page title", (r) => r.pageTitle || ""],
  ["Page the link is on", (r) => r.page || ""],
  ["How to fix", fixText],
  ["Better address", betterAddress],
  ["Edit this page", (r) => r.editUrl || ""],
];

// Spreadsheet programs run cells that start with = + - @ as formulas. Scanned text is untrusted, so defuse it.
export function guardCell(v) {
  const s = String(v ?? "");
  return /^[=+\-@\t\r]/.test(s) ? "'" + s : s;
}

function csvCell(v) {
  const s = guardCell(v);
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

export function toCsv(rows) {
  const lines = [COLUMNS.map((c) => csvCell(c[0])).join(",")];
  for (const r of sortRows(rows)) lines.push(COLUMNS.map((c) => csvCell(c[1](r))).join(","));
  return "﻿" + lines.join("\r\n") + "\r\n"; // BOM so Excel reads UTF-8 correctly
}

export function toTsv(rows) {
  const clean = (v) => guardCell(v).replace(/[\t\r\n]+/g, " ");
  return [COLUMNS.map((c) => c[0]).join("\t"), ...sortRows(rows).map((r) => COLUMNS.map((c) => clean(c[1](r))).join("\t"))].join("\n");
}

export function toMarkdown(rows, meta) {
  const broken = sortRows(rows.filter((r) => r.bucket === "broken"));
  const blocked = rows.filter((r) => r.bucket === "blocked");
  const esc = (s) => String(s ?? "").replace(/\|/g, "\\|").replace(/\s+/g, " ").trim();
  const out = [];
  out.push(`## Broken link report for ${meta.site}`);
  out.push(`Scanned ${meta.date}. ${meta.pages} pages, ${meta.links} links checked. **${new Set(broken.map((r) => r.target)).size} broken**, ${new Set(blocked.map((r) => r.target)).size} could not be verified.`);
  if (meta.platform) out.push(`Platform: ${meta.platform}.`);
  out.push("");
  if (!broken.length) {
    out.push("No broken links found.");
  } else {
    out.push("| Page | Link text | Where | Broken link | Problem |");
    out.push("|---|---|---|---|---|");
    for (const r of broken.slice(0, 200)) {
      out.push(`| ${esc(r.page)} | ${esc(r.text)} | ${esc(r.where)} | ${esc(r.target)} | ${esc(r.title)} |`);
    }
    if (broken.length > 200) out.push(`\n...and ${broken.length - 200} more. Download the CSV for the full list.`);
  }
  return out.join("\n");
}

export function toJson(rows, meta) {
  return JSON.stringify({ ...meta, results: sortRows(rows) }, null, 2);
}

export function download(filename, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.className = "sr-only";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    return ok;
  }
}
