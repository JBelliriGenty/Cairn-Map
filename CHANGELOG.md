# Changelog

## 1.5.0 (2026-11-10)

- Proxmox module, option `macs`: each guest's network MACs (from its config,
  re-read every `macs_every` seconds) become aliases. The device the switches
  see under that MAC is linked to the guest and, when Cairn Net has no name
  for it, takes the guest's name instead of its MAC.
- An alias brought by a module without elements of its own now links
  elements across families, like the others.

## 1.4.0 (2026-11-10)

- Cairn IaC module: a machine's description (Cairn IaC 1.7.0: its Tofu
  `description` or inventory `description` host variable) becomes the
  attribute `description`, shown at the top of its sheet and searched by
  the palette.

## 1.3.3 (2026-11-08)

- Map: the current or hovered element's name sits on an opaque pill, so it
  reads even when it has to cross a dense cluster of points.

## 1.3.2 (2026-11-08)

- Config: a key nothing reads, at the top of the config or in a module entry
  (a typo such as `intervall`), is reported at start on standard error, with
  the closest known key ("did you mean 'interval'?"). The map still starts.
  Module options are not checked: each module reads its own.
- Configuration reference: `docs/configuration.md`, every key with its
  default, the settings file, the module format and recipes.

## 1.3.1 (2026-11-08)

- Map: a name is no longer cut by the edge of the map (a place outside it is
  not free). The current element's name, always shown, takes the place that
  covers the fewest other names and points, inside the map first. Checked on
  a copy of a 275-element map, 375 to 1440 px wide: no name over another, none
  cut by the edge at the family's view.

## 1.3.0 (2026-11-08)

- Map: a name never covers another point either (it already never covered
  another name). It tries right, left, below, above its point, else waits for
  the hover or a closer zoom; checked on the example from 320 to 1440 px wide.
- English: the guest kinds read `VM` and `LXC` (they read `vm` and `lxc`).

## 1.2.2 (2026-11-08)

- Docker image published on each release: `ghcr.io/jbellirigenty/cairn-map`
  (Alpine, amd64 and arm64, runs as `nobody`), tags `1.2.2`, `1.2`, `1`, `latest`.
- GitHub releases created from the tag, with their CHANGELOG notes.

## 1.2.1 (2026-11-08)

- Its own icon (sky blue, the cairn with three linked points of the map):
  `icon.svg`, and the 64 px PNG in the page (tab, `/favicon.ico`, sidebar).

## 1.2.0 (2026-11-08)

- **Settings page** (`#settings`, key `s`): each machine's room or rack and
  kind, the modules on or off, saved for everyone in `settings_file`
  (`POST /api/settings`: same-origin JSON only, checked, written atomically)
  and applied at once. Saved rooms replace the modules' `places`; a saved
  kind moves the machine to its group (a group left empty goes); a module
  switched off is no longer read. Without `settings_file` the page is read
  only and nothing is written.
- `/api/map` carries the settings (`settings`) and each module's `on`.

## 1.1.0 (2026-11-08)

- **Physical by kind or by place**: once a place is declared, a switch on
  the family's page groups the machines by room or rack instead of by kind
  (`/api/map?places=1`, "No place" for the others), remembered by the
  browser. The place is no longer a level above the kinds; it is the
  machine's `location` attribute.
- **Network**: `cairn_net` option `uplink` adds the way out (Internet) first
  under the router, through a device (the ISP box), ok while its port runs;
  its aliases catch an external monitor.
- **Storage**: `cairn_nas` reads the SMB shares Cairn NAS 0.2.1 adds to
  `/api/slow`; a dataset shared over SMB is a `share`, with its share names
  and users.
- **Map**: names no longer overlap in a dense cluster. Each name tries the
  right of its point, then the left, below, above; one that finds no room
  waits for the hover or a closer zoom (the hovered, current and their
  neighbours always show, the upper levels and the failing ones first).

## 1.0.0 (2026-11-07)

The five families are filled; end of the first roadmap.

- **Physical**: site → room or rack (optional `places`) → kind → machine,
  from `cairn_iac` (bare metal) and `cairn_net` (switches, access points,
  NAS), through the `physical` option and `ctx.physical(...)` for other
  modules. The same machine links to its Network and Hypervisor twins, and
  their states and curves show on it.
- **Services**: new module `traefik` (proxy → service → server) from
  Traefik's API, routers and services only. Services carry their domains as
  aliases, so Uptime Kuma monitors of web services now attach to them.
- **Storage**: new module `cairn_nas` (machine → pool → dataset or NFS
  share) from Cairn NAS's `/api/slow`; pool states from health and capacity.
- **Search**: `/` or `Ctrl K` opens a palette (name, IP, aliases, kind,
  path; arrows and Enter). **Keyboard shortcuts**: `0`–`5`, `t`, `u`, `m`,
  `Esc`, `?` (help).
- State details are written in English by the modules and translated by
  the page (they stayed in the config's language before); the families'
  names and the attributes have English labels.
- A nameless node takes the name of the same element in another family.
- "Also in" names the parent when the same machine shows several times in a
  family (one server behind many services).
- `ctx.get_text` for modules that read text.

## 0.5.0 (2026-11-07)

- Dashboard. New module `prometheus`: curves over the last 24 h per element
  (CPU, memory, disk, network by default, from node_exporter; every query,
  selector and label is an option, so OpenTelemetry's hostmetrics work too),
  the last backup (any query giving a unix time, e.g. pbs-exporter) with a
  state when too old, a Grafana link per element.
- New panel type `series` (lines of values at a fixed step), drawn as an
  inline SVG curve on the element's page: last value, maximum, average,
  the value under the pointer; light and dark, English and French.
- `GET /api/panels/<id>`: a series' points, fetched when the page opens;
  `/api/map` carries each line's last value only.
- Map: zoomed in on an element, its percentages ring the point and its last
  values hang under its name.
- `value` panels may carry a `time`, shown as an age in the page's language.

## 0.4.0 (2026-11-07)

- Map view redrawn as neurons (replaces the boxes of 0.3.0): a glowing point
  per family on a dark sky (soft sky in the light theme), curved links,
  impulses running down them (red towards a failing element), beating rings
  on states to watch or down.
- Semantic zoom: families and their roots at first, each next level grows
  out of its parent with the zoom. A click flies to the element, grows its
  next two levels and opens its details; the address follows.
- Links between families (the same machine seen twice) show only for the
  hovered or current element.
- Stable layout: families on a ring, each family's branches in its own
  region, seeded by the ids.

## 0.3.0 (2026-11-07)

- Map view: the same tree on one canvas with semantic zoom (wheel, pinch,
  double-click or double-tap bring the next level in), drag to move, zoom
  buttons and keys, state dots at every level, a click opens the element's
  details beside the map (below it on a phone).
- Tiles / Map switch on every page, remembered in the browser; addresses
  unchanged. The current element and its children keep their place through
  a view transition (none under `prefers-reduced-motion`).
- Self-check covers the page: no outside resource, every literal string has
  its French.

## 0.2.0 (2026-11-07)

- Live state. New modules `proxmox` (nodes and guests running or stopped,
  CPU, memory, uptime; read-only API token) and `uptime_kuma` (monitors'
  state, uptime 24 h / 30 d, response time, from Prometheus; one table per
  element). `cairn_net` gives port, device and switch states from Cairn Net
  0.5's live interfaces and health; a switch it cannot reach shows, down.
- Status, panels and family-less nodes may carry `aliases`: they attach to
  every element named by their id or an alias, once.
- Page: dots roll up to every family and the overview (side menu included),
  a tally per family (down, to watch, ok), the element's states listed on its
  page, tables of the same title merged, sources of states shown.
- URL modules: `auth` (the `Authorization` scheme, default `Bearer `) and a
  list of URLs tried in order; Python modules get `ctx.lang`.
- README: how to write your own module (URL, command, Python), with an
  example.

## 0.1.0 (2026-11-07)

- Map tree from modules: common JSON format (`nodes`, `status`, `panels`),
  merge by id, aliases for sources that do not know the ids, the same
  element across families linked.
- Module types: Python file (`modules/`), URL (bearer token file, CA
  bundle), command. A failing module keeps its last good data and is named
  in a banner.
- Shipped modules `cairn_iac` (Hypervisor family) and `cairn_net` (Network
  family).
- Page: overview of the families, nested tiles, breadcrumb, one address per
  level, Modules page, English and French, light and dark.
