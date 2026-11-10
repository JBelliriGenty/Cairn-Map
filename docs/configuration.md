# Configuration reference

Everything Cairn Map reads or writes, key by key. The [README](../README.md)
explains what the map shows; this page is what you edit.

| File | Who writes it | |
|---|---|---|
| `config.json` (`-c`) | you | the page, the access rules, the modules |
| token files (`token_file`) | you | one secret per file, never in the config |
| `settings_file` | the Settings page | rooms, kinds, modules switched off |
| a module's output | your module | the JSON format the map merges |

Relative paths (`file`, `token_file`, `ca_file`, a Python module's `file`,
`settings_file`) are read from the config file's folder. With Docker, that
is the folder mounted at `/etc/cairn-map`.

Check a config without starting the server:

```sh
python3 cairn-map.py -c config.json --json
```

It prints the merged map. A module in error is listed with its message
under `modules`; items that do not fit the format are counted in `dropped`.
A module without a `name`, or two modules with the same one, stop the
program at once.

## config.json

| Key | Type | Default | |
|---|---|---|---|
| `title` | string | `"Cairn Map"` | page title |
| `lang` | `"en"` \| `"fr"` | `"en"` | page language |
| `listen` | `"host:port"` | `"127.0.0.1:8095"` | `"0.0.0.0:8095"` in Docker |
| `trusted_proxies` | list of IPs | `[]` | empty: only this machine (loopback) may connect. Set: only these addresses, and the user comes from `user_header` |
| `user_header` | string | `"Remote-User"` | |
| `groups_header` | string | `"Remote-Groups"` | comma-separated groups |
| `require_groups` | list | `[]` | the user needs one of these groups; empty: any user |
| `modules` | list | `[]` | see [Modules](#modules) |
| `settings_file` | path | `""` | the Settings page's file, created on the first save in a writable folder. Empty: the Settings page is read only |

A key nothing reads (a typo such as `listn`), here or in a module entry, is
reported at start on standard error with the closest known key ("did you
mean 'listen'?"), and otherwise ignored: the map still starts. Keys inside
a module's `options` are not checked, so spell those carefully.

## Modules

Each entry of `modules`:

| Key | Type | Default | |
|---|---|---|---|
| `name` | string | required | unique, shown on the Modules page |
| `type` | `"python"` \| `"url"` \| `"command"` | `"python"` | |
| `module` | string | `name` | `python`: a module shipped in `modules/` (`cairn_iac`, `proxmox`…) |
| `file` | path | | `python`: your own `.py` with `fetch(options, ctx)`, instead of `module` |
| `options` | object | `{}` | `python`: handed to the module, see below |
| `url` | URL | | `url`: GET this JSON |
| `token_file`, `ca_file` | path | | `url`: the token sent as `Authorization: <auth><token>`, the CA bundle |
| `auth` | string | `"Bearer "` | `url`: the prefix before the token |
| `command` | list | | `command`: run without a shell, its standard output is the JSON; a non-zero exit is an error |
| `interval` | seconds | `60` | between two reads |
| `timeout` | seconds | `20` | of one read |
| `enabled` | bool | `true` | `false` leaves it out entirely (the Settings page can also switch it off) |

A module that fails keeps its last good data on the map, and a banner says
which one stopped answering and since when.

**Order matters.** When two modules describe the same element, the first in
the list wins each field and the later ones fill what is missing (`attrs`
and `aliases` add up). Put the module you trust most for names first.

### Options of the shipped modules

Most modules read a live source (`url` or `prometheus`) or a saved copy
(`file`), handy to try a config or to write tests. Give one or the other.

#### `cairn_iac`: Hypervisor family (and Physical)

| Option | Default | |
|---|---|---|
| `url` + `token_file` | | Cairn IaC's `GET /api/export`, with its `export_token_file` |
| `file` | | or the output of `cairn-iac.py --json` |
| `ca_file` | | |
| `cluster` | `"Cluster"` | the cluster's name |
| `edit_url` | | the "Edit in Cairn IaC" link, `{key}` = the machine's key: `"https://iac.example/#{key}"` |
| `skip` | `[]` | machine names or keys left out |
| `upper_names` | `false` | names in capitals |
| `physical` | | see [The `physical` option](#the-physical-option) |

#### `cairn_net`: Network family (and Physical)

| Option | Default | |
|---|---|---|
| `url` + `token_file` | | Cairn Net's `GET /api/export`, with its `export_token_file` |
| `file` | | or a saved copy |
| `ca_file` | | |
| `router` | the switch with the most addresses | the top of the tree |
| `skip` | `[]` | switch names left out (a test router) |
| `edit_url` | | `{switch}` = the switch's name: `"https://net.example/#ports/{switch}"` |
| `temp_warn` | `70` | °C above which a switch is warn |
| `cpu_warn` | `90` | % above which a switch is warn |
| `uplink` | | `{"name": "Internet", "via": "isp-box", "aliases": ["1.1.1.1"]}`: the way out, ok while the port of the device `via` runs; its aliases catch an external monitor |
| `physical` | | see below; the switches go to the Physical family |
| `physical_kinds` | `["ap", "nas"]` | the device kinds that go there too |

#### `proxmox`: live state of a Proxmox VE cluster

| Option | Default | |
|---|---|---|
| `url` | | `https://pve1:8006/api2/json/cluster/resources`, or a list tried in order (one per node) |
| `file` | | or a saved copy of that URL |
| `token_id` | | `"map@pve!map"` |
| `token_file` | | the token's secret |
| `ca_file` | | |
| `expect_stopped` | `[]` | guests stopped on purpose: ok instead of warn |
| `macs` | `false` | read each guest's config for its network MACs: the device the switches see under one joins the guest (Also in) and, unnamed, takes its name |
| `macs_every` | `600` | seconds between two reads of the guests' configs |
| `cpu_warn` | `0.9` | 0 to 1 |
| `mem_warn` | `0.9` | 0 to 1, nodes only |

A read-only token is enough (`PVEAuditor`), see the README.

#### `traefik`: Services family

| Option | Default | |
|---|---|---|
| `url` | | the API's base (`http://proxy:8082`), or a list |
| `file` | | or a saved copy `{"routers": [...], "services": [...]}` |
| `token_file`, `ca_file` | | |
| `name` | `"Traefik"` | the proxy's name |
| `host` | | the machine it runs on (a name or IP), to link it to that machine |
| `skip` | `[]` | service names left out |

#### `cairn_nas`: Storage family

| Option | Default | |
|---|---|---|
| `machines` | required | `[{"name": "nas", "url": "http://nas:9091"}]`, or `{"name", "file"}` with a saved copy of `/api/slow` |
| `token_file` | | the panel's `summary_token_file` token |
| `ca_file` | | |
| `capacity_warn` | `80` | % used above which a pool is warn |
| `skip` | `[]` | datasets left out, with their children (`"tank/scratch"`) |

#### `uptime_kuma`: monitors, through Prometheus

| Option | Default | |
|---|---|---|
| `prometheus` | | the Prometheus that scrapes Uptime Kuma (`http://prom:9090`) |
| `file` | | or a saved copy (see `example/kuma-prometheus.json`) |
| `token_file`, `ca_file` | | a Prometheus behind a token |
| `selector` | `job="uptime-kuma"` | label filter |
| `skip` | `[]` | monitor names left out |

#### `prometheus`: curves, last backup, Grafana link

| Option | Default | |
|---|---|---|
| `prometheus` | | base URL |
| `file` | | or a saved copy (see `example/prometheus.json`) |
| `token_file`, `ca_file` | | |
| `by` | `"instance"` | the label that names the element (`host_name` with OpenTelemetry) |
| `selector` | `job="node"` | replaces `$sel` in the queries |
| `range` | `86400` | seconds shown |
| `step` | `900` | seconds between two points |
| `series` | node_exporter CPU, memory, disk `/`, network | `[{"title", "unit", "max", "query", "line"}]`; `$by` and `$sel` are replaced; `line` names the label that splits a series into lines |
| `backup` | | `{"query", "label", "warn_hours"}`: the last backup as a unix time per element; `label` defaults to `by`; no `warn_hours` = shown, never warn |
| `grafana_url` | | a link per element, `{name}` = its label value |
| `skip` | `[]` | label values left out |

Giving `series` replaces the four defaults: list every curve you want.

### The `physical` option

`cairn_iac` and `cairn_net` take the same `physical` object, which places
their machines in the Physical family. Give both modules the same one.

```json
"physical": {
  "site": "Lab",
  "places": {"Rack": ["pve1", "pve2", "core"], "Office": ["laptop"]},
  "kinds": {"nas": "nas", "laptop": "pc"}
}
```

| Key | Default | |
|---|---|---|
| `site` | `"Site"` | the top's name |
| `places` | `{}` | room or rack → machine names (any case). Once a place exists, the family's page can group by place |
| `kinds` | `{}` | machine name → kind, overrides the module's guess |

Kinds and their group: `node`, `server` → Servers; `nas` → Storage;
`router`, `switch`, `ap` → Network; `pc` → Computers; anything else →
Other.

Without `physical`, a module adds nothing to the Physical family.

## The settings file

Written by the Settings page (`#settings`), atomically, when
`settings_file` is set:

```json
{
  "places": {"Rack": ["pve1", "core"]},
  "kinds": {"nas": "nas"},
  "disabled": ["uptime-kuma"]
}
```

| Key | |
|---|---|
| `places` | once saved, **replaces** the modules' `places` |
| `kinds` | wins over the modules' `kinds`; machine name → `node`, `server`, `nas`, `router`, `switch`, `ap` or `pc` |
| `disabled` | module names no longer read |

You can edit it by hand: stop Cairn Map, edit, start it again. To go back
to what the config says, delete the file and restart.

## Module output

What a `url`, `command` or Python module returns:

```json
{
  "nodes":  [{"id": "host:web", "family": "hypervisor", "parent": "host:pve1", "name": "WEB", "kind": "lxc",
              "aliases": ["web", "10.0.10.21"], "attrs": {"ip": "10.0.10.21", "vcpu": 2}}],
  "status": [{"id": "10.0.10.21", "level": "warn", "detail": "Backup · 3 days old"}],
  "panels": [{"id": "host:web", "type": "link", "title": "Edit in Cairn IaC", "url": "https://iac.example/#web"}]
}
```

**nodes**

| Key | |
|---|---|
| `id` | required; two modules with the same `id` describe the same element |
| `family` | `physical`, `network`, `hypervisor`, `services`, `storage`. None: the node only enriches the element its `id` or an alias names |
| `parent` | a node of the same family; none: a top element |
| `name` | none: the name of the same element elsewhere, else its first alias |
| `kind` | free (`lxc`, `switch`…) |
| `slug` | the element's part of the address (`#network/vlan10/core`) |
| `aliases` | names, IPs, MACs that other sources may use for it |
| `attrs` | free; `ip`, `mac`, `vcpu`, `memory_mib`, `disk_gb`, `roles`… get a label, a `<key>_total` twin shows "used / total", `order` sorts siblings, `location` is the place |

**status**: `id` (or an alias), `level` (`ok`, `unknown`, `warn`, `down`),
`detail` in English, parts separated by ` · ` (the page translates the
parts it knows). The worst level under an element colours it.

**panels**: `id`, `type` and, by type:

| `type` | Keys |
|---|---|
| `link` | `title`, `url` |
| `value` | `title`, `value`, `unit`, or `time` (unix time, shown as an age) |
| `table` | `title`, `columns`, `rows` |
| `series` | `title`, `unit`, `max`, `start`, `step`, `lines: [{"name", "values": [...]}]` (`null` = gap) |

Units `%`, `B/s` and `B` are scaled for reading. Every status, panel and
family-less node may carry `aliases` too.

## Recipes

**Smallest useful config**: one module from a saved file, on this machine
only.

```json
{"modules": [{"name": "iac", "module": "cairn_iac", "options": {"file": "iac-export.json"}}]}
```

**Behind Authelia (or any authenticating proxy)**: listen on the network,
answer only the proxy, and keep the map to one group.

```json
{"listen": "0.0.0.0:8095", "trusted_proxies": ["10.0.10.5"], "require_groups": ["admins"]}
```

**Several Proxmox nodes**: list one URL per node, so one node down does not
blind the module.

```json
{"name": "proxmox", "module": "proxmox", "interval": 30,
 "options": {"url": ["https://pve1:8006/api2/json/cluster/resources", "https://pve2:8006/api2/json/cluster/resources"],
             "token_id": "map@pve!map", "token_file": "pve-token", "ca_file": "ca.crt", "expect_stopped": ["test-vm"]}}
```

**A state from a script of yours**: no Python module needed, any command
printing the format works; the host name or IP is enough as an `id`.

```json
{"name": "disks", "type": "command", "command": ["/usr/local/bin/disk-state"], "interval": 300}
```

**OpenTelemetry instead of node_exporter**: change the label and the
queries.

```json
{"name": "prometheus", "module": "prometheus",
 "options": {"prometheus": "http://prom:9090", "by": "host_name", "selector": "job=\"otel\"",
             "series": [{"title": "CPU", "unit": "%", "max": 100,
                         "query": "100 * (1 - sum by ($by) (rate(system_cpu_time_seconds_total{state=\"idle\",$sel}[5m])) / sum by ($by) (rate(system_cpu_time_seconds_total{$sel}[5m])))"}]}}
```

**Try a change without touching the live map**: copy the config, point the
modules at `file` copies of their sources, and run `--json`.
