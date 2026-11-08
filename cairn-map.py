#!/usr/bin/env python3
"""Cairn Map: a map of the infrastructure, from the big picture down to one element, built from modules.

It stores nothing and writes nothing: every source is a module that returns one JSON shape
({"nodes": [...], "status": [...], "panels": [...]}), merged by id and alias. See README.md.
Python standard library only.
"""
import argparse
import base64
import difflib
import hmac
import http.server
import importlib.util
import ipaddress
import json
import os
import pathlib
import re
import ssl
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
VERSION = "1.3.3"

# The families the page knows, in display order; a module can only fill these.
FAMILIES = ["physical", "network", "hypervisor", "services", "storage"]
LEVELS = ["ok", "unknown", "warn", "down"]  # worst last

DEFAULTS = {
    "title": "Cairn Map", "lang": "en",
    "listen": "127.0.0.1:8095",
    # Behind an authenticating proxy: requests from these addresses only, user from user_header.
    # Empty: requests from this machine only (loopback), user "local".
    "trusted_proxies": [], "user_header": "Remote-User", "groups_header": "Remote-Groups", "require_groups": [],
    # Modules: [{name, type: python|url|command, module|file|url|command, options, interval, timeout, token_file, ca_file, enabled}]
    "modules": [],
    # The Settings page's file (places, kinds, modules switched off), the only thing Cairn Map writes;
    # empty: no Settings page.
    "settings_file": "",
}


class ModuleError(Exception):
    pass


# ---------- reading sources (shared by the module types and handed to Python modules) ----------

def read_secret(base, path):
    return (base / path).read_text(encoding="utf-8").strip() if path else ""


def get_json(base, url="", file="", token_file="", ca_file="", timeout=20, auth="Bearer "):
    """JSON from a URL (with an optional token, sent as `Authorization: <auth><token>`, and a CA bundle)
    or from a local file. A list of URLs is tried in order (the first that answers wins)."""
    try:
        return json.loads(get_text(base, url, file, token_file, ca_file, timeout, auth))
    except ValueError as e:
        raise ModuleError(f"not JSON: {e}") from None


def get_text(base, url="", file="", token_file="", ca_file="", timeout=20, auth="Bearer "):
    """The same, as text."""
    if file:
        return (base / file).read_text(encoding="utf-8")
    tok = read_secret(base, token_file)
    ctx = ssl.create_default_context(cafile=str(base / ca_file)) if ca_file else None
    errors = []
    for u in [url] if isinstance(url, str) else url:
        req = urllib.request.Request(u, headers={"Accept": "application/json, text/plain"})
        if tok:
            req.add_header("Authorization", auth + tok)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read().decode("utf-8")
        except (OSError, ValueError) as e:
            errors.append(f"{u}: {e}")
    raise ModuleError("; ".join(errors) or "no url")


def load_python(path):
    spec = importlib.util.spec_from_file_location(f"cairn_map_module_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, "fetch", None)):
        raise ModuleError(f"{path.name}: no fetch(options, ctx) function")
    return mod


# The Physical family's upper levels, shared by the modules that know machines: site -> group by kind ->
# machine, or site -> place -> machine when the page asks for places (by_place). Options (a module's
# "physical"): site (its name), places ({place: [machine names]}), kinds ({machine name: kind}, overrides
# the module's guess).
GROUPS = {"node": "Servers", "server": "Servers", "nas": "Storage", "router": "Network", "switch": "Network",
          "ap": "Network", "pc": "Computers"}
GROUP_ORDER = ["Servers", "Storage", "Network", "Computers", "Other"]


def physical(ph, name, kind, aliases=(), attrs=None):
    """The nodes that place a machine in the Physical family (its site, group, itself); [] without a
    "physical" option. Its id is "phys:<name in lower case>", so two modules naming it merge; its place,
    if any, is its attribute "location"."""
    if not isinstance(ph, dict) or not name:
        return []
    low = name.lower()
    kind = {k.lower(): v for k, v in (ph.get("kinds") or {}).items()}.get(low, kind)
    site = ph.get("site") or "Site"
    sid = "site:" + slugify(site)
    place = next((pl for pl, ns in (ph.get("places") or {}).items() if low in {n.lower() for n in ns}), None)
    g = GROUPS.get(kind, "Other")
    return [{"id": sid, "family": "physical", "name": site, "kind": "site"},
            {"id": f"{sid}:{g.lower()}", "family": "physical", "parent": sid, "name": g, "kind": "group",
             "attrs": {"order": GROUP_ORDER.index(g)}},
            {"id": "phys:" + low, "family": "physical", "parent": f"{sid}:{g.lower()}", "name": name, "kind": kind,
             "aliases": [a for a in aliases if a], "attrs": {**(attrs or {}), **({"location": place} if place else {})}}]


def synth(id_, parent, name, kind, order):
    """A merged node made by the core (a group or a place of the Physical family)."""
    return {"id": id_, "family": "physical", "parent": parent, "name": name, "kind": kind, "slug": "", "aliases": [],
            "attrs": {"order": order}, "source": "", "sources": [], "status": [], "panels": []}


def apply_settings(nodes, st):
    """The Settings page's places and kinds over the modules' Physical family: a machine named in "kinds"
    moves to its kind's group; "places", once saved, replaces the config's places. Groups left empty go."""
    kinds = {k.lower(): v for k, v in (st.get("kinds") or {}).items()}
    places = st.get("places")
    where = {n.lower(): pl for pl, ns in (places or {}).items() for n in ns}
    for x in list(nodes.values()):
        g = nodes.get(x["parent"])
        if x["family"] != "physical" or not g or g["kind"] != "group":
            continue
        low = x["name"].lower()
        if low in kinds and kinds[low] != x["kind"]:
            name = GROUPS.get(kinds[low], "Other")
            gid = f"{g['parent']}:{name.lower()}"
            nodes.setdefault(gid, synth(gid, g["parent"], name, "group", GROUP_ORDER.index(name)))
            x["kind"], x["parent"] = kinds[low], gid
        if places is not None:
            x["attrs"] = {k: v for k, v in x["attrs"].items() if k != "location"}
            if low in where:
                x["attrs"]["location"] = where[low]
    used = {x["parent"] for x in nodes.values()}
    return {i: x for i, x in nodes.items() if not (x["family"] == "physical" and x["kind"] == "group" and i not in used)}


SETTINGS_KEYS = ("places", "kinds", "disabled")


def check_settings(st, modules):
    """A settings body as the page sends it, or ValueError: {places: {place: [machine]}, kinds: {machine:
    kind}, disabled: [module name]}, names up to 64 characters."""
    name = lambda v: isinstance(v, str) and 0 < len(v.strip()) <= 64
    if not isinstance(st, dict) or set(st) - set(SETTINGS_KEYS):
        raise ValueError("expected {places, kinds, disabled}")
    places, kinds, off = st.get("places") or {}, st.get("kinds") or {}, st.get("disabled") or []
    if not (isinstance(places, dict) and len(places) <= 100 and all(name(k) and isinstance(v, list) and len(v) <= 500 and all(map(name, v))
                                                                    for k, v in places.items())):
        raise ValueError("places: {place: [machine names]}")
    if not (isinstance(kinds, dict) and len(kinds) <= 500 and all(name(k) and v in GROUPS for k, v in kinds.items())):
        raise ValueError("kinds: {machine: " + "|".join(GROUPS) + "}")
    if not (isinstance(off, list) and all(m in modules for m in off)):
        raise ValueError("disabled: module names")
    return {"places": {k.strip(): [n.strip() for n in v] for k, v in places.items() if v}, "kinds": kinds, "disabled": sorted(set(off))}


def by_place(nodes):
    """The Physical family regrouped: site -> place -> machine instead of site -> kind -> machine; the
    machines with no place go to "No place". Merged nodes in, merged nodes out."""
    out = {}
    for i, x in nodes.items():
        g = nodes.get(x["parent"])
        if x["family"] == "physical" and x["kind"] == "group":
            continue
        if x["family"] == "physical" and g and g["kind"] == "group":
            pl = x["attrs"].get("location") or ""
            pid = f"{g['parent']}:place:{slugify(pl) if pl else '-'}"
            out.setdefault(pid, synth(pid, g["parent"], pl or "No place", "place" if pl else "group", 1 if pl else 2))
            x = {**x, "parent": pid}
        out[i] = x
    return out


class Ctx:
    """What a Python module gets besides its options: get_json() and get_text() with paths relative to the
    config, the config's lang."""
    def __init__(self, base, m, lang="en"):
        self.base, self.m, self.lang = base, m, lang

    def get_json(self, url="", file="", token_file="", ca_file="", auth="Bearer "):
        return get_json(self.base, url, file, token_file, ca_file, self.m.get("timeout", 20), auth)

    def get_text(self, url="", file="", token_file="", ca_file="", auth="Bearer "):
        return get_text(self.base, url, file, token_file, ca_file, self.m.get("timeout", 20), auth)

    physical = staticmethod(physical)


def run_module(base, m, lang="en"):
    t = m.get("type", "python")
    if t == "url":
        return get_json(base, m["url"], "", m.get("token_file", ""), m.get("ca_file", ""), m.get("timeout", 20), m.get("auth", "Bearer "))
    if t == "command":
        cmd = m["command"] if isinstance(m["command"], list) else m["command"].split()
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=m.get("timeout", 20), cwd=base, encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ModuleError(str(e)) from None
        if r.returncode:
            raise ModuleError(f"exit {r.returncode}: {r.stderr.strip()[-300:]}")
        try:
            return json.loads(r.stdout)
        except ValueError as e:
            raise ModuleError(f"output is not JSON: {e}") from None
    if t == "python":
        path = base / m["file"] if m.get("file") else HERE / "modules" / f"{m.get('module') or m['name']}.py"
        return load_python(path).fetch(m.get("options") or {}, Ctx(base, m, lang))
    raise ModuleError(f"unknown module type {t!r}")


# ---------- the common format: checked, then merged by id and alias ----------

def clean(data, source):
    """Keep what fits the format; one module's mistake never breaks the map. Returns (data, number of items dropped)."""
    out, dropped = {"nodes": [], "status": [], "panels": []}, 0
    if not isinstance(data, dict):
        return out, 1
    s = lambda v: isinstance(v, str) and v != ""
    for n in data.get("nodes") or []:
        if not (isinstance(n, dict) and s(n.get("id")) and (n.get("family") in FAMILIES or n.get("family") is None)):
            dropped += 1
            continue
        out["nodes"].append({
            "id": n["id"], "family": n.get("family"), "parent": n.get("parent") if s(n.get("parent")) else None,
            "name": str(n.get("name") or ""), "kind": str(n.get("kind") or ""), "slug": str(n.get("slug") or ""),
            "aliases": aliases(n),
            "attrs": n.get("attrs") if isinstance(n.get("attrs"), dict) else {}, "source": source})
    for st in data.get("status") or []:
        if isinstance(st, dict) and s(st.get("id")) and st.get("level") in LEVELS:
            out["status"].append({"id": st["id"], "level": st["level"], "detail": str(st.get("detail") or ""), "source": source,
                                  "aliases": aliases(st)})
        else:
            dropped += 1
    for p in data.get("panels") or []:
        if isinstance(p, dict) and s(p.get("id")) and s(p.get("type")):
            out["panels"].append({**p, "source": source, "aliases": aliases(p)})
        else:
            dropped += 1
    return out, dropped


def aliases(item):
    a = item.get("aliases")
    return [str(x).lower() for x in a if str(x)] if isinstance(a, list) else []


def merge(results):
    """Modules' outputs (in config order) into one map: {id: node}. The first module to name a field wins,
    later ones fill what is missing; attrs and aliases add up. A node without a family enriches the node
    its id or an alias points at (a source that does not know the ids); status and panels attach the same way."""
    nodes, extra = {}, []
    for d in results:
        for n in d["nodes"]:
            if not n["family"]:
                extra.append(n)
                continue
            x = nodes.get(n["id"])
            if x is None:
                nodes[n["id"]] = {**n, "aliases": list(dict.fromkeys(n["aliases"])), "attrs": dict(n["attrs"]),
                                  "sources": [n["source"]], "status": [], "panels": []}
                continue
            for k in ("family", "parent", "name", "kind", "slug"):
                x[k] = x[k] or n[k]
            x["aliases"] = list(dict.fromkeys(x["aliases"] + n["aliases"]))
            for k, v in n["attrs"].items():
                x["attrs"].setdefault(k, v)
            if n["source"] not in x["sources"]:
                x["sources"].append(n["source"])
    index = {}
    for x in nodes.values():
        for k in [x["id"].lower(), *x["aliases"]]:
            index.setdefault(k, []).append(x["id"])
    one = lambda i: [i] if i in nodes else index.get(i.lower(), [])
    # an item attaches to every element its id or one of its aliases names, once
    resolve = lambda it: list(dict.fromkeys(j for k in [it["id"], *it["aliases"]] for j in one(k)))
    for n in extra:
        for i in resolve(n):
            x = nodes[i]
            x["aliases"] = list(dict.fromkeys(x["aliases"] + n["aliases"]))
            for k, v in n["attrs"].items():
                x["attrs"].setdefault(k, v)
            if n["source"] not in x["sources"]:
                x["sources"].append(n["source"])
    for d in results:
        for st in d["status"]:
            for i in resolve(st):
                nodes[i]["status"].append(st)
        for p in d["panels"]:
            for i in resolve(p):
                nodes[i]["panels"].append(p)
    return nodes, index


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "x"


def build(nodes, index):
    """Tree per family: children, a unique slug among siblings, the path from the family root, the worst
    level of the node and everything under it, and the same element in other families (shared id or alias)."""
    # a node without a name (a server behind a proxy, known by its address) takes the name of the same
    # element in another family, the nearest the top of its tree; else its first alias
    for i, x in nodes.items():
        if not x["name"]:
            same = [nodes[j] for k in x["aliases"] for j in index.get(k, []) if j != i and nodes[j]["name"] and nodes[j]["family"] != x["family"]]
            x["name"] = min(same, key=lambda y: depth(nodes, y))["name"] if same else (x["aliases"] or [""])[0]
    kids = {i: [] for i in nodes}
    roots = {f: [] for f in FAMILIES}
    for i, x in nodes.items():
        p = x["parent"]
        if p in nodes and p != i and nodes[p]["family"] == x["family"]:
            kids[p].append(i)
        else:
            roots[x["family"]].append(i)
    order = lambda ids: sorted(ids, key=lambda i: (nodes[i]["attrs"].get("order", 0), natural(nodes[i]["name"] or i)))
    seen = set()

    def walk(ids, path, solo=False):
        taken = set()
        for i in order(ids):
            if i in seen:
                continue  # a parent cycle: each node is placed once
            seen.add(i)
            x = nodes[i]
            base = slugify(x["slug"] or x["name"] or i)
            slug, k = base, 2
            while slug in taken:
                slug, k = f"{base}-{k}", k + 1
            taken.add(slug)
            # a family with a single root: the root is the family's page, addresses start below it
            x["slug"], x["path"] = slug, [] if solo else [*path, slug]
            x["children"] = [c for c in order(kids[i])]
            walk(kids[i], x["path"])
            own = [s["level"] for s in x["status"]]
            x["level"] = max(own, key=LEVELS.index) if own else ""
            under = [nodes[c]["rollup"] for c in x["children"] if nodes[c].get("rollup")]
            x["rollup"] = max([x["level"], *under], key=lambda l: LEVELS.index(l) if l else -1) if (own or under) else ""
    for f in FAMILIES:
        walk(roots[f], [], len(roots[f]) == 1)
        roots[f] = [i for i in order(roots[f]) if i in seen]
    for i, x in nodes.items():
        x.setdefault("children", [])
        others = {j for k in [i.lower(), *x["aliases"]] for j in index.get(k, []) if nodes[j]["family"] != x["family"]}
        x["also"] = sorted(others, key=lambda j: (FAMILIES.index(nodes[j]["family"]), len(nodes[j].get("path", []))))
    return roots


def depth(nodes, x, n=0):
    p = x["parent"]
    return n if n > 20 or p not in nodes or p == x["id"] else depth(nodes, nodes[p], n + 1)


def natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# ---------- server ----------

class App:
    def __init__(self, cfg, base):
        self.cfg, self.base = cfg, base
        self.mods = [m for m in cfg["modules"] if m.get("enabled", True)]
        # name -> {"data", "ok" (time of the last good read), "tried", "error", "dropped"}
        self.state = {m["name"]: {"data": None, "ok": 0.0, "tried": 0.0, "error": "", "dropped": 0} for m in self.mods}
        self.lock = threading.Lock()  # ponytail: one refresh at a time; per-module locks if a slow module holds others up
        self.proxies = [ipaddress.ip_network(p, strict=False) for p in cfg["trusted_proxies"]]
        self.settings_path = base / cfg["settings_file"] if cfg["settings_file"] else None
        try:
            self.settings = json.loads(self.settings_path.read_text(encoding="utf-8")) if self.settings_path else {}
        except FileNotFoundError:
            self.settings = {}

    def save_settings(self, body):
        """Check, write (atomically) and use a settings body; ValueError when it does not fit."""
        st = check_settings(body, [m["name"] for m in self.mods])
        tmp = self.settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, self.settings_path)
        with self.lock:
            self.settings = st
        return st

    def on(self):
        return [m for m in self.mods if m["name"] not in (self.settings.get("disabled") or [])]

    def refresh(self):
        now = time.time()
        due = [m for m in self.on() if now - self.state[m["name"]]["tried"] >= m.get("interval", 60)]

        def one(m):
            st = self.state[m["name"]]
            st["tried"] = time.time()
            try:
                st["data"], st["dropped"] = clean(run_module(self.base, m, self.cfg["lang"][:2]), m["name"])
                st["ok"], st["error"] = time.time(), ""
            except Exception as e:  # noqa: BLE001 - a broken module keeps its last good data and says why
                st["error"] = str(e) or type(e).__name__
                print(f"cairn-map: module {m['name']}: {st['error']}", file=sys.stderr)
        if due:
            with ThreadPoolExecutor(len(due)) as ex:
                list(ex.map(one, due))

    def map(self, full=False, places=False):
        """The merged map (the Physical family by place when places is true). Series panels carry only each line's last value here (the map's labels); their
        points come from panels(id), on demand, so the map stays light."""
        with self.lock:
            self.refresh()
            results = [self.state[m["name"]]["data"] for m in self.on() if self.state[m["name"]]["data"]]
            nodes, index = merge(results)
            nodes = apply_settings(nodes, self.settings)
            if places:
                nodes = by_place(nodes)
            roots = build(nodes, index)
            modules = [{"name": m["name"], "families": m.get("families", []), "error": self.state[m["name"]]["error"],
                        "ok": self.state[m["name"]]["ok"], "dropped": self.state[m["name"]]["dropped"],
                        "nodes": sum(1 for x in nodes.values() if m["name"] in x["sources"]
                                     or any(s["source"] == m["name"] for s in x["status"] + x["panels"])),
                        "edit": m.get("edit_label", ""), "on": m in self.on()} for m in self.mods]
        for x in nodes.values():
            x.pop("parent", None)
            if not full:
                x["panels"] = [slim(p) for p in x["panels"]]
        return {"title": self.cfg["title"], "lang": self.cfg["lang"], "version": VERSION, "families": FAMILIES,
                "roots": roots, "nodes": nodes, "modules": modules, "time": time.time(),
                "settings": {**self.settings, "editable": bool(self.settings_path), "kind_list": list(GROUPS)}}

    def panels(self, id_):
        x = self.map(full=True)["nodes"].get(id_)
        return None if x is None else {"id": id_, "panels": x["panels"]}

    def user(self, h):
        peer = ipaddress.ip_address(h.client_address[0])
        if not self.proxies:
            return "local" if peer.is_loopback else None
        if not any(peer in n for n in self.proxies):
            return None
        user = h.headers.get(self.cfg["user_header"], "").strip()
        groups = [g.strip() for g in h.headers.get(self.cfg["groups_header"], "").split(",")]
        ok = not self.cfg["require_groups"] or any(g in self.cfg["require_groups"] for g in groups)
        return user if user and ok else None


def slim(p):
    """A series panel without its points: each line keeps its last value."""
    if p.get("type") != "series" or not isinstance(p.get("lines"), list):
        return p
    last = lambda vs: next((v for v in reversed(vs) if v is not None), None) if isinstance(vs, list) else None
    return {**p, "lines": [{"name": str(ln.get("name") or ""), "last": last(ln.get("values"))} for ln in p["lines"] if isinstance(ln, dict)],
            "points": True}


CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def favicon():
    m = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", (HERE / "page.html").read_text(encoding="utf-8"))
    return base64.b64decode(m.group(1))


def page(cfg):
    p = (HERE / "page.html").read_text(encoding="utf-8")
    t = cfg["title"].replace("&", "&amp;").replace("<", "&lt;")
    return p.replace("<title>Cairn Map</title>", f"<title>{t}</title>").replace('lang="en"', f'lang="{cfg["lang"][:5]}"', 1)


def serve(cfg, base):
    app = App(cfg, base)

    class H(http.server.BaseHTTPRequestHandler):
        server_version, sys_version = "cairn-map", ""

        def send(self, code, body, ctype="application/json"):
            b = body if isinstance(body, bytes) else body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            for k, v in (("Content-Type", ctype if isinstance(body, bytes) else f"{ctype}; charset=utf-8"), ("Content-Length", str(len(b))),
                         ("Cache-Control", "no-store"), ("Content-Security-Policy", CSP), ("X-Content-Type-Options", "nosniff"),
                         ("Referrer-Policy", "no-referrer")):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/healthz":
                return self.send(200, "ok\n", "text/plain")
            if path == "/favicon.ico":
                return self.send(200, favicon(), "image/png")
            if not app.user(self):
                return self.send(403, "access denied\n", "text/plain")
            if path == "/api/map":
                return self.send(200, app.map(places="places=1" in self.path.partition("?")[2].split("&")))
            if path.startswith("/api/panels/"):
                body = app.panels(urllib.parse.unquote(path[len("/api/panels/"):]))
                return self.send(200, body) if body else self.send(404, "not found\n", "text/plain")
            if path == "/":
                return self.send(200, page(cfg), "text/html")
            self.send(404, "not found\n", "text/plain")

        def do_POST(self):
            # the Settings page only: a JSON body (a form cannot send one without a preflight), same origin
            if self.path != "/api/settings" or not app.settings_path:
                return self.send(404, "not found\n", "text/plain")
            if not app.user(self):
                return self.send(403, "access denied\n", "text/plain")
            origin = urllib.parse.urlsplit(self.headers.get("Origin", "")).netloc
            if not self.headers.get("Content-Type", "").startswith("application/json") or (origin and origin != self.headers.get("Host")):
                return self.send(403, "same-origin JSON only\n", "text/plain")
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= 65536:
                return self.send(413, "body too large\n", "text/plain")
            try:
                st = app.save_settings(json.loads(self.rfile.read(n)))
            except ValueError as e:
                return self.send(400, f"{e}\n", "text/plain")
            print(f"cairn-map: settings saved by {app.user(self)}", file=sys.stderr)
            self.send(200, st)

        def log_message(self, fmt, *args):
            pass

    host, _, port = cfg["listen"].rpartition(":")
    srv = http.server.ThreadingHTTPServer((host.strip("[]") or "0.0.0.0", int(port)), H)
    print(f"cairn-map {VERSION}: serving on {cfg['listen']}, {len(app.mods)} modules", file=sys.stderr)
    srv.serve_forever()


MODULE_KEYS = {"name", "type", "module", "file", "options", "url", "token_file", "ca_file", "auth", "command",
               "interval", "timeout", "enabled"}


def unknown_keys(cfg):
    """Keys of the config and of its module entries that nothing reads (a typo would else go unnoticed),
    with the closest known key. Module options are not checked: each module reads its own."""
    def check(d, known, where):
        for k in d:
            if k not in known:
                close = difflib.get_close_matches(k, known, 1)
                yield f"unknown key {where}{k!r}" + (f", did you mean {close[0]!r}?" if close else "")
    out = list(check(cfg, DEFAULTS, ""))
    for m in cfg.get("modules", []):
        out += check(m, MODULE_KEYS, f"in module {m.get('name')!r}: ")
    return out


def load_config(path):
    raw = json.loads(path.read_text(encoding="utf-8")) if path else {}
    cfg = {**DEFAULTS, **raw}
    names = [m.get("name") for m in cfg["modules"]]
    if any(not n for n in names) or len(set(names)) != len(names):
        sys.exit("cairn-map: every module needs a unique name")
    for w in unknown_keys(raw):
        print(f"cairn-map: {w}", file=sys.stderr)
    return cfg


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-c", "--config", type=pathlib.Path, help="JSON config (see README)")
    ap.add_argument("--json", action="store_true", help="print the merged map once and exit")
    a = ap.parse_args()
    path = a.config.resolve() if a.config else None
    cfg, base = load_config(path), (path.parent if path else pathlib.Path.cwd())
    if a.json:
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(App(cfg, base).map(), ensure_ascii=False, indent=2))
    else:
        serve(cfg, base)
