# Running your nodes in the cloud

A cloud server keeps both nodes online 24/7, so phones can mine from anywhere and friends can join the same network. This guide uses Docker, so the whole setup is a few commands.

What you end up with:

```
https://nodes.example.com/pulsarite   ← Pulsarite node
https://nodes.example.com/nebulite    ← Nebulite node
```

Put those addresses in the app's NODE_URI field.

## 1. Get a server

Any small Linux server (a "VPS") works: 1 CPU and 1 GB of RAM is plenty. Mainstream providers such as Hetzner, DigitalOcean, Linode/Akamai and Vultr have plans for a few dollars a month. Oracle Cloud's "Always Free" tier includes small VMs at no cost; check their current terms.

Pick **Ubuntu 24.04** (or any recent Linux) and note the server's public IP address.

> Avoid "free app hosting" services that sleep or wipe their disk. The node stores the blockchain on disk, and a wiped disk means a lost chain.

## 2. (Optional) Point a domain at it

A domain gives you free automatic HTTPS. Create an **A record** (e.g. `nodes.example.com`) pointing at the server's IP. Free subdomain services like DuckDNS work too.

No domain? Skip this; you'll use `http://<server-ip>/nebulite` instead.

## 3. Install Docker and start the nodes

SSH into the server, then:

```bash
curl -fsSL https://get.docker.com | sh          # installs Docker
git clone https://github.com/<you>/<your-repo>.git stellarite
cd stellarite/deploy
cp .env.example .env
nano .env                                        # set DOMAIN=nodes.example.com (or leave empty)
docker compose up -d --build
```

Open the firewall for web traffic if your provider has one (and on the server, if you use `ufw`):

```bash
sudo ufw allow 80 && sudo ufw allow 443
```

## 4. Check it works

From any browser:

- `https://nodes.example.com/nebulite/info`, which should show the Nebulite node's height
- `https://nodes.example.com/pulsarite/info`
- `https://nodes.example.com/pulsarite/map` and `https://nodes.example.com/nebulite/map`: the web maps, which you can share with anyone

The Pulsarite node is already connected to the Nebulite node (`NEBULITE_URL` in `docker-compose.yml`), so Nebulite escape missions automatically scout Pulsarite's survey stars. Running nodes by hand, start Pulsarite with `NEBULITE_URL=http://<nebulite node>:5001` (or `--nebulite`) to do the same.

## 5. Point the app at it

On the RIG tab, pick **NBLT** or **PLSR** and set NODE_URI to `https://nodes.example.com/nebulite` or `https://nodes.example.com/pulsarite`. Use the app's own wallet (**[NEW WALLET]**) for your address: you don't need, and shouldn't keep, a wallet file on the server.

If you mined in **solo mode** first, tap **[PUSH CHAIN]** to send your solo chain to the server. It's adopted if it's longer than what the server has (on a brand-new server, it always is).

## Everyday operations

| Task | Command (in `stellarite/deploy`) |
|---|---|
| See logs | `docker compose logs -f nebulite` |
| Update after pulling new code | `git pull && docker compose up -d --build` |
| Stop | `docker compose down` |
| Back up the chains | `docker run --rm -v deploy_nebulite-data:/d -v $PWD:/b alpine tar czf /b/nebulite-chain.tgz -C /d .` (same for `pulsarite-data`) |
| **Start a coin's chain over** (after a consensus change) | `docker compose down && docker volume rm deploy_nebulite-data && docker compose up -d` |

The chains live in Docker volumes, so they survive restarts and updates. Only the last command deletes them.

## Linking more nodes

To run a second node elsewhere that stays in sync, start it with the first as a peer:

```bash
PEERS=https://nodes.example.com/nebulite python node.py --public-url https://second.example.com/nebulite
```

or set `PEERS` and `PUBLIC_URL` in the `environment:` section of `docker-compose.yml`.

## Security notes

- Anyone who knows the address can mine and send transactions. That's what a public coin is, but it also means anyone can send requests. Caddy limits request size; for a busier network, add rate limiting (a Caddy plugin, or Cloudflare in front).
- Nodes don't need private keys. Keep wallets on phones or your own computer.
- These are learning coins with no real-world value; don't present them as investments.
