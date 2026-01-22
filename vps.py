#!/usr/bin/env python3
import os
import subprocess
import shutil
import sys
import time
import threading

# ===========================
# CONFIGURATION
# ===========================
VM_NAME = "debian12-idx"
# YOUR REQUESTED SPECS:
VM_RAM = "14336"      # 14GB (Very High Risk of Freezing)
VM_CORES = "5"        # 5 Cores
DISK_SIZE = "10G"     # 10GB Disk
OS_URL = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"

# PORTS (Using new ones to avoid conflicts)
WEB_PORT = 6082
VNC_PORT = 5902
VNC_DISPLAY = ":2"
CPU_LIMIT = 70        # Limit CPU to stop bans

# ===========================
# 1. SETUP TOOLS (NIX)
# ===========================
def install_tools():
    print("📦 1. INSTALLING TOOLS...")
    packages = [
        "nixpkgs.tigervnc", "nixpkgs.websockify", "nixpkgs.fluxbox",
        "nixpkgs.xterm", "nixpkgs.qemu", "nixpkgs.cpulimit",
        "nixpkgs.cloud-utils", "nixpkgs.cdrkit", "nixpkgs.wget", "nixpkgs.openssl"
    ]
    os.system(f"nix-env -iA {' '.join(packages)} >/dev/null 2>&1")
    
    if not os.path.exists("./novnc"):
        print("   ⬇️  Downloading NoVNC...")
        os.system("git clone --depth 1 https://github.com/novnc/noVNC.git novnc >/dev/null 2>&1")
        os.system("git clone --depth 1 https://github.com/novnc/websockify novnc/utils/websockify >/dev/null 2>&1")

# ===========================
# 2. DISK PREP (10GB)
# ===========================
def prepare_vm():
    print(f"🛠️  2. SETTING UP VM ({DISK_SIZE})...")
    vm_dir = os.path.expanduser("~/vms")
    os.makedirs(vm_dir, exist_ok=True)
    
    img_file = f"{vm_dir}/{VM_NAME}.img"
    seed_file = f"{vm_dir}/{VM_NAME}-seed.iso"
    
    if not os.path.exists(img_file):
        print("   ⬇️  Downloading Debian 12...")
        subprocess.run(["wget", "-q", "--show-progress", "-O", img_file + ".tmp", OS_URL])
        os.rename(img_file + ".tmp", img_file)
        
        # RESIZE TO 10GB
        print(f"   💾 Resizing to {DISK_SIZE}...")
        os.system(f"qemu-img resize -f qcow2 {img_file} {DISK_SIZE}")
    else:
        # Enforce 10GB if file exists
        os.system(f"qemu-img resize -f qcow2 {img_file} {DISK_SIZE}")

    # Cloud Init (User: user / Pass: password)
    if not os.path.exists(seed_file):
        print("   🔑 Generating Config...")
        user_data = f"""#cloud-config
hostname: {VM_NAME}
ssh_pwauth: true
users:
  - name: user
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    passwd: $6$rounds=4096$randomsalt$6q6B.L1d.t/j..5/5..5/5..5/5..5/5..5/5..5/5..5/5..5/5..5/5..5/5..5/5..5/5..5/5..5/5..5
chpasswd:
  list: |
    root:password
    user:password
  expire: false
"""
        meta_data = f"instance-id: {VM_NAME}\nlocal-hostname: {VM_NAME}\n"
        with open("user-data", "w") as f: f.write(user_data)
        with open("meta-data", "w") as f: f.write(meta_data)
        os.system(f"cloud-localds {seed_file} user-data meta-data >/dev/null 2>&1")
        os.remove("user-data")
        os.remove("meta-data")

    return img_file, seed_file

# ===========================
# 3. START SERVICES
# ===========================
def start_system(img, seed):
    print(f"\n🚀 3. STARTING SYSTEM (Port {WEB_PORT})...")
    
    # Cleanup old processes
    os.system("killall -9 Xvnc websockify fluxbox qemu-system-x86_64 >/dev/null 2>&1")
    os.system(f"rm -rf /tmp/.X*-lock /tmp/.X11-unix")
    
    # Start VNC
    print("   ► VNC Display...")
    os.system(f"Xvnc {VNC_DISPLAY} -geometry 1280x720 -depth 16 -rfbport {VNC_PORT} -localhost yes -SecurityTypes None >/dev/null 2>&1 &")
    time.sleep(2)
    
    # Start Fluxbox
    os.system(f"export DISPLAY={VNC_DISPLAY}; fluxbox >/dev/null 2>&1 &")
    
    # Start Web Bridge
    print("   ► Web Bridge...")
    os.system(f"./novnc/utils/novnc_proxy --vnc localhost:{VNC_PORT} --listen {WEB_PORT} >/dev/null 2>&1 &")
    
    # Start VM
    print(f"   ► Booting VM ({VM_RAM}MB RAM, {VM_CORES} Cores)...")
    qemu_cmd = (
        f"export DISPLAY={VNC_DISPLAY}; "
        f"qemu-system-x86_64 -enable-kvm -m {VM_RAM} -smp {VM_CORES} -cpu host "
        f"-drive file={img},format=qcow2,if=virtio "
        f"-drive file={seed},format=raw,if=virtio "
        f"-netdev user,id=n1 -device virtio-net-pci,netdev=n1 "
        f"-vga virtio -display gtk,gl=off "
        f">/dev/null 2>&1 &"
    )
    os.system(qemu_cmd)

# ===========================
# 4. ANTI-BAN GUARD
# ===========================
def ban_guard():
    print(f"🛡️  4. GUARD ACTIVE (Limit: {CPU_LIMIT}%)...")
    while True:
        try:
            pids = subprocess.getoutput("pgrep -f qemu-system-x86_64").split()
            for pid in pids:
                os.system(f"cpulimit -p {pid} -l {CPU_LIMIT} -b >/dev/null 2>&1")
        except: pass
        time.sleep(5)

try:
    install_tools()
    img, seed = prepare_vm()
    start_system(img, seed)
    
    print("\n" + "="*60)
    print(f"✅ VM STARTED (14GB RAM / 10GB Disk)")
    print("-" * 60)
    print(f"👉 Open Port {WEB_PORT} (6082) in the PORTS tab.")
    print("👉 Add '/vnc.html' to the URL.")
    print("="*60 + "\n")
    
    ban_guard()

except KeyboardInterrupt:
    print("\nStopped.")
