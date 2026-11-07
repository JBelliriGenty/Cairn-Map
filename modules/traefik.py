"""Traefik module: the Services family, from the routes of a Traefik reverse proxy.

proxy -> service -> server. Reads Traefik's API, GET <url>/api/http/routers and /api/http/services
(read only; the routers and services are enough, the middlewares are never read). A service is named
after Traefik's service, carries the domains of the routers that use it (its aliases: an Uptime Kuma
monitor of https://app.example attaches to it) and has one child per server behind it, known by its
address (its alias: the same machine in the other families gives it its name). Internal services
(api@internal, noop@internal…) are left out.

Status: a server Traefik health-checks is ok (UP) or down (DOWN); a router Traefik flags (missing
middleware, bad rule…) puts its service in warn.

Options: url (the API's base, e.g. http://proxy:8082, or a list) | file (a saved copy: {"routers":
[...], "services": [...]}); token_file, ca_file; name (the proxy's name, default "Traefik"); host (the
machine it runs on: an alias, so the proxy links to that machine elsewhere); skip (service names left out).
"""
import re
import urllib.parse


def fetch(opt, ctx):
    if opt.get("file"):
        d = ctx.get_json(file=opt["file"])
        routers, services = d.get("routers") or [], d.get("services") or []
    else:
        urls = [opt["url"]] if isinstance(opt["url"], str) else opt["url"]
        get = lambda path: ctx.get_json(url=[u.rstrip("/") + path for u in urls], token_file=opt.get("token_file", ""), ca_file=opt.get("ca_file", ""))
        routers, services = get("/api/http/routers?per_page=1000"), get("/api/http/services?per_page=1000")
    skip = {s.lower() for s in opt.get("skip", [])}
    name = opt.get("name") or "Traefik"
    root = "svc:" + name.lower()
    nodes = [{"id": root, "family": "services", "name": name, "kind": "proxy", "aliases": [opt["host"]] if opt.get("host") else [],
              "attrs": {"host": opt.get("host", "")} if opt.get("host") else {}}]
    status = []
    # routers by the service they send to (a router names a service of its own provider without "@provider")
    used = {}
    for r in routers:
        svc = r.get("service") or ""
        if "@" not in svc and "@" in (r.get("name") or ""):
            svc += "@" + r["name"].split("@", 1)[1]
        used.setdefault(svc, []).append(r)
    for s in services:
        full = s.get("name") or ""
        short = full.split("@", 1)[0]
        if not short or full.endswith("@internal") or short.lower() in skip or full not in used:
            continue
        rs = used[full]
        hosts = list(dict.fromkeys(h for r in rs for h in re.findall(r"Host\(([^)]*)\)", r.get("rule") or "") for h in re.findall(r"`([^`]+)`", h)))
        sid = f"{root}:{short.lower()}"
        servers = [x.get("url") or x.get("address") or "" for x in (s.get("loadBalancer") or {}).get("servers") or []]
        nodes.append({"id": sid, "family": "services", "parent": root, "name": short, "kind": "service", "aliases": hosts,
                      "attrs": {a: v for a, v in {"hosts": hosts, "entrypoints": sorted({e for r in rs for e in r.get("entryPoints") or []}),
                                                  "middlewares": sorted({m.split("@", 1)[0] for r in rs for m in r.get("middlewares") or []}),
                                                  "servers": len(servers)}.items() if v}})
        for r in rs:
            if r.get("status") not in (None, "enabled"):
                status.append({"id": sid, "level": "warn", "detail": f"Traefik · {r.get('name')} · {'; '.join(r.get('error') or []) or r.get('status')}"})
        for u in servers:
            host = urllib.parse.urlsplit(u if "://" in u else "//" + u).hostname or u
            bid = f"{sid}:{u}"
            # a server named by its domain is also known by its first label ("db.example" -> "db")
            al = [host] if re.fullmatch(r"[\d.:]+", host) else [host, host.split(".")[0]]
            nodes.append({"id": bid, "family": "services", "parent": sid, "name": "", "slug": host, "kind": "server", "aliases": al, "attrs": {"url": u}})
            up = (s.get("serverStatus") or {}).get(u)
            if up:
                status.append({"id": bid, "level": "ok" if up == "UP" else "down", "detail": "Traefik · " + ("server up" if up == "UP" else "server down")})
    return {"nodes": nodes, "status": status}
