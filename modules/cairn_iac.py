"""Cairn IaC module: the declared machines (Tofu + Ansible inventory) as the Hypervisor family, and the
physical ones (bare metal, "phys" in the export) in the Physical family.

Hypervisor: cluster -> node (a machine other machines run on) -> guest (VM, LXC). Physical: site ->
place -> group -> machine (see "physical" in cairn-map.py). Reads Cairn IaC's export: GET /api/export
(option url + token_file) or the output of `cairn-iac.py --json` (option file).

Options: url, token_file, ca_file | file; cluster (the cluster's name, default "Cluster");
edit_url ("https://iac.example/#{key}": the "Edit in Cairn IaC" link); skip (machine names left out);
upper_names (true: names in capitals, for inventories that write them in lower case); physical
({site, places, kinds}: fills the Physical family; a node is "node", other bare metal "server").
"""

KINDS = {"LXC": "lxc", "VM": "vm"}


def fetch(opt, ctx):
    d = ctx.get_json(url=opt.get("url", ""), file=opt.get("file", ""), token_file=opt.get("token_file", ""), ca_file=opt.get("ca_file", ""))
    skip = {s.lower() for s in opt.get("skip", [])}
    machines = [m for m in d.get("machines", []) if m["key"] not in skip and m["name"].lower() not in skip]
    cap = d.get("capacity") or {}
    hosts = {m["node"] for m in machines if m.get("node")} | set(cap)
    cluster = opt.get("cluster") or "Cluster"
    cid = "cluster:" + cluster.lower()
    edit = opt.get("edit_url", "")
    nodes = [{"id": cid, "family": "hypervisor", "name": cluster, "kind": "cluster",
              "attrs": {"nodes": len(hosts), "guests": sum(1 for m in machines if m.get("node") in hosts)}}]
    panels = []
    up = lambda n: n.upper() if opt.get("upper_names") else n
    for m in machines:
        if m.get("phys") and hasattr(ctx, "physical"):
            nodes += ctx.physical(opt.get("physical"), up(m["name"]), "node" if m["key"] in hosts else "server",
                                  [m["key"], m["name"], m.get("host"), m.get("ip")],
                                  {a: v for a, v in {"ip": m.get("ip"), "description": m.get("description"), "groups": m.get("groups"), "roles": m.get("roles")}.items() if v})
    for m in machines:
        k = m["key"]
        is_host = k in hosts
        if not is_host and m.get("node") not in hosts:
            continue  # bare metal that runs no guest: the Physical family's business, not this one
        t = m.get("tofu") or {}
        attrs = {"ip": m.get("ip") or "", "description": m.get("description") or "", "roles": m.get("roles") or [], "groups": m.get("groups") or []}
        if is_host:
            c = cap.get(k) or {}
            attrs.update({"guests": c.get("guests", 0), "vcpu": c.get("cores", 0), "memory_mib": c.get("memory", 0), "disk_gb": c.get("disk", 0)})
            tot = c.get("total") or {}
            if tot:
                attrs.update({"vcpu_total": tot.get("cores"), "memory_mib_total": tot.get("memory"), "disk_gb_total": tot.get("disk")})
        else:
            attrs.update({"vmid": m.get("id"), "vcpu": num(t.get("cores")), "memory_mib": num(t.get("memory")), "disk_gb": num(t.get("disk")),
                          "declared": "tofu" if t else "inventory"})
        nodes.append({"id": "host:" + k, "family": "hypervisor", "parent": cid if is_host else "host:" + m["node"],
                      "name": up(m["name"]), "kind": "node" if is_host else KINDS.get(t.get("kind"), "guest"),
                      "aliases": [x for x in (k, m["name"], m.get("host"), m.get("ip"), m.get("id") and f"vmid:{m['id']}") if x],
                      "attrs": {a: v for a, v in attrs.items() if v not in (None, "", [])}})
        if edit:
            panels.append({"id": "host:" + k, "type": "link", "title": "Edit in Cairn IaC", "url": edit.replace("{key}", k)})
    return {"nodes": nodes, "panels": panels}


def num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
