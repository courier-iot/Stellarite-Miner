# Windows installer

`StellariteNode-Setup-<version>.exe` installs the Pulsarite and Nebulite full nodes on Windows 10/11 (64-bit), with their own Python inside, so the computer needs nothing else installed. It uses the Neon Pulsar look of the apps.

## What it installs

- **Start menu → Stellarite Node:** *Start both nodes*, each node on its own, the two web maps, and a *Command deck* prompt with `plsr-wallet`, `nblt-wallet`, `plsr-miner` and `nblt-miner`.
- **Options:** a desktop shortcut, start both nodes at sign-in, and (when installed for all users) a Windows Firewall rule for ports 5000–5001 on private networks. Installed just for you, Windows asks to allow Python the first time a node starts: allow it on **private networks**.
- **Chains** live in `%APPDATA%\Stellarite Node\pulsarite` and `…\nebulite`. Updating or uninstalling never touches them. After a consensus change, delete the coin's folder there to start its chain over.
- Pulsarite is started with `NEBULITE_URL=http://127.0.0.1:5001`, so local Nebulite escape missions scout its survey stars, as in the Docker setup. To turn that off, set `NEBULITE_URL` to an empty value in your Windows environment variables.

Each node window shows the `NODE_URI` for the phone, e.g. `http://192.168.40.10:5000`, or tap **[FIND NODE]** in the app.

## Building it

**On GitHub:** the *Windows node installer* workflow builds it on every push (download `stellarite-node-windows` from the run). Tag a release (`v12.1.0`) and the `.exe` is attached next to the APK.

**On a Windows PC:** install Python 3.12 and Inno Setup 6 (`winget install JRSoftware.InnoSetup`), then from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

The output is `build\StellariteNode-Setup-<version>.exe`, with the version taken from the top of CHANGELOG.md. The script downloads python.org's embeddable Python, installs both `requirements.txt` files into it as Windows wheels, copies `node/` and `nebulite/` (without `data/`, tests or caches), checks that both nodes start with the bundled Python, then compiles `stellarite-node.iss`.

## Files

| File | Purpose |
|---|---|
| `stellarite-node.iss` | Inno Setup script: pages, shortcuts, firewall rule, Neon Pulsar colours |
| `launcher.py` | What the shortcuts run: themed console, AppData chain folders, starts `node.py` |
| `stellarite-shell.cmd` | The Command deck prompt |
| `build.ps1` | Stages Python and the nodes, then compiles the installer |
| `make_art.py` | Draws `art/` (wizard banners and icon); rerun only to change the artwork |

Add `build/` to `.gitignore`.

## Notes

- The installer isn't code-signed, so SmartScreen shows "Windows protected your PC" the first time: **More info → Run anyway**. Signing it needs a code-signing certificate (`SignTool=` in the `.iss`).
- Inno Setup colours the pages, text and lists; Windows still draws the buttons and checkboxes in its own style.
