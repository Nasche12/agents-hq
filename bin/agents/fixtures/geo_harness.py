import sys, json, threading, http.server, importlib.util
spec = importlib.util.spec_from_file_location("geo", sys.argv[1]); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
out = {}

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302); self.send_header("Location", "file:///etc/hosts"); self.end_headers()
    def log_message(self, *a): pass
s = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start()
r = g.fetch("http://127.0.0.1:%d/" % s.server_address[1])
out["redir"] = {"status": r["status"], "error": r["error"], "body": len(r["body"])}
# nur HTTP(S)-Handler im Opener
out["handlers"] = sorted(type(h).__name__ for h in g._opener.handlers)

out["same_site"] = [g.same_site(u, "https://site.at") for u in
    ["http://site.at:99999/x", "http://site.at:abc/", "https://site.at:443/", "http://site.at/", "https://www.site.at/", "https://site.at.evil.com/", "HTTPS://Site.AT/", "https://site.at:8443/"]]
out["same_host"] = [g.same_host(u, "https://site.at") for u in
    ["http://site.at/sitemap.xml", "https://site.at/sitemap.xml", "https://evil.com/s.xml", "file:///x", "http://site.at:99999/"]]

def run_sitemap(sitemaps, bodies):
    calls = []
    def fake(url, *a, **k):
        calls.append(url)
        b = bodies.get(url)
        return {"status": 200 if b else 404, "url": url, "headers": {}, "body": (b or "").encode(), "redirects": [], "error": None, "ms": 1}
    g.fetch = fake
    rep = g.Report()
    urls, info = g.check_sitemap("https://site.at", sitemaps, rep)
    return {"urls": urls, "issues": [f["issue"] for f in rep.findings], "calls": calls}

XML = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>'
locs = "".join("<url><loc>%s</loc></url>" % u for u in
    ["https://site.at/a", "http://site.at/b", "https://evil.com/c", "file:///x"])
out["sm1"] = run_sitemap(["http://site.at/sitemap.xml"], {"http://site.at/sitemap.xml": XML % locs})
out["sm2"] = run_sitemap(["https://evil.com/sm.xml"], {"https://site.at/sitemap.xml": XML % "<url><loc>https://site.at/a</loc></url>"})
print(json.dumps(out))
