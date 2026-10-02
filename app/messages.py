# SPDX-License-Identifier: AGPL-3.0-or-later
"""Human wording for every result. Edit the words here, not in the logic.

Write for non-technical nonprofit staff. No em dashes.
"""

# reason -> (short title, one-sentence explanation, how to fix)
REASONS = {
    "http_404": ("Page not found (404)", "The page at this address does not exist.",
                 "Update the link to the right page, or remove it. If the page moved, point to its new address."),
    "http_410": ("Page removed (410)", "The page was deliberately removed.",
                 "Remove the link or replace it with a current page."),
    "http_4xx": ("Page refused the request", "The site answered with an error for this address.",
                 "Open the link in your browser. If it fails there too, update or remove it."),
    "http_5xx": ("Server error", "The website this link points to had a problem and could not respond.",
                 "Try the link again later. If it keeps failing, update or remove it."),
    "dns_failure": ("Website not found", "The website name in this link does not exist anymore.",
                    "Check the spelling. If the organization closed or moved, replace or remove the link."),
    "connection_refused": ("Website not reachable", "The website did not accept our connection.",
                           "Check the address. If the site is gone, replace or remove the link."),
    "tls_error": ("Security certificate problem", "The site's security certificate is invalid or expired, so browsers warn visitors.",
                  "Tell the site owner, or replace the link. If this is your site, renew the certificate."),
    "timeout": ("Did not respond (timeout)", "The website took too long to answer, twice.",
                "Try the link in your browser. If it is slow or down, replace it or check again later."),
    "redirect_loop": ("Redirect loop", "The link sends visitors in a circle and never loads.",
                      "Update the link to a working address, or fix the redirect if this is your site."),
    "too_many_redirects": ("Too many redirects", "The link bounces through too many addresses.",
                           "Update the link to its final address."),
    "error": ("Could not load", "Something went wrong loading this address.",
              "Open the link in your browser to check. If it fails there too, update or remove it."),
    "blocked_waf": ("Blocked our check", "The site uses bot protection and refused our automated check. The link is probably fine.",
                    "Open the link in your browser to confirm it works."),
    "blocked": ("Could not verify", "The site refused our automated check. The link may be fine.",
                "Open the link in your browser to confirm it works."),
    "rate_limited": ("Could not verify (too many requests)", "The site asked us to slow down, so we could not check this link.",
                     "Open the link in your browser to confirm it works."),
    "auth_required": ("Needs a login", "This page asks for a login, so we cannot check it.",
                      "Open the link in your browser. If visitors are not supposed to need a login, fix the link."),
    "social_skipped": ("Not checked (social site)", "Social sites block automated checks, so we skip them.",
                       "Click the link yourself now and then. Turn on social link checking to try anyway."),
    "unsafe_target": ("Not checked", "This link points to a private or unsupported address.",
                      "Links on a public website should not point here. Update the link."),
    "redirect_permanent": ("Link has moved", "The link works, but the page moved permanently.",
                           "Update the link to the new address so visitors skip the extra hop."),
    "redirect_home": ("Sends visitors to the home page", "The link works, but lands on the home page. The page was probably removed.",
                      "Point the link at a better page, or remove it."),
    "http_to_https": ("Uses http instead of https", "The link works, but the secure version of the address is preferred.",
                      "Change http:// to https:// in the link."),
    "soft_404": ("Might be a missing page", "The page loads, but it looks like a 'page not found' message.",
                 "Open the link and check. If the content is missing, update or remove the link."),
    "slow": ("Very slow to load", "The link works, but it took more than 8 seconds.",
             "Check the link in your browser. Consider a different source if it stays slow."),
    "ok": ("Working", "The link works.", ""),
}


def describe(reason: str) -> dict:
    title, explain, fix = REASONS.get(reason, REASONS["error"])
    return {"title": title, "explain": explain, "fix": fix}


# Friendly messages when the very first page cannot be loaded.
START_ERRORS = {
    "dns_failure": "We could not find that website. Please check the spelling and try again.",
    "connection_refused": "That website did not accept our connection. Is the address right?",
    "timeout": "That website took too long to answer. Please try again in a moment.",
    "tls_error": "That website has a security certificate problem, so we could not open it.",
    "unsafe_target": "We can only check public websites.",
    "blocked": "That website blocks automated checks, so we cannot scan it. Try the single page option or a different page.",
    "http_error": "That website returned an error for the address you gave us.",
    "denied": "We do not scan this website.",
    "invalid": "That does not look like a website address. Try something like yourorganization.org",
    "error": "We could not open that website.",
}
