"""Cairn Net module: the network as Cairn Net sees it (MikroTik switches), as the Network family.

router -> VLAN -> switch -> port -> device. Reads Cairn Net's GET /api/export (option url + token_file)
or a saved copy of it (option file).

Status (when the export carries the live `ifaces`, `health`, `resource` of Cairn Net 0.5): a port is ok
when its link runs, down when it does not; a device is ok when its MAC is seen on a running port; a
switch is warn above temp_warn degrees or cpu_warn percent, down when Cairn Net cannot reach it.

Options: url, token_file, ca_file | file; router (switch name; default: the one holding the most
VLAN addresses); skip (switch names left out, e.g. a test router); edit_url
("https://net.example/#ports/{switch}": the "Edit in Cairn Net" link); temp_warn (default 70);
cpu_warn (default 90); uplink ({name (default "Internet"), via (the name of the device it goes through,
e.g. the ISP box), aliases (e.g. the address an external monitor watches)}: a first element under the
router, ok while via's port runs); physical ({site, places, kinds}: the switches, and the devices of the kinds
in physical_kinds (default ["ap", "nas"]), in the Physical family; see "physical" in cairn-map.py).
"""
import ipaddress



def fetch(opt, ctx):
    d = ctx.get_json(url=opt.get("url", ""), file=opt.get("file", ""), token_file=opt.get("token_file", ""), ca_file=opt.get("ca_file", ""))
    w = lambda k, **v: k.format(**v)  # details in English, the page translates them
    skip = {s.lower() for s in opt.get("skip", [])}
    every = [s for s in d.get("switches", []) if s.get("name") and s["name"].lower() not in skip]
    sws = [s for s in every if not s.get("error")]
    if not sws:
        return {"nodes": []}
    by = {s["name"]: s for s in sws}
    rows = lambda s, k: s.get(k) or []
    router = by.get(opt.get("router")) or max(sws, key=lambda s: len(rows(s, "addresses")))
    edit = opt.get("edit_url", "")

    # VLANs of each switch's bridge table; the bridge's own (untagged) VLAN carries the bridge's address
    vlans_of = {s["name"]: {} for s in sws}  # switch -> vid -> set of member ports
    bridge_vid = {}
    for s in sws:
        for v in rows(s, "vlans"):
            members = set(split(v.get("current-tagged"))) | set(split(v.get("current-untagged")))
            for vid in split(v.get("vlan-ids")):
                vlans_of[s["name"]].setdefault(vid, set()).update(members)
                if "bridge" in split(v.get("current-untagged")):
                    bridge_vid[s["name"]] = vid
    ifname = {i.get("name"): i.get("vlan-id") for i in rows(router, "vlan_ifaces")}
    vlan_name, subnet = {}, {}
    if router["name"] in bridge_vid:
        ifname.setdefault("bridge", bridge_vid[router["name"]])
        vlan_name[bridge_vid[router["name"]]] = "bridge"
    for i in rows(router, "vlan_ifaces"):
        vlan_name[i.get("vlan-id")] = i.get("name")
    for a in rows(router, "addresses"):
        vid = ifname.get(a.get("interface"))
        if vid and a.get("disabled") != "true":
            subnet[vid] = str(ipaddress.ip_interface(a["address"]).network)
            gw = a["address"].split("/")[0]
            subnet.setdefault("gw:" + vid, gw)

    topo = d.get("topology") or {}
    links = {}  # (switch, port) -> switch across
    for l in topo.get("links") or []:
        links[(l["a"], l["a_via"])] = l["b"]
        links[(l["b"], l["b_via"])] = l["a"]
    pvid = {(s["name"], p.get("interface")): p.get("pvid") for s in sws for p in rows(s, "ports")}
    iface = {(s["name"], i.get("name")): i for s in sws for i in rows(s, "ifaces")}
    running = {k: i.get("running") == "true" for k, i in iface.items()}

    def health(s):
        """(level, detail) of a switch from its CPU and hottest sensor; None without live data."""
        temps = [num(h.get("value")) for h in rows(s, "health") if "temperature" in (h.get("name") or "")]
        temps = [t for t in temps if t is not None]
        cpu = num((s.get("resource") or {}).get("cpu-load"))
        if cpu is None and not temps:
            return None
        hot, busy = temps and max(temps) > opt.get("temp_warn", 70), cpu is not None and cpu > opt.get("cpu_warn", 90)
        parts = [f"CPU {cpu:.0f} %" if cpu is not None else "", f"{max(temps):.0f} °C" if temps else ""]
        flag = [w("hot")] * bool(hot) + [w("busy")] * bool(busy)
        return ("warn" if hot or busy else "ok"), "Cairn Net · " + " · ".join(flag + [p for p in parts if p])
    live = {s["name"]: health(s) for s in sws}
    status = []

    def link_status(nid, sw, p):
        i = iface.get((sw, p))
        if i is None:
            return
        if i.get("disabled") == "true":
            status.append({"id": nid, "level": "unknown", "detail": "Cairn Net · " + w("disabled")})
        else:
            status.append({"id": nid, "level": "ok" if running[(sw, p)] else "down", "detail": "Cairn Net · " + w("link up" if running[(sw, p)] else "link down")})

    rid = "net:" + router["name"].lower()
    nodes = [{"id": rid, "family": "network", "name": router["name"], "kind": "router",
              "aliases": [router["name"]], "attrs": {"switches": len(sws), "vlans": len({v for x in vlans_of.values() for v in x})}}]
    if live[router["name"]]:
        status.append({"id": rid, "level": live[router["name"]][0], "detail": live[router["name"]][1]})
    for s in every:
        if s.get("error"):  # a switch Cairn Net cannot reach: shown under the router, down
            nodes.append({"id": f"{rid}:{s['name'].lower()}", "family": "network", "parent": rid, "name": s["name"], "kind": "switch",
                          "aliases": [s["name"]], "attrs": {"order": -1}})
            status.append({"id": f"{rid}:{s['name'].lower()}", "level": "down", "detail": "Cairn Net · " + w("unreachable: {e}", e=s["error"])})
    up = opt.get("uplink")  # the way out (Internet), first under the router, through the device named "via"
    if up:
        via = next((dv for dv in topo.get("devices") or [] if (dv.get("name") or "").lower() == str(up.get("via") or "").lower() and dv.get("sw") in by), None)
        uid = f"{rid}:uplink"
        nodes.append({"id": uid, "family": "network", "parent": rid, "name": up.get("name") or "Internet", "kind": "internet",
                      "aliases": up.get("aliases") or [],
                      "attrs": {"order": -2, **({a: v for a, v in {"via": via.get("name"), "ip": via.get("ip"), "switch": via["sw"], "port": via["port"],
                                                                  "vlans": via.get("vids")}.items() if v} if via else {})}})
        if via and running.get((via["sw"], via["port"])) is not None:
            ok = running[(via["sw"], via["port"])]
            status.append({"id": uid, "level": "ok" if ok else "down",
                           "detail": "Cairn Net · " + w("seen on {p}" if ok else "port {p} is down", p=f"{via['sw']} {via['port']}")})
    panels = []
    used = {}  # (vid, switch, port) -> number of devices
    devices = []
    for dv in topo.get("devices") or []:
        if dv.get("sw") not in by:
            continue
        for vid in dv.get("vids") or [pvid.get((dv["sw"], dv["port"])) or "?"]:
            devices.append((vid, dv))
            used[(vid, dv["sw"], dv["port"])] = used.get((vid, dv["sw"], dv["port"]), 0) + 1

    all_vids = sorted({v for x in vlans_of.values() for v in x} | {v for v, _ in devices}, key=lambda v: int(v) if v.isdigit() else 1 << 30)
    for vid in all_vids:
        vnode = f"{rid}:vlan{vid}"
        n_dev = sum(1 for v, _ in devices if v == vid)
        nodes.append({"id": vnode, "family": "network", "parent": rid, "name": f"VLAN {vid}", "slug": f"vlan{vid}", "kind": "vlan",
                      "attrs": {"order": int(vid) if vid.isdigit() else 1 << 30, "vlan": vid, "interface": vlan_name.get(vid, ""),
                                "subnet": subnet.get(vid, ""), "gateway": subnet.get("gw:" + vid, ""), "devices": n_dev}})
        for s in sws:
            members = vlans_of[s["name"]].get(vid, set())
            ports = {p for (v, w, p) in used if v == vid and w == s["name"]}
            trunks = {p for p in members if (s["name"], p) in links}
            if not members and not ports:
                continue
            snode = f"{vnode}:{s['name'].lower()}"
            nodes.append({"id": snode, "family": "network", "parent": vnode, "name": s["name"], "kind": "router" if s is router else "switch",
                          "aliases": [s["name"]], "attrs": {"order": 0 if s is router else 1, "ports": len(ports | trunks),
                                                            "devices": sum(used.get((vid, s["name"], p), 0) for p in ports)}})
            if edit:
                panels.append({"id": snode, "type": "link", "title": "Edit in Cairn Net", "url": edit.replace("{switch}", s["name"])})
            if live[s["name"]]:
                status.append({"id": snode, "level": live[s["name"]][0], "detail": live[s["name"]][1]})
            for p in ports | trunks:
                link_status(f"{snode}:{p}", s["name"], p)
                up = running.get((s["name"], p))
                nodes.append({"id": f"{snode}:{p}", "family": "network", "parent": snode, "name": p, "kind": "link" if p in trunks else "port",
                              "attrs": {"to": links.get((s["name"], p), ""), "pvid": pvid.get((s["name"], p), ""),
                                        "link": "" if up is None else ("up" if up else "down"), "devices": used.get((vid, s["name"], p), 0)}})
    for vid, dv in devices:
        mac = dv.get("mac", "")
        name = dv.get("name") or ""  # unnamed: the core gives it the name of the same machine elsewhere (by MAC), else the MAC
        did = f"{rid}:vlan{vid}:{dv['sw'].lower()}:{dv['port']}:{mac}"
        up = running.get((dv["sw"], dv["port"]))
        if up is not None:  # in the switch's MAC table: seen lately, as long as its port runs
            status.append({"id": did, "level": "ok" if up else "down",
                           "detail": "Cairn Net · " + w("seen on {p}" if up else "port {p} is down", p=f"{dv['sw']} {dv['port']}")})
        nodes.append({"id": did, "family": "network",
                      "parent": f"{rid}:vlan{vid}:{dv['sw'].lower()}:{dv['port']}", "name": name, "kind": dv.get("kind") or "device",
                      "aliases": [x for x in (mac, dv.get("ip"), dv.get("name")) if x],
                      "attrs": {a: v for a, v in {"ip": dv.get("ip"), "mac": mac, "switch": dv["sw"], "port": dv["port"], "vlans": dv.get("vids")}.items() if v}})
    # the hardware itself, in the Physical family (the same machines are linked to their Network elements by alias)
    ph, phys = opt.get("physical"), getattr(ctx, "physical", None)
    if ph and phys:
        for s in every:
            nodes += phys(ph, s["name"], "router" if s is router else "switch", [s["name"]], {"model": (s.get("resource") or {}).get("board-name", "")} if s.get("resource") else {})
            h = live.get(s["name"]) or (("down", "Cairn Net · " + w("unreachable: {e}", e=s["error"])) if s.get("error") else None)
            if h:
                status.append({"id": "phys:" + s["name"].lower(), "level": h[0], "detail": h[1]})
        kinds = set(opt.get("physical_kinds", ["ap", "nas"]))
        forced = {k.lower() for k in (ph.get("kinds") or {})}
        for dv in topo.get("devices") or []:
            name = dv.get("name")
            if name and dv.get("sw") in by and (dv.get("kind") in kinds or name.lower() in forced):
                nodes += phys(ph, name, dv.get("kind") or "device", [dv.get("mac"), dv.get("ip"), name],
                              {a: v for a, v in {"ip": dv.get("ip"), "mac": dv.get("mac"), "switch": dv["sw"], "port": dv["port"]}.items() if v})
                up = running.get((dv["sw"], dv["port"]))
                if up is not None:
                    status.append({"id": "phys:" + name.lower(), "level": "ok" if up else "down",
                                   "detail": "Cairn Net · " + w("seen on {p}" if up else "port {p} is down", p=f"{dv['sw']} {dv['port']}")})
    return {"nodes": nodes, "status": status, "panels": panels}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def split(v):
    return [x for x in (v or "").split(",") if x]
