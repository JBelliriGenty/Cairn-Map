"""Prometheus module: each element's dashboard, curves over the last 24 h (CPU, memory, disk, network by
default), the last backup, a link to Grafana. Adds no element: panels attach by alias.

Every query is an option, so any exporter works. A series query returns one series per element, named by
the label `by` (default "instance"; "10.0.0.5:9100" also gives "10.0.0.5"), and optionally one line per
value of the label `line` ("direction": receive, transmit). In queries, $sel is replaced by `selector`
and $by by `by`.

Options: prometheus (base URL) | file (a saved copy: {"end": <unix time>, "series": {<title>: <result of
the range query>}, "backup": <result of the instant query>}); token_file, ca_file; by, selector; range
(seconds, default 86400), step (default 900); series ([{title, unit, query, max, line}], default:
node_exporter's CPU, memory, disk /, network); backup ({query, label, warn_hours}: a query giving the
unix time of each element's last backup, the label naming the element; older than warn_hours = warn);
grafana_url (a link per element, {name} = its label value); skip (label values left out); macs (true, or
{query, label}: each element's network MACs as aliases, default node_exporter's node_network_info and its label
"address", so the device the switches see under that MAC joins the machine; in a saved copy, "macs": the result).
"""
import re
import time
import urllib.parse

MACS = 'node_network_info{address!="",$sel}'
NODE = [
    {"title": "CPU", "unit": "%", "max": 100,
     "query": '100 * (1 - avg by ($by) (rate(node_cpu_seconds_total{mode="idle",$sel}[5m])))'},
    {"title": "Memory", "unit": "%", "max": 100,
     "query": "100 * (1 - node_memory_MemAvailable_bytes{$sel} / node_memory_MemTotal_bytes{$sel})"},
    {"title": "Disk", "unit": "%", "max": 100,
     "query": '100 * (1 - node_filesystem_avail_bytes{mountpoint="/",$sel} / node_filesystem_size_bytes{mountpoint="/",$sel})'},
    {"title": "Network", "unit": "B/s", "line": "direction",
     "query": 'label_replace(sum by ($by) (rate(node_network_receive_bytes_total{device!="lo",$sel}[5m])), "direction", "receive", "", "")'
              ' or label_replace(sum by ($by) (rate(node_network_transmit_bytes_total{device!="lo",$sel}[5m])), "direction", "transmit", "", "")'},
]


def fetch(opt, ctx):
    by, sel = opt.get("by", "instance"), opt.get("selector", 'job="node"')
    span, step = int(opt.get("range", 86400)), int(opt.get("step", 900))
    series, backup = opt.get("series") or NODE, opt.get("backup") or {}
    q = lambda s: s.replace("$sel", sel).replace("$by", by)
    if opt.get("file"):
        d = ctx.get_json(file=opt["file"])
        end, res, last, macs = float(d["end"]), d.get("series") or {}, d.get("backup") or [], d.get("macs") or []
    else:
        end = (time.time() // step) * step
        base = opt["prometheus"].rstrip("/") + "/api/v1/"
        get = lambda path: ctx.get_json(url=base + path, token_file=opt.get("token_file", ""), ca_file=opt.get("ca_file", ""))["data"]["result"]
        res = {s["title"]: get("query_range?" + urllib.parse.urlencode({"query": q(s["query"]), "start": end - span, "end": end, "step": step}))
               for s in series}
        last = get("query?" + urllib.parse.urlencode({"query": q(backup["query"])})) if backup.get("query") else []
        mq = opt.get("macs")
        macs = get("query?" + urllib.parse.urlencode({"query": q(mq.get("query", MACS) if isinstance(mq, dict) else MACS)})) if mq else []
    skip, n = {x.lower() for x in opt.get("skip", [])}, span // step + 1
    panels, status, seen = [], [], {}
    for s in series:
        lines = {}
        for r in res.get(s["title"]) or []:
            name = r["metric"].get(by)
            if not name or name.lower() in skip:
                continue
            seen[name] = None
            vals = [None] * n
            for t, v in r.get("values") or []:
                i = round((float(t) - (end - span)) / step)
                if 0 <= i < n and v not in ("NaN", "+Inf", "-Inf"):
                    vals[i] = float(f"{float(v):.3g}")
            lines.setdefault(name, []).append({"name": r["metric"].get(s.get("line", ""), ""), "values": vals})
        for name, ls in lines.items():
            p = {"id": name, "aliases": hooks(name), "type": "series", "title": s["title"], "unit": s.get("unit", ""),
                 "start": end - span, "step": step, "lines": sorted(ls, key=lambda x: x["name"])}
            if s.get("max") is not None:
                p["max"] = s["max"]
            panels.append(p)
    lab, warn = backup.get("label", by), float(backup.get("warn_hours") or 0)
    for r in last:
        name = r["metric"].get(lab)
        if not name or name.lower() in skip:
            continue
        ts = float(r["value"][1])
        hours = (end - ts) / 3600
        panels.append({"id": name, "aliases": hooks(name), "type": "value", "title": "Last backup", "value": f"{age(hours)} ago",
                       "time": ts})
        if warn:
            status.append({"id": name, "aliases": hooks(name), "level": "warn" if hours > warn else "ok",
                           "detail": f"Backup · {age(hours)} ago" + (f" · older than {warn:g} h" if hours > warn else "")})
    if opt.get("grafana_url"):
        for name in seen:
            panels.append({"id": name, "aliases": hooks(name), "type": "link", "title": "Grafana",
                           "url": opt["grafana_url"].replace("{name}", urllib.parse.quote(name))})
    mlab = (opt.get("macs") or {}).get("label", "address") if isinstance(opt.get("macs"), dict) else "address"
    by_host = {}
    for r in macs:
        name, mac = r["metric"].get(by), r["metric"].get(mlab, "").upper()
        if name and name.lower() not in skip and re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", mac) and mac != "00:00:00:00:00:00":
            by_host.setdefault(name, []).append(mac)
    nodes = [{"id": name, "aliases": hooks(name) + sorted(set(ms))} for name, ms in by_host.items()]
    return {"nodes": nodes, "panels": panels, "status": status}


def hooks(v):
    """The names a label value gives its element: itself and, for "host:port", the host."""
    m = re.fullmatch(r"\[?([^\]]+?)\]?:\d+", v)
    return list(dict.fromkeys(x.lower() for x in (v, m.group(1) if m else "") if x))


def age(h):
    """In minutes or hours only, so the page translates "{h} ago" without units of its own."""
    return f"{h * 60:.0f} min" if h < 1 else f"{h:.0f} h"
