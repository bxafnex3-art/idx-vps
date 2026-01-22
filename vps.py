#!/usr/bin/env bash
set -e
export NIX_CONFIG="download-buffer-size = 50000000"

# Ensure python
if [ ! -x "$HOME/.nix-profile/bin/python3" ]; then
  echo "🐍 python3 not found, installing..."
  nix-env -iA nixpkgs.python3
fi

$HOME/.nix-profile/bin/python3 - << 'PYCODE'
import os, subprocess, time, threading

VM_NAME = "debian12-idx"
VM_RAM = "8192"
VM_CORES = "4"
DISK_SIZE = "30G"
OS_URL = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"

WEB_PORT = 6080
VNC_PORT = 5901
VNC_DISPLAY = ":1"
USE_CLOUDFLARE = True

BASE = os.path.expanduser("~/idxvm")
IMG = f"{BASE}/{VM_NAME}.qcow2"
SEED = f"{BASE}/{VM_NAME}-seed.iso"

def sh(cmd):
    subprocess.run(cmd, shell=True)

def ensure_nix(pkgs):
    missing = []
    for p in pkgs:
        name = p.split(".")[-1]
        if subprocess.call(f"nix-env -q {name} >/dev/null 2>&1", shell=True) != 0:
            missing.append(p)
    if missing:
        print("📦 Installing:", " ".join(missing))
        sh(f"nix-env -iA {' '.join(missing)}")

ensure_nix([
    "nixpkgs.qemu",
    "nixpkgs.tigervnc",
    "nixpkgs.fluxbox",
    "nixpkgs.cloud-utils",
    "nixpkgs.wget",
    "nixpkgs.git",
    "nixpkgs.cloudflared"
])

if not os.path.exists("novnc"):
    sh("git clone --depth 1 https://github.com/novnc/noVNC.git novnc")
    sh("git clone --depth 1 https://github.com/novnc/websockify novnc/utils/websockify")

os.makedirs(BASE, exist_ok=True)

if not os.path.exists(IMG):
    sh(f"wget -O {IMG}.tmp {OS_URL}")
    os.rename(f"{IMG}.tmp", IMG)
    sh(f"qemu-img resize {IMG} {DISK_SIZE}")

if not os.path.exists(SEED):
    with open("user-data", "w") as f:
        f.write(f"""#cloud-config
hostname: {VM_NAME}
users:
  - name: user
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
chpasswd:
  list: |
    user:password
  expire: false
""")
    with open("meta-data", "w") as f:
        f.write(f"instance-id: {VM_NAME}\n")
    sh(f"cloud-localds {SEED} user-data meta-data")
    os.remove("user-data")
    os.remove("meta-data")

sh("pkill -f Xvnc >/dev/null 2>&1")
sh("pkill -f qemu-system-x86_64 >/dev/null 2>&1")
sh("pkill -f novnc_proxy >/dev/null 2>&1")
sh("pkill -f cloudflared >/dev/null 2>&1")

sh(f"Xvnc {VNC_DISPLAY} -geometry 1280x720 -depth 16 -rfbport {VNC_PORT} -localhost yes -SecurityTypes None &")
time.sleep(2)
sh(f"export DISPLAY={VNC_DISPLAY}; fluxbox &")
sh(f"./novnc/utils/novnc_proxy --vnc localhost:{VNC_PORT} --listen {WEB_PORT} &")

if USE_CLOUDFLARE:
    sh(f"cloudflared tunnel --url http://localhost:{WEB_PORT} --no-autoupdate >/tmp/cf.log 2>&1 &")
    time.sleep(3)
    sh("grep -o 'https://[a-z0-9.-]*trycloudflare.com' /tmp/cf.log | tail -1")

sh(
    f"export DISPLAY={VNC_DISPLAY}; "
    f"qemu-system-x86_64 -enable-kvm -m {VM_RAM} -smp {VM_CORES} -cpu host "
    f"-drive file={IMG},format=qcow2,if=virtio "
    f"-drive file={SEED},format=raw,if=virtio "
    f"-netdev user,id=n1,hostfwd=tcp::2222-:22 "
    f"-device virtio-net-pci,netdev=n1 "
    f"-vga virtio -display gtk,gl=off &"
)

print("VM ready. user/password")
while True:
    time.sleep(300)
PYCODE
