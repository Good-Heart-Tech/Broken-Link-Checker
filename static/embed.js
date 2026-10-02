// SPDX-License-Identifier: AGPL-3.0-or-later
// When this page sits inside the Nonprofit Tools Hub, the Hub already shows the logo and title, so hide ours.
if (window.self !== window.top) document.documentElement.classList.add("embedded");
document.addEventListener("DOMContentLoaded", () => {
  const y = document.getElementById("ght-year");
  if (y) y.textContent = new Date().getFullYear();
});
