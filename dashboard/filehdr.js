'use strict';
/* Antwort-Header fuer /api/file (Agent-Output ist untrusted). Rein, damit testbar.
   Alles: nosniff + no-store. Sandbox-CSP fuer alles ausser PDF: Chrome deaktiviert den PDF-Viewer
   in sandboxed Dokumenten (Belege/Rechnungen waeren sonst nicht mehr lesbar). */
function fileHeaders(type) {
  const h = { 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
  if (!/^application\/pdf\b/i.test(type)) h['Content-Security-Policy'] = 'sandbox';
  return h;
}
module.exports = { fileHeaders };
