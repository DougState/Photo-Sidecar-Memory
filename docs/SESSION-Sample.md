# SESSION.md — ElementTest Pro

> Agent-facing state file. Read this first at the start of any Claude session touching this plugin. Customer-facing release notes live in `readme.txt` / `CHANGELOG.md`; design rationale lives in `DECISIONS.md`; this file tracks *working state*.

---

## 1. Project Context

**What it is:** ElementTest Pro — WordPress plugin for A/B testing page elements (CSS, copy, JS, images) with conversion tracking. Built and maintained by Elimstat Dev Ops.

**Stack:**
- PHP 7.4+ (WordPress 5.6+, tested up to 6.7)
- MySQL 5.6+
- Vanilla JS on the frontend (no build step for plugin JS — files served directly from `assets/js/`)
- WooCommerce integration is optional but first-class
- Build tooling: Cursor command `/zip-plugin` defined in `.cursor/rules/zip-plugin.mdc` produces `elementtest-pro-<version>.zip`

**Distribution:** WordPress.org (canonical release notes in `readme.txt`) mirrored to GitHub (`CHANGELOG.md`, `README.md`).

---

## 2. Current State (overwrite each session)

**Version:** 2.3.9 (latest shipped on `main`)

**What works / is stable:**
- Core A/B testing: test creation, variant definitions, traffic allocation, scheduled start/stop
- Visual element selector for picking targets
- Conversion goals: click, page view, form submit, custom event, YouTube play, WooCommerce add-to-cart (page-scoped)
- Wildcard URL matching for thank-you / order-received goals
- JSON import/export of test configurations
- Statistical significance in results view
- Server-side visitor identity (post-2.2.0) — no longer trusts client-supplied hashes
- Per-IP rate limiting for impression + conversion tracking, now object-cache-safe (2.2.6)
- Per-IP invalid-request cap to prevent DB write amplification on public endpoints (2.3.6)
- Reverse proxy / CDN detection with admin settings UI (2.2.4)
- WooCommerce variable product compatibility (2.2.5 anti-flicker fix)
- Report export: standalone HTML (with Chart.js visual dashboard), CSV, and JSON via WP-CLI or admin UI buttons (2.3.0–2.3.4)
- HTML report XSS hardening and Chart.js graceful degradation (2.3.5)

**What is in flight:**
- Nothing currently in flight.

---

## 3. Next Actions (prioritized)

_(Update at the end of each session. Keep this short — 3 to 7 items max. Items below were inferred from a code/README/CHANGELOG review on 2026-04-06 — prune, reorder, or replace with what's actually in flight.)_

1. **Decompose `class-ajax-handler.php` (2,382 lines).** It holds event ingestion, rate limiting, dedup, identity resolution, revenue handling, and security enforcement in one file. That size makes the most security-sensitive file in the plugin hard to audit. Target split: a rate-limiter class, a dedup class, a conversion-recording class, and the thin AJAX dispatch. Add a `DECISIONS.md` entry when done.
2. **Add a minimal automated test suite, starting with the rate limiter.** The 2.2.0 → 2.2.1 → 2.2.6 arc is three consecutive rate-limiter bugs that a unit test covering fixed-window semantics and an object-cache-backed integration test would have caught. PHPUnit + WP_Mock + a Redis test double is the cheapest way in. Priority targets in order: rate limiter, `ElementTest_Visitor` hashing, revenue clamping for custom-event goals.
3. ~~**Fix the placeholder `Plugin URI` in `elementtest-pro.php`.**~~ Fixed in 2.3.9 — now points to `https://github.com/DougState/elementtest-pro`.
4. **Document the `elementtest_trusted_proxy_headers` filter in the main README.** It exists (CHANGELOG 2.2.4) and is the escape hatch for sites with unusual proxy setups, but a user reading just `README.md` would never find it. Add a short "Advanced: customizing trusted proxy headers" section under Reverse Proxy / CDN Setup.
5. **Formalize a release checklist in SESSION.md (or a `RELEASE.md`).** Minimum items surfaced from the CHANGELOG: test on a site with an external object cache (Redis/Memcached), test add-to-cart on a WooCommerce variable product page, verify the rate-limiter window expires, verify IP resolution with the three proxy presets, bump version in `elementtest-pro.php` + `readme.txt` + `CHANGELOG.md` together, run `/zip-plugin`. Every item maps to a past regression — that's what makes it worth the checklist.
6. **Audit `includes/views/*.php` for capability checks, nonces, and output escaping.** The CHANGELOG's security arc (2.1.2, 2.2.0, 2.2.4) has focused on the ingest side (`class-ajax-handler.php`) and identity (`class-visitor.php`); admin views haven't had a mentioned pass. Worth a deliberate review.
7. **Consider whether the 2.0.1 "drop conversion if button can't be verified" path should emit a debug log.** Silent drops are correct behavior but invisible when a customer on an exotic theme reports "my conversions are missing." A gated `WP_DEBUG`-level log would make support triage much faster without changing the default behavior.

---

## 4. Session Log (append-only)

| Date | Summary | Outcome |
|------|---------|---------|
| 2026-04-06 | Created SESSION.md and DECISIONS.md from README + CHANGELOG + main plugin file | Draft docs in place; Doug to fill in Next Actions and in-flight work |
| 2026-04-06 | Created `.claude/skills/wp-ajax-security-review/` skill | Single-file SKILL.md (150 lines) covering generic WP AJAX checklist + ElementTest Pro invariants with fixed report format and severity rubric |
| 2026-04-06 | First run of `wp-ajax-security-review` against `class-ajax-handler.php` @ v2.2.6 | 4 findings: 1 Medium (page-scoping not enforced at AJAX layer — invariant defense-in-depth gap), 3 Low (preg_replace `$N` in proxy_page, wp_kses_post wrong for js test_type, $wpdb->last_error logged unconditionally). All 5 of 6 invariants clean; page-scoping flagged per skill design. Report at `security-reviews/2026-04-06-class-ajax-handler-v2.2.6.md`. |
| 2026-04-07 | Initiated changelog process, reviewed PRs #26 and #29, merged wildcard URL fix (PR #29), backfilled readme.txt changelog gap (2.2.1–2.2.6), built v2.2.6 zip | All testing passed. Changelog now fully synced between `readme.txt` and `CHANGELOG.md` for all shipped 2.x versions. Zip at `elementtest-pro-2.2.6.zip` (108 KB). |
| 2026-04-12 | Built 2.3.0 report export feature (HTML, CSV, WP-CLI), verified all CLI commands on woo.dougstate.com, exported youtube-5300 test data | All 4 tests export cleanly in HTML and CSV. Version bumped to 2.3. |
| 2026-04-12 | Alt A branch: enhanced `report-html.php` with Chart.js visual dashboard (5 charts), added `--format=json` to CLI | Branch `feature/alt-a-chartjs-html` created, pushed, zip built as 2.3.a (121 KB). CDN-dependent for Chart.js; charts hidden in print. |
| 2026-04-18 | Fix cross-page add-to-cart conversion tracking (Issue #31) | Two bugs: (1) `detect_pageview_goal_tests()` only queried `pageview` goals, ignoring `add_to_cart` — frontend script never loaded on non-test pages; (2) `track_conversion()` page-scope enforcement rejected cross-page add-to-cart events. Fixed both; verified with curl + browser testing. |
| 2026-04-21 | Clean up stale cross-page add-to-cart dead code and doc drift (Issue #37) | Removed unreachable `add_to_cart` branch from `processConversionOnlyTests()` in `frontend.js` (leftover from reverted 2.3.2). Updated SESSION.md: fixed incorrect "cross-page by design" gotcha, corrected version from 2.3.2 to 2.3.6, updated page-scoping invariant entry to reflect 2.2.6 AJAX enforcement. |
| 2026-04-22 | Fix duplicate test dropping goals + wildcard path boundary in pageview detection (Issue #38) | `duplicate_test()` now copies `wp_elementtest_conversions` rows (was only copying variants). Fixed `detect_pageview_goal_tests()` wildcard matching to enforce path boundary (same fix as PR #29 for `conversion_page_matches()`). Bumped to 2.3.8. |
| 2026-04-22 | Fix frontend wildcard path boundary in pageview goals (Issue #30) | Ported the wildcard path boundary fix to `setupPageviewGoal()` in `frontend.js`. JS was using bare `indexOf` so `/shop/*` matched `/shopping`. Also fixed Plugin URI placeholder and synced frontend.js VERSION. Bumped to 2.3.9. |

---

## 5. Known Issues / Gotchas

Things that will bite the next session if you forget them:

- **Conversion goals are page-scoped by design.** Do not "fix" this by making tracking site-wide. See `DECISIONS.md` → "Page-scoped conversion tracking" for the full reasoning. The only exception is Page View goals, which legitimately track a destination URL different from the test page (thank-you pages, etc.).
- **Anti-flicker CSS vs. WooCommerce variation lifecycle.** WooCommerce's variation JS has a ~300ms `slideDown` delay on variable products that hides elements after the anti-flicker CSS has already shown them. The fix in 2.2.5 is `setupWooCommerceVariationHandler` hooking `show_variation` / `found_variation`. If you touch the frontend JS visibility logic, re-test on a WooCommerce variable product page or you *will* regress this.
- **Rate limiter transient storage.** Counter + window expiration are stored *together inside the transient value* (2.2.6 fix). Do not refactor to split them out — direct writes to the options table are invisible to Redis/Memcached object caches. Always use `set_transient()`.
- **Rate limiter window is fixed, not sliding.** The 2.2.1 fix was specifically to stop the TTL from being reset on every increment. The intent is a fixed hourly window. If you see the TTL being refreshed on increment, that is the 2.2.1 regression.
- **Visitor IP defaults to `REMOTE_ADDR` only.** Since 2.2.4, `X-Forwarded-For` / `X-Real-IP` / `CF-Connecting-IP` are *not* trusted unless explicitly enabled via the site's reverse-proxy setting or the `elementtest_trusted_proxy_headers` filter. If a user reports "IPs all look the same / rate limiting is too aggressive on Cloudflare," the answer is almost always: they haven't selected Cloudflare in Settings → Reverse Proxy / CDN.
- **Nginx preset prefers `X-Real-IP` over `X-Forwarded-For`.** `X-Forwarded-For` is client-spoofable in some configurations; `X-Real-IP` is nginx-controlled.
- **Custom proxy header names: hyphens are normalized to underscores.** PHP stores `$_SERVER['HTTP_X_REAL_IP']`, not `HTTP_X-REAL-IP`. If you add a new proxy preset, normalize the header name.
- **Visitor identity must stay aligned between frontend and AJAX.** Both sides use `ElementTest_Visitor`. If you change hashing in one place, change it in both, or dedup and rate limiting will split-brain.
- **Goal revenue is server-authoritative for standard conversions.** Do not accept client-supplied revenue for standard goals. Custom-event revenue is allowed but clamped. This is a security boundary (2.2.0) — don't loosen it without explicit discussion.
- **Add-to-cart goals are page-scoped (not cross-page).** Cross-page add-to-cart tracking was attempted in 2.3.2 and reverted in 2.3.1. All non-pageview conversion goals — including `add_to_cart` — are scoped to the test page. See `DECISIONS.md` → "2.3.1 — Revert cross-page add-to-cart tracking" and "Page-scoped conversion tracking". The only cross-page goal type is `pageview`. Do not re-add cross-page exemptions for `add_to_cart` without explicit discussion.
- **Page-scoping invariant is enforced at both the frontend and AJAX layers.** Since 2.2.6, `track_conversion()` in `class-ajax-handler.php` calls `conversion_page_matches()` to reject conversion events that did not originate on the test's configured page URL. Pageview goals are the only exception (they are cross-page by design). This defense-in-depth was originally flagged in the 2026-04-06 security review.

---

## 6. Key Files (orient fast here)

| File | Lines | Why it matters |
|------|-------|----------------|
| `elementtest-pro.php` | 760 | Plugin bootstrap, constants, activation/deactivation, admin menu, settings registration, proxy notice |
| `includes/class-ajax-handler.php` | 2,382 | **The beast.** Event ingestion, conversion recording, rate limiting, dedup, revenue clamping. Most security-sensitive file in the plugin. |
| `includes/class-frontend.php` | 618 | Frontend script injection, anti-flicker CSS, WooCommerce variation handler, test application logic |
| `includes/class-visitor.php` | 105 | Shared visitor identity utility. Source of truth for hashing — both AJAX and frontend must use it. |
| `includes/views/new-test.php` | — | Test editor admin view (element selector integration, goal config, WooCommerce add-to-cart controls) |
| `includes/views/test-results.php` | — | Results / statistical significance view |
| `includes/views/settings.php` | — | Settings UI including reverse proxy / CDN selector |
| `includes/views/tests-list.php` | — | Tests index page (import/export actions live here) |
| `assets/js/frontend.js` | — | Frontend test application + variation handler. Touch with care. |
| `assets/js/element-selector.js` | — | Visual picker injected into the edited page |
| `assets/js/admin.js` | — | Admin UI wiring |
| `includes/class-report-generator.php` | 410 | Report data assembly, HTML/CSV/JSON rendering. Shared by WP-CLI and admin export buttons. |
| `includes/class-cli-commands.php` | 170 | WP-CLI `wp elementtest export` and `export_all` commands. Supports `--format=html\|csv\|json`. |
| `includes/views/report-html.php` | 290 | Standalone HTML report template with Chart.js visual dashboard (5 charts) + data tables. |
| `readme.txt` | — | **Canonical** WordPress.org release notes. Update here first; mirror to `CHANGELOG.md`. |
| `CHANGELOG.md` | — | GitHub-facing mirror of `readme.txt` |
| `README.md` | — | GitHub-facing project overview + reverse proxy setup guide |
| `DECISIONS.md` | — | Architectural / design rationale (why page-scoped, why server-side identity, etc.) |

**Database tables** (prefixed with WP table prefix):

| Table | Purpose |
|-------|---------|
| `wp_elementtest_tests` | Test configurations |
| `wp_elementtest_variants` | Variant definitions per test |
| `wp_elementtest_events` | User interaction tracking (impressions, clicks, etc.) |
| `wp_elementtest_conversions` | Conversion goal definitions |

---

## 7. Discipline (read this, then do it)

At the end of every session:

1. **Overwrite** "Current State" to reflect reality.
2. **Append** one row to the Session Log (date, one-line summary, outcome).
3. **Refresh** Next Actions — remove what's done, add what surfaced.
4. Move any new gotchas into "Known Issues."
5. Move any new architectural choices into `DECISIONS.md`, not here.

When starting a new session or delegating to a sub-agent, point it at this file first.
