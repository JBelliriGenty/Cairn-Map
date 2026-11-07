# Cairn Map

A map of your infrastructure that starts from the big picture and goes down,
click by click, to one element: the families side by side, then

- **Physical**: site → kind (servers, storage, network, computers) or room
  / rack (a switch on the page) → machine;
- **Network**: router → the way out (Internet) and VLANs → switch → port →
  device;
- **Hypervisor**: cluster → node → guest (VM, LXC);
- **Services**: reverse proxy → service (its domains) → the server behind it;
- **Storage**: storage box → ZFS pool → dataset or share.

The same machine seen in several families is one element: its page links
the others ("Also in"), and states and dashboards follow it everywhere.

Cairn Map **stores nothing of its sources and writes nothing to them**.
Every source is a *module* that returns one JSON shape; the map merges them.
Editing stays in the tools that own the data (links "Edit in …"). The one
thing it keeps is its own Settings page (rooms, kinds, modules switched off),
in one file, and only when you give it `settings_file`.

Part of the Cairn family ([Cairn IaC](https://github.com/JBelliriGenty/Cairn-IaC),
[Cairn Net](https://github.com/JBelliriGenty/Cairn-Net), [Cairn NAS](https://github.com/JBelliriGenty/Cairn-NAS)). Python
standard library only, one file, one page.

## Run it

```sh
python3 cairn-map.py -c example/config.json      # http://127.0.0.1:8095
python3 cairn-map.py -c example/config.json --json   # the merged map, once
python3 test_cairn_map.py                        # self-check, prints "ok"
```

Docker: `docker build -t cairn-map .` then mount your config at
`/etc/cairn-map/config.json` (and the files it names).

## Two views

Switch with **Tiles / Map** at the top of any page; the choice is remembered
in the browser, the address (`#network/vlan10/core`) stays the same.

- **Tiles**: nested tiles, a breadcrumb, one address per level; a click goes
  down one level.
- **Map**: the same tree as neurons on one canvas. A core (the overview), a
  glowing point per family (a family with a single root is that root), and
  each level grows out of its parent as you zoom in (wheel, pinch, `+`/`−`):
  semantic zoom, so only the families and their roots show at first.
  Impulses run along the links, red towards a failing element; a point to
  watch or down has a beating ring. Hovering a point lights its links,
  including the same machine in another family. A click flies there, grows
  its next two levels and opens its details beside the map (below it on a
  phone), with its address. Drag to move; `0` shows everything. The layout
  is computed from the ids, so the same infrastructure always draws the same
  way. Light and dark follow the page's theme.

**Search**: `/` or `Ctrl K` (or the Search button) opens a palette over the
page: every word must appear in the name, IP, aliases (domains, MAC), kind,
family or path, accents and case aside; arrows choose, Enter goes.

**Keyboard**: `0` to `5` the overview and the five families, `t` tiles or
map, `u` or Backspace up one level, `m` the modules, `Esc` closes the
search, the details or the help, `?` lists them all. On the map, `+` `−`,
the arrows and `0` zoom, move and show everything.

Switching keeps the current element in place with an animated transition
(View Transitions API where the browser has it, none under
`prefers-reduced-motion`).

## Config

| Key | Default | |
|---|---|---|
| `title` | `Cairn Map` | page title |
| `lang` | `en` | `en` or `fr` |
| `listen` | `127.0.0.1:8095` | address and port |
| `trusted_proxies` | `[]` | behind an authenticating proxy (Authelia, oauth2-proxy…): requests only from these addresses, user from `user_header`. Empty: requests from this machine only (loopback) |
| `user_header`, `groups_header` | `Remote-User`, `Remote-Groups` | |
| `require_groups` | `[]` | one of these groups is needed (empty: any user) |
| `modules` | `[]` | see below |
| `settings_file` | `""` | the Settings page's file (created on the first save, in a writable folder). Empty: the page is read only |

**The Settings page** (`#settings`, key `s`): each machine of the Physical
family with its room or rack (free text, the rooms in use suggested) and its
kind, and every module with a switch. Saving sends `POST /api/settings`
(`{"places": {room: [machines]}, "kinds": {machine: kind}, "disabled":
[modules]}`, checked by the server, written atomically) and applies at once:
once saved, the page's rooms replace the modules' `places`, its kinds win
over theirs, and a module switched off is no longer read (its elements leave
the map).

Relative paths are read from the config file's folder.

## Modules

A module is declared in `modules`:

| Key | |
|---|---|
| `name` | unique, shown on the Modules page |
| `type` | `python` (default), `url` or `command` |
| `module` / `file` | `python`: a module shipped in `modules/` (`cairn_iac`), or the path of your own `.py` with `fetch(options, ctx)` |
| `url`, `token_file`, `ca_file`, `auth` | `url`: GET this JSON, with an optional token read from a file (sent as `Authorization: <auth><token>`, `auth` defaults to `Bearer `) and a CA bundle |
| `command` | `command`: a list (no shell), its standard output is the JSON |
| `options` | handed to a Python module |
| `interval` | seconds between two reads (default 60) |
| `timeout` | seconds (default 20) |
| `enabled` | `false` leaves it out |

A module that fails keeps its last good data on the map; a banner says which
module stopped answering and since when. Items that do not fit the format are
dropped and counted.

### The format

```json
{
  "nodes":  [{"id": "host:web", "family": "hypervisor", "parent": "host:pve1", "name": "WEB", "kind": "lxc",
              "aliases": ["web", "10.0.10.21"], "attrs": {"ip": "10.0.10.21", "vcpu": 2}}],
  "status": [{"id": "10.0.10.21", "level": "warn", "detail": "backup is 3 days old"}],
  "panels": [{"id": "host:web", "type": "link", "title": "Edit in Cairn IaC", "url": "https://iac.example/#web"}]
}
```

- Every `status`, `panel` and family-less node may carry `aliases` too: it
  attaches to every element its `id` or one of its aliases names, once.
- `nodes`: `family` is one of `physical`, `network`, `hypervisor`,
  `services`, `storage`; `parent` is a node of the same family (none: a top
  element); `slug` (optional) names the element in the address
  (`#network/vlan10/core`); `attrs` are free (known keys get a label:
  `ip`, `mac`, `vcpu`, `memory_mib`, `disk_gb`, `roles`… and a `_total`
  twin shows "used / total"; `order` sorts siblings).
- **Merge by id**: two modules naming the same `id` describe the same
  element. The first module (config order) wins a field, later ones fill
  what is missing; `attrs` and `aliases` add up.
- **Aliases** (name, IP, MAC…) hook a source that does not know the ids: a
  `status`, a `panel` or a node *without family* whose `id` is an alias of
  an element attaches to it. Elements of two families that share an id or an
  alias are the same thing seen twice: the page links them ("Also in").
- A node without a `name` (a server known by its address) takes the name of
  the same element in another family, the one nearest the top of its tree;
  else its first alias.
- `status.level`: `ok`, `unknown`, `warn`, `down`, with a `detail` line,
  written in English, parts separated by ` · ` ("Proxmox · running · CPU 3 %"):
  the page translates the parts it knows into its own language. The
  worst level of an element and of everything under it colours its dot, up
  to its family and the overview; the element's page lists every state.
- `panels`: `link` (`url`), `value` (`title`, `value`, `unit`, or `time`:
  a unix time shown as an age, "20 h ago"), `table` (`title`, `columns`,
  `rows`; tables of the same title and columns on one element are shown as
  one), `series` (`title`, `unit`, `max`, `start`, `step`, `lines`:
  `[{"name", "values": [...]}]`, one value per step, `null` for a gap): a
  curve. Units `%`, `B/s` and `B` are scaled for reading (kB/s, MB/s…).
- `GET /api/map` keeps each series line's last value only (`last`); the
  points come from `GET /api/panels/<id>` when the element's page opens, so
  the map stays light.

### Shipped modules

**`cairn_iac`** — the Hypervisor family from
[Cairn IaC](https://github.com/JBelliriGenty/Cairn-IaC): cluster → node (a
machine others run on) → guest (VM, LXC). Reads its `GET /api/export`
(`url` + `token_file`, Cairn IaC's `export_token_file`) or the output of
`cairn-iac.py --json` (`file`). Options: `cluster` (name), `edit_url`
(`https://iac.example/#{key}`), `skip`, `upper_names`, `physical` (see
below: its bare metal, "phys" in the export, in the Physical family; a
machine guests run on is a `node`, other bare metal a `server`).

**`cairn_net`** — the Network family from Cairn Net (MikroTik switches):
router → VLAN → switch → port (or link to another switch) → device. Reads
its `GET /api/export` (`url` + `token_file`, Cairn Net's
`export_token_file`) or a saved copy (`file`). A device seen in two VLANs
appears in both; a device with no VLAN seen sits under its port's PVID.
Options: `router` (default: the switch with the most addresses), `skip`
(switch names, e.g. a test router), `edit_url`
(`https://net.example/#ports/{switch}`), `physical` (see below: the
switches, and the devices of the kinds in `physical_kinds`, default
`["ap", "nas"]`, in the Physical family), `uplink` (`{"name": "Internet",
"via": "isp-box", "aliases": ["1.1.1.1"]}`: a first element under the router
for the way out, through the device named `via` (ok while its port runs);
its aliases catch an external monitor, e.g. of `1.1.1.1`).

**The Physical family** is filled by the modules that know machines
(`cairn_iac`, `cairn_net`; your own through `ctx.physical(...)`), each with
the same `physical` option: `site` (the top's name), `places` (`{"Rack":
["pve1", "core"]}`: a room or rack, optional) and `kinds` (`{"nas": "nas"}`:
corrects a module's guess). Machines are grouped by kind: servers (`node`,
`server`), storage (`nas`), network (`router`, `switch`, `ap`), computers
(`pc`). Once a place is declared, a switch on the family's page groups them
by place instead (`GET /api/map?places=1`; the others under "No place"),
remembered by the browser; a machine's place is its attribute `location`. Each is
`phys:<name in lower case>`, so two modules naming it merge, and its aliases
(name, IP, MAC) link it to its Network and Hypervisor twins.

**`traefik`** — the Services family from a
[Traefik](https://traefik.io) reverse proxy: proxy → service → server. Reads
`GET /api/http/routers` and `/api/http/services` (the routers and services
only, never the middlewares, which may hold secrets). Expose just those, read
only, on an entry point the map can reach, e.g. in a dynamic file:

```yaml
http:
  routers:
    map-api:
      entryPoints: [metrics]
      rule: "Method(`GET`) && (Path(`/api/http/routers`) || Path(`/api/http/services`))"
      service: api@internal
```

A service carries the domains of its routers (its aliases: a monitor of
`https://app.example` attaches to it), its entry points and middlewares; a
server is known by its address and takes the name of the same machine
elsewhere. A health-checked server is ok or down; a router Traefik flags puts
its service in warn. Internal and unused services are left out. Options:
`url` (the API's base, or a list), `name` (default `Traefik`), `host` (the
machine it runs on, an alias), `token_file`, `ca_file`, `skip`, or `file`
(see `example/traefik.json`).

**`cairn_nas`** — the Storage family from
[Cairn NAS](https://github.com/JBelliriGenty/Cairn-NAS) panels: machine →
ZFS pool → dataset (→ child datasets). Reads each panel's `GET /api/slow`
with the bearer token of its `summary_token_file`: pools (health, size, use,
fragmentation), datasets and volumes (used, available, quota, mount point),
NFS exports and, from Cairn NAS 0.2.1, the SMB shares it manages (a dataset
shared over NFS or SMB is a `share`, with its NFS clients, SMB share names
and users). A
pool is ok when ONLINE and under `capacity_warn` % (default 80), warn above
or when DEGRADED, down otherwise; a machine that does not answer is down,
the others still show. Options: `machines` (`[{name, url}]`, `url` = the
panel's base, or `{name, file}` with a saved copy of `/api/slow`),
`token_file`, `ca_file`, `capacity_warn`, `skip` (datasets left out, with
their children).

**`proxmox`** — the live state of a Proxmox VE cluster: each node and guest
running or stopped, CPU, memory, uptime. Adds no element: its states attach
to the Hypervisor elements by alias (`host:<name>`, `<name>`,
`vmid:<id>`). Reads `GET /api2/json/cluster/resources`; a read-only token is
enough:

```sh
pveum user add map@pve
pveum acl modify / --users map@pve --roles PVEAuditor
pveum user token add map@pve map --privsep 0     # prints the secret once
```

Options: `url` (one URL or a list tried in order: one per node, so a node
down does not blind the module), `token_id` (`map@pve!map`), `token_file`
(the secret), `ca_file`, `expect_stopped` (guests stopped on purpose: ok
instead of warn), `cpu_warn`, `mem_warn` (0–1, default 0.9; memory for nodes
only), or `file` (a saved copy of that URL).

**`uptime_kuma`** — [Uptime Kuma](https://github.com/louislam/uptime-kuma)
monitors: state, uptime over 24 h and 30 days, response time, read from the
Prometheus that scrapes its `/metrics` (no key of its own). A monitor
attaches to what it watches by alias: its hostname (not for DNS monitors),
its URL's host and first label, the words of its name (`Pi-hole (DNS1)` →
`dns1`). One table per element lists its monitors. Options: `prometheus`
(base URL), `selector` (default `job="uptime-kuma"`), `token_file`,
`ca_file`, `skip`, or `file` (see `example/kuma-prometheus.json`).

**`prometheus`** — each element's dashboard: curves over the last 24 h,
the last backup, a link to Grafana. Adds no element: panels attach by
alias. Every query is an option, so any exporter works; the default is
[node_exporter](https://github.com/prometheus/node_exporter) (CPU, memory,
disk `/`, network), one series per element named by the label `by`
(default `instance`; `10.0.10.21:9100` also gives `10.0.10.21`). In a
query, `$sel` is replaced by `selector` (default `job="node"`) and `$by` by
`by`. Options: `prometheus` (base URL), `token_file`, `ca_file`, `by`,
`selector`, `range` (seconds, default 86400), `step` (default 900),
`series` (`[{title, unit, max, query, line}]`, `line` naming the label that
splits a series into lines, e.g. `direction`), `backup` (`{query, label,
warn_hours}`: a query giving each element's last backup as a unix time, the
label naming the element; older than `warn_hours` = warn; for Proxmox
Backup Server's [pbs-exporter](https://github.com/natrontech/pbs-exporter):
`max by (vm_name) (pbs_snapshot_vm_last_timestamp)`, label `vm_name`),
`grafana_url` (`https://grafana.example/d/hosts?var-instance={name}`),
`skip`, or `file` (see `example/prometheus.json`).

With OpenTelemetry's hostmetrics instead of node_exporter, `by: host_name`
and, for the CPU:
`100 * (1 - sum by ($by) (rate(system_cpu_time_seconds_total{state="idle",$sel}[5m])) / sum by ($by) (rate(system_cpu_time_seconds_total{$sel}[5m])))`.

On the element's page the curves sit under its state: the last value, the
maximum and the average, the value at any hour under the pointer. On the
map, zoomed in on an element (the current or hovered one), its percentages
ring the point and its last values hang under its name.

The `cairn_net` module also gives states when Cairn Net (0.5+) exports the
live interfaces: a port is ok when its link runs and down when it does not, a
device ok when its MAC is seen on a running port, a switch warn when hot
(`temp_warn`, default 70 °C) or busy (`cpu_warn`, default 90 %), down when
Cairn Net cannot reach it.

## Write your own module

The map knows no source by heart: anything that prints the format above is a
module. Three ways, from the simplest:

1. **A URL** that returns the JSON, in any language, anywhere:

   ```json
   {"name": "backups", "type": "url", "url": "https://backup.example/cairn-map.json",
    "token_file": "backups.token", "interval": 600}
   ```

2. **A command** run on the map's machine (no shell; its standard output is
   the JSON, a non-zero exit is an error):

   ```json
   {"name": "disks", "type": "command", "command": ["/usr/local/bin/disk-state"], "interval": 300, "timeout": 30}
   ```

3. **A Python file** with `fetch(options, ctx)` returning a dict;
   `ctx.get_json(url=…, file=…, token_file=…, ca_file=…, auth=…)` (or
   `ctx.get_text`, the same as text) reads a source (paths relative to the
   config), `ctx.physical(options, name, kind, aliases, attrs)` gives the
   nodes that place a machine in the Physical family, `ctx.lang` is the
   config's language (write details in English all the same: the page
   translates the ones it knows):

   ```json
   {"name": "mine", "type": "python", "file": "my_module.py", "options": {"warn_days": 2}}
   ```

Example, a command that marks hosts whose last backup is too old. It does not
know the map's ids: the host name or IP is enough, as an `id` or an alias.

```python
#!/usr/bin/env python3
import json, time
last = {"web": time.time() - 3 * 86400, "10.0.10.22": time.time() - 3600}  # from your backup tool
out = {"status": [], "panels": []}
for host, t in last.items():
    days = (time.time() - t) / 86400
    out["status"].append({"id": host, "level": "warn" if days > 2 else "ok",
                          "detail": f"Backup: {days:.1f} days ago"})
    out["panels"].append({"id": host, "type": "value", "title": "Last backup", "value": f"{days:.1f}", "unit": " d"})
print(json.dumps(out))
```

Elements the module creates need a `family` and, below the top, a `parent`
of the same family; elements it only enriches need neither. Test it with
`python3 cairn-map.py -c config.json --json`: a module in error is listed
with its message under `modules`, items that do not fit are counted in
`dropped`.

## Security

Read-only, except the Settings page: its `POST /api/settings` only takes a
same-origin JSON body (no form can send one), checked against a closed
shape, and writes `settings_file` only; without `settings_file` there is no
state on disk at all. Behind a proxy, only the proxy's
addresses are answered and the user header is required; tokens of URL
modules are read from files, never from the config. The page's CSP allows
no outside resource.

## Licence

MIT.
