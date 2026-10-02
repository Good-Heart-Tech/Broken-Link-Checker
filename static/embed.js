// SPDX-License-Identifier: AGPL-3.0-or-later
// Fills in the current year in the footer.
document.addEventListener("DOMContentLoaded", () => {
  const y = document.getElementById("ght-year");
  if (y) y.textContent = new Date().getFullYear();
});
