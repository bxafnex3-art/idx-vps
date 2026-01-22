#!/usr/bin/env python3
import os, subprocess, time

# ===========================
# CONFIG
# ===========================
VM_NAME = "debian12-idx"
VM_RAM = "8192"
VM_CORES = "4"
DISK_SIZE = "30G"
OS_URL = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"

WEB_PORT = 6080
VNC_PORT = 5901
VNC_DISPLAY = ":1"

BASE = os.path.expanduser("~/idxvm")
IMG = f"{BASE}/{VM_NAME}.qcow2"
SEED = f"{BASE}/{VM_NAME}-seed.iso"

def sh(cmd):
    subprocess.run(cmd, shell=True)

# ===========================
# INSTALL TOOLS (NIX)
# ===========================
def install_tools():
    print("📦 Installing required tools with Nix...")
    pkgs = [
        "nixpkgs.qemu",
        "nixpkgs.tigervnc",
        "nixpkgs.fluxbox",
        "nixpkgs.cloud-utils",
        "nixpkgs.wget",
        "nixpkgs.git"
    ]
    sh(f"nix-env -iA {' '.join(pkgs)}")

    if not os.path.exists("novnc"):
        print("⬇️  Cloning noVNC...")
        sh("git clone --depth 1 https://github.com/novnc/noVNC.git novnc")
        sh("git clone --depth 1 https://github.com/novnc/websockify novnc/utils/websockify")

# ===========================
# IMAGE SETUP
# ===========================
def setup_image():
    os.makedirs(BASE, exist_ok=True)

    if not os.path.exists(IMG):
        print("⬇️  Downloading Debian image...")
        sh(f"wget -O {IMG}.tmp {OS_URL}")
        os.rename(f"{IMG}.tmp", IMG)
        sh(f"qemu-img resize {IMG} {DISK_SIZE}")

    if not os.path.exists(SEED):
        print("🔑 Creating cloud-init seed...")
        with open("user-data", "w") as f:
            f.write(f"""#cloud-config
hostname: {VM_NAME}
ssh_pwauth: true
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
            f.write(f"instance-id: {VM_NAME}\nlocal-hostname: {VM_NAME}\n")

        sh(f"cloud-localds {SEED} user-data meta-data")
        os.remove("user-data")
        os.remove("meta-data")

# ===========================
# START SYSTEM
# ===========================
def start():
    print("🚀 Starting services...")

    sh("pkill -f Xvnc >/dev/null 2>&1")
    sh("pkill -f qemu-system-x86_64 >/dev/null 2>&1")
    sh("pkill -f novnc_proxy >/dev/null 2>&1")

    print("► VNC display")
    sh(f"Xvnc {VNC_DISPLAY} -geometry 1280x720 -depth 16 "
       f"-rfbport {VNC_PORT} -localhost yes -SecurityTypes None >/dev/null 2>&1 &")
    time.sleep(2)

    print("► Fluxbox")
    sh(f"export DISPLAY={VNC_DISPLAY}; fluxbox >/dev/null 2>&1 &")

    print("► noVNC")
    sh(f"./novnc/utils/novnc_proxy --vnc localhost:{VNC_PORT} "
       f"--listen {WEB_PORT} >/dev/null 2>&1 &")

    print("► QEMU (KVM)")
    sh(
        f"export DISPLAY={VNC_DISPLAY}; "
        f"qemu-system-x86_64 "
        f"-enable-kvm "
        f"-m {VM_RAM} "
        f"-smp {VM_CORES} "
        f"-cpu host "
        f"-drive file={IMG},format=qcow2,if=virtio "
        f"-drive file={SEED},format=raw,if=virtio "
        f"-netdev user,id=n1,hostfwd=tcp::2222-:22 "
        f"-device virtio-net-pci,netdev=n1 "
        f"-vga virtio -display gtk,gl=off "
        f">/dev/null 2>&1 &"
    )

    print("\n" + "="*60)
    print("✅ DEBIAN 12 VM READY")
    print("="*60)
    print(f"Open PORT {WEB_PORT} → add /vnc.html")
    print("Login:")
    print("  user / password")
    print("="*60)

# ===========================
# MAIN
# ===========================
install_tools()
setup_image()
start()

print("\nKeep this terminal open.")
while True:
    time.sleep(60)
