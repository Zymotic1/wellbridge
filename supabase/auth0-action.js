/**
 * Auth0 Post-Login Action
 *
 * Generates a deterministic UUID from the Auth0 user ID using MD5 (via
 * Node's built-in crypto module — no external HTTP calls, no secrets needed).
 * The UUID is stored in app_metadata so future logins skip the hashing step.
 *
 * The backend auto-provisions the matching tenants row on first request.
 *
 * Setup:
 *   1. Auth0 Dashboard → Actions → Library → Create Action
 *   2. Trigger: Login / Post Login  |  Runtime: Node 22
 *   3. Paste this code → Deploy → add to Login flow
 *
 * Claims namespace: https://wellbridge.app/
 */

exports.onExecutePostLogin = async function(event, api) {
  const ns = "https://wellbridge.app/";

  let tenantId = event.user.app_metadata?.tenant_id;
  const role   = event.user.app_metadata?.role || "patient";

  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

  if (!tenantId || !UUID_RE.test(tenantId)) {
    // Derive a stable UUID v4-compatible value from the Auth0 user_id.
    // Same user always gets the same UUID; no external calls required.
    const h = require("crypto")
      .createHash("md5")
      .update(event.user.user_id)
      .digest("hex");

    tenantId = [
      h.slice(0, 8),
      h.slice(8, 12),
      "4" + h.slice(13, 16),                                      // version 4
      ((parseInt(h[16], 16) & 3) | 8).toString(16) + h.slice(17, 20), // variant bits
      h.slice(20, 32),
    ].join("-");

    // Persist so the hashing step is skipped on subsequent logins
    api.user.setAppMetadata("tenant_id", tenantId);
    api.user.setAppMetadata("role", role);
  }

  api.accessToken.setCustomClaim(ns + "tenant_id", tenantId);
  api.accessToken.setCustomClaim(ns + "role", role);
  api.idToken.setCustomClaim(ns + "tenant_id", tenantId);
  api.idToken.setCustomClaim(ns + "role", role);
};
