# musi remote API — Cloudflare Tunnel setup

One-time setup (~20 min) that exposes the device API at
`https://api.<domain>` so the musi website can manage the library from
anywhere. No port forwarding; the Pi dials out to Cloudflare.

## Prerequisites

- A domain added to a **free Cloudflare account** (nameservers switched to
  Cloudflare and the zone shows *Active*).

  Free-domain route (eu.org), in this order:
  1. Add `<name>.eu.org` to Cloudflare first (Add a domain → Free). The
     pending zone gets two assigned Cloudflare nameservers — note them.
  2. Register at https://nic.eu.org, request the same domain, and enter
     those two Cloudflare nameservers in the request's NS section.
  3. Wait for eu.org's manual approval (days to weeks). When it lands,
     the Cloudflare zone flips to Active ("Check nameservers" nudges it).

  NOTE: `musiweb.base44.app` can NOT be used — it's base44's domain; the
  zone would wait forever on a nameserver change only base44 could make.
- The Pi online, running Device API pack 3 or later. That update installs
  `cloudflared` automatically; check with:

  ```sh
  cloudflared --version
  ```

  If it's missing (e.g. the OTA ran offline), install it manually — the
  version must match `CLOUDFLARED_VERSION` in `update.sh`, and it MUST be
  the generic `linux-arm` build (armhf/ARMv7 builds crash with "illegal
  instruction" on the Zero W's ARMv6):

  ```sh
  VER=$(sed -n 's/^CLOUDFLARED_VERSION="\(.*\)"$/\1/p' ~/musi/update.sh)
  curl -fsSL -o /tmp/cloudflared \
    "https://github.com/cloudflare/cloudflared/releases/download/$VER/cloudflared-linux-arm"
  sudo install -m 0755 /tmp/cloudflared /usr/local/bin/cloudflared
  ```

All commands below run on the Pi over SSH as the normal user.

## Option A — dashboard flow (simpler, remote-managed)

Cloudflare Zero Trust → Networks → Tunnels → Create a tunnel (cloudflared).

1. **Environment**: Debian → architecture **arm32** ("32-bit" is x86 — wrong).
2. **Connector install**: the shown command dpkg-installs the *latest*
   `cloudflared-linux-arm.deb`. If `/usr/local/bin/cloudflared` already
   exists (our pinned install), skip the download and run only:

   ```sh
   sudo cloudflared service install <TOKEN-from-the-dashboard-command>
   ```

   If a fresh dpkg install crashes with "illegal instruction", remove it
   and use the pinned binary the same way.
3. **Public hostname**: `api.<domain>` → service `HTTP` → `localhost:8080`.
   Path scoping is optional here — the app already 404s the tokenless
   legacy routes for any request carrying Cloudflare headers.
4. Jump to step 5 below ("Test") and then step 7 (website env).

## Option B — CLI flow (locally-managed, config in the repo)

## 1. Authorize cloudflared

```sh
cloudflared tunnel login
```

It prints a URL — open it on your PC, log in to Cloudflare, pick the
domain. This drops a certificate at `~/.cloudflared/cert.pem`.

## 2. Create the named tunnel

```sh
cloudflared tunnel create musi
```

Note the tunnel UUID it prints; credentials land in
`~/.cloudflared/<UUID>.json`.

## 3. Route DNS

```sh
cloudflared tunnel route dns musi api.<domain>
```

This creates the `api.<domain>` CNAME in Cloudflare DNS.

## 4. Config

```sh
sudo mkdir -p /etc/cloudflared
sudo cp ~/musi/pi/cloudflared-config.yml /etc/cloudflared/config.yml
sudo nano /etc/cloudflared/config.yml   # fill in <TUNNEL_ID>, <USER>, <DOMAIN>
```

The ingress in that file only forwards `/api/*`. The legacy tokenless
upload page stays LAN-only — keep it that way.

## 5. Test run

```sh
cloudflared tunnel run musi
```

From a phone on mobile data (NOT the home WiFi):

```sh
curl -H "Authorization: Bearer <token>" https://api.<domain>/api/v1/status
```

(token: Settings → API on the device). Also confirm the lockdown:

- `https://api.<domain>/` → 404 (legacy page not exposed)
- `/api/v1/status` without the token → 401

Ctrl-C when happy.

## 6. Install as a service

```sh
sudo cloudflared --config /etc/cloudflared/config.yml service install
sudo systemctl enable --now cloudflared
```

The service runs as root and reads the credentials file path from the
config, so the `/home/<user>/.cloudflared/...` path is fine.

## 7. Point the website at it

On the website (Vercel) side:

- API base URL: `https://api.<domain>`
- Token: entered by the user, from Settings → API on the device.
- Add the site's origin to the device CORS allowlist:

  ```sh
  echo "https://<site-domain>" >> ~/.local/share/musi/api-origins
  systemctl --user restart musi-api    # origins are read at startup
  ```

  (The default allowlist already contains https://musiweb.base44.app.)

## Notes / gotchas

- Battery device: the API is only reachable while the musi is ON and on
  WiFi. The website should treat timeouts as "device is off", not errors.
- Storage lock ON ⇒ all write endpoints return 423 by design.
- Version bumps: change `CLOUDFLARED_VERSION` in `update.sh` (new root
  step or re-run of step 3 logic), test on-device before trusting it —
  ARMv6 support is the fragile part.
- cloudflared idles at ~30–60 MB RAM — noticeable on the 512 MB Zero W,
  acceptable. If it ever fights the player for memory, stop the service
  and use the API on the LAN only (`http://musi.local:8080`).
