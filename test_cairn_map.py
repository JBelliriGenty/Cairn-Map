"""Cairn Map self-check: module format, merge by id and alias, tree, paths, cross-family links, the example modules.
Run: python test_cairn_map.py (prints "ok")."""
import importlib.util
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cairn_map", HERE / "cairn-map.py")
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)


def tree(*outputs):
    results = [cm.clean(o, f"m{i}")[0] for i, o in enumerate(outputs)]
    nodes, index = cm.merge(results)
    return nodes, cm.build(nodes, index)


# format: bad items are dropped and counted, never fatal
data, dropped = cm.clean({"nodes": [{"id": "a", "family": "network"}, {"id": "", "family": "network"}, {"id": "b", "family": "moon"}],
                          "status": [{"id": "a", "level": "on fire"}]}, "x")
assert [n["id"] for n in data["nodes"]] == ["a"] and dropped == 3
assert cm.clean("not a dict", "x") == ({"nodes": [], "status": [], "panels": []}, 1)

# merge by id: first module wins a field, later ones fill the gaps; attrs and aliases add up
nodes, roots = tree(
    {"nodes": [{"id": "host:a", "family": "hypervisor", "name": "A", "attrs": {"ip": "10.0.0.1"}, "aliases": ["10.0.0.1"]}]},
    {"nodes": [{"id": "host:a", "family": "hypervisor", "name": "other", "kind": "lxc", "attrs": {"ip": "x", "vcpu": 2}}],
     "status": [{"id": "10.0.0.1", "level": "down", "detail": "no ping"}],          # by alias
     "panels": [{"id": "host:a", "type": "link", "url": "https://x"}]},
    {"nodes": [{"id": "10.0.0.1", "attrs": {"uptime": "3 d"}}]})                      # no family: enriches by alias
a = nodes["host:a"]
assert a["name"] == "A" and a["kind"] == "lxc" and a["attrs"] == {"ip": "10.0.0.1", "vcpu": 2, "uptime": "3 d"}
assert a["sources"] == ["m0", "m1", "m2"] and a["level"] == "down" and len(a["panels"]) == 1
assert "10.0.0.1" not in nodes

# tree: children, unique slugs among siblings, a lone root is the family page, the worst level rolls up,
# an unknown parent makes a root, a parent cycle does not loop
nodes, roots = tree({
    "nodes": [{"id": "r", "family": "network", "name": "Core"},
              {"id": "v", "family": "network", "parent": "r", "name": "VLAN 10", "slug": "vlan10"},
              {"id": "s1", "family": "network", "parent": "v", "name": "Sw"},
              {"id": "s2", "family": "network", "parent": "v", "name": "sw"},
              {"id": "d", "family": "network", "parent": "s1", "name": "Été 2", "aliases": ["10.0.0.1"]},
              {"id": "h", "family": "hypervisor", "name": "Host", "aliases": ["10.0.0.1"]},
              {"id": "o", "family": "hypervisor", "parent": "nowhere", "name": "Orphan"},
              {"id": "c1", "family": "storage", "parent": "c2", "name": "c1"},
              {"id": "c2", "family": "storage", "parent": "c1", "name": "c2"}],
    "status": [{"id": "d", "level": "warn"}, {"id": "s2", "level": "ok"}]})
assert roots["network"] == ["r"] and nodes["r"]["path"] == []
assert nodes["d"]["path"] == ["vlan10", "sw", "ete-2"] and nodes["s2"]["path"] == ["vlan10", "sw-2"]
assert nodes["r"]["rollup"] == "warn" and nodes["s2"]["rollup"] == "ok" and nodes["s1"]["level"] == ""
assert roots["hypervisor"] == ["h", "o"] and nodes["o"]["path"] == ["orphan"]
assert nodes["d"]["also"] == ["h"] and nodes["h"]["also"] == ["d"]
assert roots["storage"] == [] and "path" not in nodes["c1"]

# the example config: both shipped modules and a command module
cfg = cm.load_config(HERE / "example" / "config.json")
assert cm.unknown_keys(json.loads((HERE / "example" / "config.json").read_text(encoding="utf-8"))) == []
assert cm.unknown_keys({"listn": "x", "modules": [{"name": "a", "intervall": 5, "zzz": 1}]}) == [
    "unknown key 'listn', did you mean 'listen'?",
    "unknown key in module 'a': 'intervall', did you mean 'interval'?", "unknown key in module 'a': 'zzz'"]
cfg["modules"][2]["command"][0] = sys.executable
m = cm.App(cfg, HERE / "example").map()
N = m["nodes"]
assert all(not x["error"] for x in m["modules"]), m["modules"]
hv = {x["name"]: x for x in N.values() if x["family"] == "hypervisor"}
assert hv["Lab"]["path"] == [] and hv["WEB"]["path"] == ["pve1", "web"] and hv["DB"]["kind"] == "vm"
assert "NAS" not in hv  # bare metal without guests: not the hypervisor's
assert hv["PVE1"]["attrs"]["vcpu_total"] == 16 and hv["DB"]["level"] == "warn" and hv["PVE2"]["rollup"] == "warn"
assert hv["WEB"]["panels"][0]["url"] == "https://iac.example/#web"
by_path = {"/".join(x["path"]): x for x in N.values() if x["family"] == "network"}
assert by_path["vlan10/core/ether2/web"]["kind"] == "server"
assert by_path["vlan10/core/ether1"]["kind"] == "link" and by_path["vlan10/core/ether1"]["attrs"]["to"] == "access"
assert by_path["vlan99/access/ether6"]["attrs"]["link"] == "down"
assert by_path["vlan10/access/ether5/printer"]["attrs"]["ip"] == "10.0.10.50"   # no VLAN seen: the port's PVID
assert by_path["vlan10"]["attrs"]["subnet"] == "10.0.10.0/24" and by_path["vlan99"]["attrs"]["interface"] == "mgmt99"
lab = next(x for x in N.values() if x["name"] == "lab")  # a switch Cairn Net cannot reach: under the router, down
assert lab["kind"] == "switch" and lab["level"] == "down" and lab["path"] == ["lab"] and not lab["children"]
web_net = by_path["vlan10/core/ether2/web"]
assert [N[j]["name"] for j in web_net["also"] if N[j]["family"] == "hypervisor"] == ["WEB"] and web_net["id"] in N[hv["WEB"]["id"]]["also"]

# live state: ports, devices and switches (cairn_net), Proxmox, Uptime Kuma, rolled up to the family root
lv = lambda x: [(st["source"], st["level"]) for st in x["status"]]
assert ("cairn-net", "down") in lv(by_path["vlan99/access/ether6"]) and lv(by_path["vlan10/core/ether2"]) == [("cairn-net", "ok")]
assert ("cairn-net", "down") in lv(by_path["vlan99/access/ether6/pve1"])           # its port does not run
assert lv(by_path["vlan99/access"])[0] == ("cairn-net", "warn") and "81 °C" in by_path["vlan99/access"]["status"][0]["detail"]
assert by_path["vlan10/core"]["level"] == "ok" and N[[i for i in m["roots"]["network"]][0]]["rollup"] == "down"
assert hv["WEB"]["attrs"]["power"] == "on" and hv["WEB"]["attrs"]["mem_used_mib_total"] == 2048 and hv["PVE1"]["attrs"]["uptime"] == "4 d 4 h"
assert ("proxmox", "warn") in lv(hv["DB"]) and ("proxmox", "ok") in lv(hv["PVE2"]) and "TPL" not in hv
assert ("proxmox", "ok") in lv(web_net)                                             # same machine, other family
assert ("uptime-kuma", "ok") in lv(hv["WEB"]) and ("uptime-kuma", "ok") in lv(hv["PVE1"])  # by URL host, by IP
assert ("uptime-kuma", "down") in lv(by_path["vlan10/access/ether5/printer"])
assert not any(st["source"] == "uptime-kuma" and "DNS" in st["detail"] for x in N.values() for st in x["status"])  # DNS: no host hook
kt = [p for p in hv["WEB"]["panels"] if p["type"] == "table"]
assert kt[0]["rows"] == [["Web (public)", "up", "100 %", "99.87 %", "42 ms"]] and len(kt) == 1
assert hv["Lab"]["rollup"] == "warn" and m["roots"]["hypervisor"] == [hv["Lab"]["id"]]

# dashboard (prometheus): curves attach by "ip:port" -> ip; /api/map carries each line's last value only,
# panels(id) the points; last backup as a time, too old = warn; a Grafana link per element seen
ser = {p["title"]: p for p in hv["WEB"]["panels"] if p["type"] == "series"}
assert list(ser) == ["CPU", "Memory", "Disk", "Network"] and all(p["points"] and "values" not in p["lines"][0] for p in ser.values())
assert ser["Memory"]["max"] == 100 and ser["Memory"]["lines"] == [{"name": "", "last": 65.8}]
assert [l["name"] for l in ser["Network"]["lines"]] == ["receive", "transmit"] and ser["Network"]["unit"] == "B/s"
assert [p["title"] for p in web_net["panels"] if p["type"] == "series"] == list(ser)          # same machine, other family
bk = next(p for p in hv["WEB"]["panels"] if p["type"] == "value")
assert bk["title"] == "Last backup" and bk["time"] == 1700006400 - 7200
assert ("prometheus", "ok") in lv(hv["WEB"]) and ("prometheus", "warn") in lv(hv["DB"])
assert any(p["type"] == "link" and p["url"].endswith("var-instance=10.0.10.21%3A9100") for p in hv["WEB"]["panels"])
assert [p["lines"][0]["last"] for p in hv["PVE1"]["panels"] if p["type"] == "series"] == [28.4]  # by IP
assert not any("10.9.9.9" in p["aliases"] for x in N.values() for p in x["panels"])            # attached nowhere
app = cm.App(cfg, HERE / "example")
full = {p["title"]: p for p in app.panels(hv["PVE1"]["id"])["panels"] if p["type"] == "series"}
v = full["CPU"]["lines"][0]["values"]
assert len(v) == 97 and v[40:48] == [None] * 8 and v[0] == 35 and full["CPU"]["step"] == 900   # a gap stays a gap
assert app.panels("nowhere") is None and cm.slim({"type": "value", "id": "x"}) == {"type": "value", "id": "x"}
pm = cm.load_python(HERE / "modules" / "prometheus.py")
assert pm.hooks("10.0.0.5:9100") == ["10.0.0.5:9100", "10.0.0.5"] and pm.hooks("[::1]:9100")[1] == "::1" and pm.hooks("WEB") == ["web"]
assert pm.age(.5) == "30 min" and pm.age(20) == "20 h" and pm.age(72) == "72 h"
# details are written in English (the page translates them)
assert "Proxmox · running · CPU 12 % · RAM 38 %" in [s["detail"] for s in hv["PVE1"]["status"]] and bk["value"] == "2 h ago"

# Physical (lot 5): site -> group by kind -> machine, from Cairn IaC (bare metal) and Cairn Net (switches,
# devices of physical_kinds); the same machine is linked to its other families and takes their state
ph = {"/".join(x["path"]): x for x in N.values() if x["family"] == "physical"}
assert m["roots"]["physical"] == ["site:lab"] and ph[""]["name"] == "Lab"
assert ph["servers/pve1"]["kind"] == "node" and ph["network/core"]["kind"] == "router" and ph["network/access"]["kind"] == "switch"
assert ph["storage/nas"]["kind"] == "nas" and [N[c]["name"] for c in ph[""]["children"]] == ["Servers", "Storage", "Network"]
assert ph["servers/pve1"]["attrs"]["location"] == "Rack" and "location" not in ph["network/access"]["attrs"]
assert sorted(N[j]["family"] for j in ph["servers/pve1"]["also"]) == ["hypervisor", "network"]
assert ("proxmox", "ok") in lv(ph["servers/pve1"]) and ph["network/lab"]["level"] == "down" and ph["network/access"]["level"] == "warn"
assert [p["title"] for p in ph["servers/pve1"]["panels"] if p["type"] == "series"] == ["CPU"]       # curves by IP
assert cm.physical(None, "x", "pc") == [] and cm.physical({}, "x", "pc")[-2]["name"] == "Computers"
# 1.1: the same family by place (the page's switch, api/map?places=1): site -> place -> machine, "No place" last
P = cm.App(cfg, HERE / "example").map(places=True)["nodes"]
pp = {"/".join(x["path"]): x for x in P.values() if x["family"] == "physical"}
assert sorted(pp) == ["", "no-place", "no-place/access", "no-place/lab", "no-place/nas", "rack", "rack/core", "rack/pve1", "rack/pve2"]
assert [P[c]["name"] for c in pp[""]["children"]] == ["Rack", "No place"] and pp["rack"]["kind"] == "place" and pp["rack"]["rollup"] == "ok"
assert pp["no-place"]["rollup"] == "down" and pp["rack/pve1"]["id"] == ph["servers/pve1"]["id"]

# 1.1: the way out, first under the router, through the ISP box; an external monitor of it attaches by alias
net = {"/".join(x["path"]): x for x in N.values() if x["family"] == "network"}
assert N[N[m["roots"]["network"][0]]["children"][0]]["kind"] == "internet" and net["internet"]["attrs"]["via"] == "isp-box"
assert lv(net["internet"]) == [("cairn-net", "ok")] and "1.1.1.1" in net["internet"]["aliases"]

# Services (lot 5): proxy -> service (its domains as aliases) -> server, internal and unused services left out;
# a nameless server takes the name of the same machine elsewhere; Traefik's states
sv = {"/".join(x["path"]): x for x in N.values() if x["family"] == "services"}
assert sorted(sv) == ["", "app", "app/10-0-10-30", "web", "web/10-0-10-21"] and sv[""]["kind"] == "proxy"
assert sv["web"]["attrs"]["hosts"] == ["web.example.org", "www.example.org"] and sv["web"]["attrs"]["middlewares"] == ["auth", "to-https"]
assert sv["web/10-0-10-21"]["name"] == "WEB" and sv["app/10-0-10-30"]["name"] == "10.0.10.30"
assert ("uptime-kuma", "ok") in lv(sv["web"]) and ("traefik", "down") in lv(sv["app/10-0-10-30"]) and sv["app"]["level"] == "warn"
assert hv["WEB"]["id"] in sv["web/10-0-10-21"]["also"] and sv[""]["rollup"] == "down"

# Storage (lot 5): machine -> pool -> dataset, from Cairn NAS's /api/slow; capacity and health give the state,
# NFS clients mark a share; a machine that does not answer is down, the others still show
st = {"/".join(x["path"]): x for x in N.values() if x["family"] == "storage"}
assert sorted(st) == ["gone", "nas", "nas/fast", "nas/tank", "nas/tank/data", "nas/tank/data/photos", "nas/tank/vm"]   # tank/scratch skipped
assert st["nas/tank"]["level"] == "warn" and st["nas/tank"]["attrs"]["used_b_total"] == 4000000000000 and st["nas/fast"]["level"] == "warn"
assert st["nas/tank/data"]["kind"] == "share" and st["nas/tank/data"]["attrs"]["nfs"] == ["10.0.10.21", "10.0.10.22"]
assert st["nas/tank/vm"]["kind"] == "volume" and st["nas/tank/data/photos"]["attrs"]["quota_b"] == 2500000000000
assert st["gone"]["level"] == "down" and ph["storage/nas"]["id"] in st["nas"]["also"]
nas = cm.load_python(HERE / "modules" / "cairn_nas.py")
assert nas.parse("a\tb\n@@\n/x 1.2.3.4(rw)\n") == ({}, [], {"/x": ["1.2.3.4"]}, {})
assert st["nas/tank/data/photos"]["kind"] == "share" and st["nas/tank/data/photos"]["attrs"]["smb"] == ["Photos"]   # 1.1: SMB
assert st["nas/tank/data/photos"]["attrs"]["smb_users"] == ["@family", "alice"]

# 1.2: the Settings page (settings_file): places replace the config's, a kind moves its machine (an empty
# group goes), a module switched off is no longer read; a body that does not fit is refused, nothing written
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    sapp = cm.App({**cfg, "settings_file": str(pathlib.Path(tmp) / "settings.json")}, HERE / "example")
    assert sapp.map()["settings"]["editable"] and all(x["on"] for x in sapp.map()["modules"])
    for bad in ({"places": {"x": "pve1"}}, {"kinds": {"pve1": "toaster"}}, {"disabled": ["nope"]}, {"other": 1}, [], {"places": {"": ["a"]}}):
        try:
            sapp.save_settings(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    assert not (pathlib.Path(tmp) / "settings.json").exists()
    st = sapp.save_settings({"places": {" Shelf ": ["nas"], "Empty": []}, "kinds": {"nas": "server"}, "disabled": ["notes"]})
    assert st == {"places": {"Shelf": ["nas"]}, "kinds": {"nas": "server"}, "disabled": ["notes"]}
    S = sapp.map()
    sp = {"/".join(x["path"]): x for x in S["nodes"].values() if x["family"] == "physical"}
    assert sp["servers/nas"]["attrs"]["location"] == "Shelf" and "location" not in sp["servers/pve1"]["attrs"]   # config's Rack replaced
    assert sp["servers/nas"]["kind"] == "server" and "storage" not in sp and "storage/nas" not in sp            # its old group went
    assert [x["name"] for x in S["modules"] if not x["on"]] == ["notes"]
    assert not any(st_["source"] == "notes" for x in S["nodes"].values() for st_ in x["status"])
    assert json.loads((pathlib.Path(tmp) / "settings.json").read_text(encoding="utf-8")) == st
    assert cm.App({**cfg, "settings_file": str(pathlib.Path(tmp) / "settings.json")}, HERE / "example").settings == st   # read back at start
    assert cm.apply_settings({}, {}) == {} and not cm.App(cfg, HERE / "example").map()["settings"]["editable"]

# a broken module keeps the map up and says why
cfg["modules"].append({"name": "gone", "type": "url", "url": "http://127.0.0.1:9/x.json", "timeout": 2})
m = cm.App(cfg, HERE / "example").map()
assert [x["name"] for x in m["modules"] if x["error"]] == ["gone"] and len(m["nodes"]) == len(N)
json.dumps(m)

# the page: nothing loaded from elsewhere (strict CSP), every literal t("...") has its French, no NUL byte
import re
html = (HERE / "page.html").read_text(encoding="utf-8")
assert "\0" not in html and not re.search(r"""(src|href)=["']?(https?:)?//""", html) and "@import" not in html
fr = set(re.findall(r'"((?:[^"\\]|\\.)+)":', html[html.index("const FR = {"):html.index("const ICONS")]))
missing = {k for k in re.findall(r'\bt\("((?:[^"\\]|\\.)+)"\s*[,)]', html) if k not in fr}
assert not missing, missing
assert 'data-view="${v}"' in html and "startViewTransition" in html and "prefers-reduced-motion" in html  # lot 3: map view
assert "api/panels/" in html and "<svg viewBox" in html and "function dash(" in html  # lot 4: curves, values on the map
assert "function palette(" in html and 'e.key === "?"' in html and "function trd(" in html  # lot 5: search, shortcuts, details translated
frd = set(re.findall(r'"((?:[^"\\]|\\.)+)":', html[html.index("const FRD = {"):html.index("const FRD_RE")]))
for mod in ("cairn_net", "proxmox", "prometheus", "traefik", "cairn_nas"):  # every fixed detail word has its French
    src = (HERE / "modules" / f"{mod}.py").read_text(encoding="utf-8")
    for w in re.findall(r'"(link up|link down|disabled|seen on \{p\}|port \{p\} is down|hot|busy|running|offline|stopped(?: \(expected\))?|server up|server down)"', src):
        assert w in frd, (mod, w)
# lot 7: in English every family and the guest kinds have their own spelling (not the lowercase key),
# and the names on the map make room for the points as well as for each other
en = dict(re.findall(r'(\w+): "([^"]*)"', html[html.index("const EN = {"):html.index("const FRD = {")]))
for k in list(m["families"]) + ["vm", "lxc"]:
    assert en.get(k, k) != k.lower() and en[k][0].isupper(), k
assert "const boxes = drawn.map(" in html and "b[2] > SW" in html and "id === FOCUS || id === HOVER) {  // the current or hovered name on an opaque pill" in html  # nor are they cut by the edge

# every key the code reads is in the configuration reference
doc = (HERE / "docs/configuration.md").read_text(encoding="utf-8")
missing = [k for k in [*cm.DEFAULTS, *cm.MODULE_KEYS, *cm.SETTINGS_KEYS, *cm.GROUPS] if f"`{k}`" not in doc]
assert not missing, missing
print("ok")
