"""Uptime Kuma module: the monitors' state, uptime over 24 h and 30 days and response time, from the
Prometheus that scrapes Uptime Kuma's /metrics (no key of its own).

A monitor attaches by alias to the elements it watches: its hostname (IP or name; not for DNS monitors), its URL's host
and that host's first label (https://web.example:8443 -> "web.example", "web"), and the words of its
name ("Pi-hole (DNS1)" -> "pi-hole", "dns1"). A monitor that names no known element shows nowhere.

Options: prometheus (base URL, e.g. http://prom:9090) | file (a saved copy: {"status": <result of
monitor_status>, "time": <monitor_response_time>, "day": <24 h uptime>, "month": <30 d uptime>},
each the "result" list of a Prometheus instant query); token_file, ca_file (a Prometheus behind a
token); selector (label filter, default 'job="uptime-kuma"'); skip (monitor names left out).
"""
import re
import urllib.parse

STATE = {"1": ("ok", "up"), "0": ("down", "down"), "2": ("warn", "pending"), "3": ("unknown", "maintenance")}
BY = "monitor_name, monitor_type, monitor_url, monitor_hostname"


def fetch(opt, ctx):
    if opt.get("file"):
        d = ctx.get_json(file=opt["file"])
    else:
        sel = opt.get("selector", 'job="uptime-kuma"')
        up = f"(monitor_status{{{sel}}} == bool 1)"
        q = {"status": f"max by ({BY}) (monitor_status{{{sel}}})", "time": f"max by ({BY}) (monitor_response_time{{{sel}}})",
             "day": f"avg by ({BY}) (avg_over_time({up}[24h:1m]))", "month": f"avg by ({BY}) (avg_over_time({up}[30d:5m]))"}
        base = opt["prometheus"].rstrip("/") + "/api/v1/query?query="
        d = {k: ctx.get_json(url=base + urllib.parse.quote(v), token_file=opt.get("token_file", ""), ca_file=opt.get("ca_file", ""))["data"]["result"]
             for k, v in q.items()}
    val = {k: {r["metric"].get("monitor_name"): float(r["value"][1]) for r in d.get(k) or []} for k in ("time", "day", "month")}
    skip = set(opt.get("skip", []))
    status, panels = [], []
    for r in d.get("status") or []:
        m = r["metric"]
        name = m.get("monitor_name") or ""
        if not name or name in skip:
            continue
        level, word = STATE.get(r["value"][1], ("unknown", r["value"][1]))
        ms, day, month = val["time"].get(name), val["day"].get(name), val["month"].get(name)
        al = hooks(m)
        status.append({"id": al[0] if al else name, "aliases": al, "level": level,
                       "detail": f"Uptime Kuma · {name} · {word}" + (f" · {pct(day)} (24 h)" if day is not None else "")})
        panels.append({"id": al[0] if al else name, "aliases": al, "type": "table", "title": "Uptime Kuma",
                       "columns": ["Monitor", "State", "24 h", "30 d", "Latency"],
                       "rows": [[name, word, pct(day), pct(month), (f"{ms:.0f} ms" if ms >= 10 else f"{ms:.1f} ms") if ms is not None else ""]]})
    return {"status": status, "panels": panels}


def hooks(m):
    """The names a monitor's labels give the element it watches."""
    out = []
    # a DNS monitor's hostname is the name it asks for, not the server it watches
    host = m.get("monitor_hostname") if m.get("monitor_type") != "dns" else ""
    for v in (host, urllib.parse.urlsplit(m.get("monitor_url") or "").hostname):
        if v and v != "null":
            out += [v, v.split(".")[0]] if not re.fullmatch(r"[\d.:]+", v) else [v]
    name = m.get("monitor_name") or ""
    out += [x for x in re.split(r"[^\w.-]+", name) if len(x) > 2]  # "Headplane (tailnet, HEIMDALL)" -> ..., "heimdall"
    return list(dict.fromkeys(x.lower() for x in out if x))


def pct(v):
    return "" if v is None else f"{v * 100:.2f} %".replace("100.00 %", "100 %")
