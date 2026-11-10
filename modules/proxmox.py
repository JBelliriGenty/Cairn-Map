"""Proxmox VE module: the live state of the cluster's nodes and guests (running or stopped, CPU, memory).

Reads GET /api2/json/cluster/resources with an API token (a PVEAuditor token is enough). Adds no
element of its own: its status and attributes attach to the Hypervisor elements by alias, so another
module (cairn_iac) draws the tree. Each node and guest is named "host:<name in lower case>" with the
aliases <name> and "vmid:<id>".

Options: url (one URL or a list tried in order, e.g. every node's https://pve1:8006/api2/json/cluster/resources)
| file (a saved copy, the JSON of that URL); token_file (the token's secret); token_id ("user@pve!name");
ca_file; macs (true: each guest's network MACs as aliases, so the device the switches see under that MAC joins
the guest, and takes its name when it has none; read from every guest's config, kept macs_every seconds, default 600);
expect_stopped (guest names that are stopped on purpose: ok instead of warn);
cpu_warn, mem_warn (0-1, default 0.9: warn above; memory for nodes only, a VM's memory includes its cache).
"""
import re
import time

MAC = re.compile(r"(?:^|[=,])(?:virtio|e1000e?|vmxnet3|rtl8139|hwaddr)=([0-9A-Fa-f:]{17})")
_macs = {"at": 0.0, "by": {}}  # ponytail: one cache per process, enough for one cluster


def guest_macs(opt, ctx, rows):
    """{(type, vmid): [MAC, ...]} from GET /nodes/<node>/<type>/<vmid>/config, re-read every macs_every seconds."""
    if time.time() - _macs["at"] < opt.get("macs_every", 600):
        return _macs["by"]
    urls = opt.get("url", "")
    bases = [u.split("/cluster/resources")[0] for u in ([urls] if isinstance(urls, str) else urls)]
    by = {}
    for r in rows:
        if r.get("type") in ("qemu", "lxc") and r.get("vmid") is not None and not r.get("template"):
            path = f"/nodes/{r['node']}/{r['type']}/{r['vmid']}/config"
            try:
                cfg = ctx.get_json(url=[b + path for b in bases], token_file=opt.get("token_file", ""), ca_file=opt.get("ca_file", ""),
                                   auth=f"PVEAPIToken={opt.get('token_id', '')}=")
            except Exception:  # noqa: BLE001 - one unreadable guest config must not hide the cluster
                continue
            cfg = cfg.get("data", cfg) if isinstance(cfg, dict) else {}
            by[(r["type"], r["vmid"])] = [m.group(1).upper() for k, v in cfg.items() if re.fullmatch(r"net\d+", k)
                                          for m in [MAC.search(str(v))] if m]
    _macs.update(at=time.time(), by=by)
    return by


def fetch(opt, ctx):
    tok = opt.get("token_id", "")
    d = ctx.get_json(url=opt.get("url", ""), file=opt.get("file", ""), token_file=opt.get("token_file", ""),
                     ca_file=opt.get("ca_file", ""), auth=f"PVEAPIToken={tok}=")
    rows = d.get("data", d) if isinstance(d, dict) else d
    calm = {s.lower() for s in opt.get("expect_stopped", [])}
    cpu_warn, mem_warn = opt.get("cpu_warn", 0.9), opt.get("mem_warn", 0.9)
    nodes, status = [], []
    macs = guest_macs(opt, ctx, rows) if opt.get("macs") and not opt.get("file") else {}
    for r in rows:
        kind = r.get("type")
        if kind not in ("node", "qemu", "lxc") or r.get("template"):
            continue
        name = r.get("node") if kind == "node" else r.get("name")
        if not name:
            continue
        on = r.get("status") in ("running", "online")
        cpu, mem, maxmem = r.get("cpu") or 0, r.get("mem") or 0, r.get("maxmem") or 0
        al = [name] + ([f"vmid:{r['vmid']}"] if r.get("vmid") is not None else []) + macs.get((kind, r.get("vmid")), [])
        hid = "host:" + name.lower()
        attrs = {"power": "on" if on else "off"}
        if on:
            attrs.update({"cpu_load": f"{cpu * 100:.0f} %",
                          "mem_used_mib": round(mem / 2**20), "mem_used_mib_total": round(maxmem / 2**20),
                          "uptime": span(r.get("uptime") or 0)})
        nodes.append({"id": hid, "aliases": al, "attrs": attrs})
        load = f"CPU {cpu * 100:.0f} %" + (f" · RAM {mem / maxmem * 100:.0f} %" if maxmem else "")
        busy = cpu > cpu_warn or (kind == "node" and maxmem and mem / maxmem > mem_warn)
        if on:
            level, detail = ("warn" if busy else "ok"), f"{'busy' if busy else 'running'} · {load}"
        elif kind == "node":
            level, detail = "down", "offline"
        else:
            level = "ok" if name.lower() in calm else "warn"
            detail = "stopped (expected)" if level == "ok" else "stopped"
        status.append({"id": hid, "aliases": al, "level": level, "detail": f"Proxmox · {detail}"})
    return {"nodes": nodes, "status": status}


def span(s):
    d, h = divmod(int(s) // 3600, 24)
    return f"{d} d {h} h" if d else f"{h} h {int(s) % 3600 // 60} min"
