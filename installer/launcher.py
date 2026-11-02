"""Starts a Stellarite node from the Windows install, in the Neon Pulsar look.

    python launcher.py pulsarite     Pulsarite node (port 5000)
    python launcher.py nebulite      Nebulite node (port 5001)
    python launcher.py all           both, each in its own window
    python launcher.py script <file> runs wallet.py, miner.py etc. from its own folder

Chains are kept in %APPDATA%\\Stellarite Node\\<coin>, so they survive
upgrades and uninstalls. Any extra arguments are passed to node.py
(for example --peer or --public-url).
"""
import ctypes
import os
import runpy
import socket
import subprocess
import sys

APP = os.path.dirname(os.path.abspath(__file__))
COINS = {
    "pulsarite": {"dir": "node", "ticker": "PLSR", "port": 5000},
    "nebulite": {"dir": "nebulite", "ticker": "NBLT", "port": 5001},
}

CRIMSON = "\x1b[38;2;220;20;60m"
AMBER = "\x1b[38;2;255;176;0m"
GREY = "\x1b[38;2;150;150;150m"
RESET = "\x1b[0m"


def data_dir(coin):
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(root, "Stellarite Node", coin)
    os.makedirs(path, exist_ok=True)
    return path


def lan_ip():
    """The address phones on the same Wi-Fi should use."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def banner(coin):
    info = COINS[coin]
    os.system("")  # turns on colour codes in the Windows console
    try:
        ctypes.windll.kernel32.SetConsoleTitleW(f"STELLARITE NODE // {info['ticker']}")
    except (AttributeError, OSError):
        pass
    title = f"STELLARITE NODE  //  {coin.upper()} ({info['ticker']})"
    print(f"{CRIMSON}┌─{RESET}" + " " * (len(title) + 4) + f"{CRIMSON}─┐{RESET}")
    print(f"   {AMBER}◉{RESET} {CRIMSON}{title}{RESET}")
    print(f"{CRIMSON}└─{RESET}" + " " * (len(title) + 4) + f"{CRIMSON}─┘{RESET}")
    print(f"{GREY}  CHAIN DATA  {RESET}{data_dir(coin)}")
    print(f"{GREY}  NODE_URI    {RESET}{AMBER}http://{lan_ip()}:{info['port']}{RESET}"
          f"{GREY}   (same Wi-Fi as the phone){RESET}")
    print(f"{GREY}  WEB MAP     {RESET}http://localhost:{info['port']}/map")
    print(f"{GREY}  Close this window or press Ctrl+C to stop the node.{RESET}\n")


def run_node(coin, extra):
    info = COINS[coin]
    coin_dir = os.path.join(APP, info["dir"])
    banner(coin)
    if coin == "pulsarite":
        # Lets Nebulite escape missions scout Pulsarite's survey stars,
        # as the Docker setup does. Harmless if Nebulite isn't running.
        if os.path.isdir(os.path.join(APP, "nebulite")):
            os.environ.setdefault("NEBULITE_URL", "http://127.0.0.1:5001")
    os.chdir(coin_dir)
    sys.path.insert(0, coin_dir)
    args = list(extra)
    if "--data" not in args:
        args += ["--data", data_dir(coin)]
    sys.argv = [os.path.join(coin_dir, "node.py")] + args
    try:
        runpy.run_path(sys.argv[0], run_name="__main__")
    except KeyboardInterrupt:
        print(f"\n{CRIMSON}  NODE STOPPED{RESET}")
    except Exception as exc:  # keep the window open so the error can be read
        print(f"\n{CRIMSON}  NODE FAILED: {exc!r}{RESET}")
        input("  Press Enter to close.")
        raise SystemExit(1)


def run_all(extra):
    # Started from pythonw (no window); each node gets a console via python.exe.
    python = os.path.join(os.path.dirname(sys.executable), "python.exe")
    if not os.path.exists(python):
        python = sys.executable
    order = [c for c in ("nebulite", "pulsarite") if os.path.isdir(os.path.join(APP, COINS[c]["dir"]))]
    for coin in order:
        subprocess.Popen([python, os.path.abspath(__file__), coin] + list(extra),
                         creationflags=subprocess.CREATE_NEW_CONSOLE)


def run_script(path, extra):
    """Runs wallet.py, miner.py or any coin script as if from its own folder.

    The embedded Python doesn't put a script's folder on sys.path, so the
    coin's own modules (config, chain, ...) are added here.
    """
    path = os.path.abspath(path)
    sys.path.insert(0, os.path.dirname(path))
    sys.argv = [path] + list(extra)
    runpy.run_path(path, run_name="__main__")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "script":
        run_script(sys.argv[2], sys.argv[3:])
        return
    if len(sys.argv) < 2 or sys.argv[1] not in (*COINS, "all"):
        print(__doc__)
        input("Press Enter to close.")
        return
    coin, extra = sys.argv[1], sys.argv[2:]
    if coin == "all":
        run_all(extra)
    else:
        run_node(coin, extra)


if __name__ == "__main__":
    main()
