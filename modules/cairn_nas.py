"""Cairn NAS module: the Storage family, from Cairn NAS panels (Debian + ZFS storage boxes).

machine -> pool -> dataset (-> its child datasets). Reads each machine's GET /api/slow, the panel's own
read-only data (open to the bearer token of its "summary_token_file"): ZFS pools (health, size, use),
datasets and volumes (used, available, quota, mount point), the NFS exports (a dataset's clients) and,
from Cairn NAS 0.2.1, the SMB shares the panel manages (a dataset's share names and users).

Status: a pool is ok when ONLINE and under capacity_warn % used, warn above it or when DEGRADED, down
otherwise (FAULTED, UNAVAIL…). A machine that does not answer is down; the others still show.

Options: machines ([{name, url | file}]: url = the panel's base, e.g. http://nas:9091; file = a saved
copy of /api/slow); token_file, ca_file; capacity_warn (default 80); skip (dataset names left out, with
their children).
"""


def fetch(opt, ctx):
    warn = float(opt.get("capacity_warn", 80))
    skip = set(opt.get("skip", []))
    nodes, status, failed = [], [], []
    for m in opt.get("machines") or []:
        name = m["name"]
        mid = "nas:" + name.lower()
        try:
            raw = ctx.get_text(file=m["file"]) if m.get("file") else ctx.get_text(
                url=m["url"].rstrip("/") + "/api/slow", token_file=opt.get("token_file", ""), ca_file=opt.get("ca_file", ""))
        except Exception as e:  # noqa: BLE001 - one machine down keeps the others
            nodes.append({"id": mid, "family": "storage", "name": name, "kind": "nas", "aliases": [name]})
            status.append({"id": mid, "level": "down", "detail": f"Cairn NAS · unreachable: {e}"})
            failed.append(name)
            continue
        pools, datasets, exports, smb = parse(raw)
        nodes.append({"id": mid, "family": "storage", "name": name, "kind": "nas", "aliases": [name],
                      "attrs": {"pools": len(pools), "datasets": sum(1 for d in datasets if "/" in d["name"])}})
        for p, a in pools.items():
            pid = f"{mid}:{p}"
            size, used = num(a.get("size")), num(a.get("allocated"))
            cap = num(a.get("capacity"))
            nodes.append({"id": pid, "family": "storage", "parent": mid, "name": p, "kind": "pool",
                          "attrs": {k: v for k, v in {"health": a.get("health"), "used_b": used, "used_b_total": size, "capacity": cap,
                                                      "fragmentation": num(a.get("fragmentation"))}.items() if v is not None}})
            health = a.get("health", "")
            level = ("ok" if cap is None or cap < warn else "warn") if health == "ONLINE" else "warn" if health == "DEGRADED" else "down"
            status.append({"id": pid, "level": level, "detail": f"Cairn NAS · {health}" + (f" · {cap:g} % used" if cap is not None else "")})
        for d in datasets:
            n = d["name"]
            if "/" not in n or any(n == s or n.startswith(s + "/") for s in skip):
                continue
            parent = n.rsplit("/", 1)[0]
            clients, shares = exports.get(d["mountpoint"], []), smb.get(d["mountpoint"], [])
            nodes.append({"id": f"{mid}:{n}", "family": "storage", "parent": f"{mid}:{parent}", "name": n.rsplit("/", 1)[1], "slug": n.rsplit("/", 1)[1],
                          "kind": "volume" if d["type"] == "volume" else "share" if clients or shares else "dataset",
                          "attrs": {k: v for k, v in {"dataset": n, "used_b": d["used"], "avail_b": d["avail"], "quota_b": d["quota"] or None,
                                                      "mountpoint": d["mountpoint"] if d["mountpoint"] not in ("-", "none", "legacy") else None,
                                                      "nfs": clients, "smb": [n for n, _ in shares],
                                                      "smb_users": sorted({u for _, us in shares for u in us})}.items() if v}})
    if failed and len(failed) == len(opt.get("machines") or []):
        raise RuntimeError("no machine answers: " + ", ".join(failed))
    return {"nodes": nodes, "status": status}


def parse(raw):
    """/api/slow is the panel's raw command outputs, joined by "@@" lines; each part is told by its shape:
    `zpool get -Hp` (pool, property, value, source), `zfs list -Hp -o name,used,avail,refer,ratio,
    compression,recordsize,quota,mountpoint,autosnap,type,…` (13 columns), /etc/exports (paths), the
    panel's smb.conf ("[share]" sections: path, valid users)."""
    pools, datasets, exports, smb = {}, [], {}, {}
    for part in raw.split("\n@@\n"):
        lines = [l for l in part.splitlines() if l.strip()]
        rows = [l.split("\t") for l in lines]
        if rows and all(len(r) == 4 for r in rows) and any(r[1] == "health" for r in rows):
            for p, k, v, _ in rows:
                pools.setdefault(p, {})[k] = v
        elif rows and all(len(r) >= 11 for r in rows) and not any("@" in r[0] for r in rows):
            datasets = [{"name": r[0], "used": num(r[1]), "avail": num(r[2]), "quota": num(r[7]), "mountpoint": r[8], "type": r[10]} for r in rows]
        elif lines and all(l.startswith("/") for l in lines) and "\t" not in part:
            for l in lines:
                path, *clients = l.split()
                exports[path] = [c.split("(", 1)[0] for c in clients]
        elif any(l.startswith("[") and l.rstrip().endswith("]") for l in lines):
            name = None
            for l in lines:
                k, _, v = l.strip().partition("=")
                if l.startswith("["):
                    name, users = l.strip()[1:-1], []
                elif name and k.strip() == "valid users":
                    users[:] = v.split()  # "@group" stays as written
                elif name and k.strip() == "path":
                    smb.setdefault(v.strip(), []).append((name, users))
    return pools, datasets, exports, smb


def num(v):
    try:
        return float(v) if "." in str(v) else int(v)
    except (TypeError, ValueError):
        return None
