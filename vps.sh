import os
import subprocess
import shutil
import sys
import time
import threading

# ===========================
# CONFIGURATION
# ===========================
# USER SETTINGS
VM_NAME = "debian12-worker"
VM_RAM = "15360"  # 15GB in MB
VM_CORES = "6"
DISK_SIZE = "30G" # Disk size
OS_URL = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"

# SYSTEM SETTINGS
WEB_PORT = 6080
VNC_PORT = 5900
VNC_DISPLAY = ":0"
CPU_LIMIT = 70    # 70% Limit (Safe zone)

# ===========================
# 1. NIX ENVIRONMENT SETUP
# ===========================
def install_tools():
    print("📦 1. SETTING UP ENVIRONMENT (NIX)...")
    
    # We need cloud-utils for cloud-localds to make the seed image
    packages = [
        "nixpkgs.tigervnc",
        "nixpkgs.websockify",
        "nixpkgs.fluxbox",
        "nixpkgs.xterm",
        "nixpkgs.cpulimit",
        "nixpkgs.qemu",
        "nixpkgs.cloud-utils", # For cloud-localds
        "nixpkgs.cdrkit",      # Dependency for cloud-utils
        "nixpkgs.wget",
        "nixpkgs.openssl"
    ]
    
    cmd = f"nix-env -iA {' '.join(packages)} >/dev/null 2>&1"
    os.system(cmd)
    
    # Get NoVNC if missing
    if not os.path.exists("./novnc"):
        print("   ⬇️  Downloading NoVNC Viewer...")
        os.system("git clone --depth 1 https://github.com/novnc/noVNC.git novnc >/dev/null 2>&1")
        os.system("git clone --depth 1 https://github.com/novnc/websockify novnc/utils/websockify >/dev/null 2>&1")

# ===========================
# 2. VM BUILDER LOGIC
# ===========================
def prepare_vm():
    print(f"🛠️  2. PREPARING VM ({VM_NAME})...")
    
    vm_dir = os.path.expanduser("~/vms")
    os.makedirs(vm_dir, exist_ok=True)
    
    img_file = f"{vm_dir}/{VM_NAME}.img"
    seed_file = f"{vm_dir}/{VM_NAME}-seed.iso"
    
    # 1. Download Image
    if not os.path.exists(img_file):
        print(f"   ⬇️  Downloading Debian 12 (This may take a minute)...")
        subprocess.run(["wget", "-q", "--show-progress", "-O", img_file + ".tmp", OS_URL])
        os.rename(img_file + ".tmp", img_file)
        
        # Resize Disk
        print(f"   DISK: Resizing to {DISK_SIZE}...")
        os.system(f"qemu-img resize {img_file} {DISK_SIZE} >/dev/null 2>&1")
    else:
        print("   ✅ Disk image ready.")

    # 2. Create Cloud-Init Seed (User: user / Pass: password)
    if not os.path.exists(seed_file):
        print("   🔑 Generating Cloud-Init Seed...")
        
        # Generate password hash using openssl
        pass_hash = subprocess.getoutput("openssl passwd -6 password")
        
        user_data = f"""#cloud-config
hostname: {VM_NAME}
ssh_pwauth: true
disable_root: false
users:
  - name: user
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    password: {pass_hash}
chpasswd:
  list: |
    root:password
    user:password
  expire: false
"""
        meta_data = f"""instance-id: iid-{VM_NAME}
local-hostname: {VM_NAME}
"""
        
        with open("user-data", "w") as f: f.write(user_data)
        with open("meta-data", "w") as f: f.write(meta_data)
        
        # Generate ISO
        os.system(f"cloud-localds {seed_file} user-data meta-data")
        
        # Cleanup
        if os.path.exists("user-data"): os.remove("user-data")
        if os.path.exists("meta-data"): os.remove("meta-data")

    return img_file, seed_file

# ===========================
# 3. SERVICE CONTROLLER
# ===========================
def start_services(img_path, seed_path):
    print(f"\n🚀 3. STARTING SERVICES (Port {WEB_PORT})...")
    
    # Cleanup
    os.system("killall -9 Xvnc websockify fluxbox qemu-system-x86_64 >/dev/null 2>&1")
    os.system("rm -rf /tmp/.X*-lock /tmp/.X11-unix")
    
    # 1. Start VNC
    print("   ► Starting VNC Server...")
    os.system(f"Xvnc {VNC_DISPLAY} -geometry 1280x720 -depth 16 -rfbport {VNC_PORT} -localhost yes -SecurityTypes None >/dev/null 2>&1 &")
    time.sleep(2)
    
    # 2. Start Desktop (Fluxbox)
    print("   ► Starting Desktop...")
    os.system(f"export DISPLAY={VNC_DISPLAY}; fluxbox >/dev/null 2>&1 &")
    
    # 3. Start NoVNC
    print("   ► Starting Web Bridge...")
    os.system(f"./novnc/utils/novnc_proxy --vnc localhost:{VNC_PORT} --listen {WEB_PORT} >/dev/null 2>&1 &")

    # 4. LAUNCH QEMU (THE VM)
    print(f"   ► Launching Debian 12 ({VM_CORES} Cores, {VM_RAM}MB RAM)...")
    
    # QEMU Command constructed carefully for IDX environment
    qemu_cmd = (
        f"export DISPLAY={VNC_DISPLAY}; "
        f"qemu-system-x86_64 "
        f"-enable-kvm "               # CRITICAL: Hardware Acceleration
        f"-m {VM_RAM} "                # RAM
        f"-smp {VM_CORES} "            # Cores
        f"-cpu host "                  # Pass host CPU features
        f"-drive file={img_path},format=qcow2,if=virtio "
        f"-drive file={seed_path},format=raw,if=virtio "
        f"-netdev user,id=n1,hostfwd=tcp::2222-:22 " # Forward SSH to 2222
        f"-device virtio-net-pci,netdev=n1 "
        f"-vga virtio -display gtk,gl=off " # Show GUI window
        f">/dev/null 2>&1 &"
    )
    
    os.system(qemu_cmd)

# ===========================
# 4. ANTI-BAN GUARD
# ===========================
def ban_guard():
    print(f"🛡️  4. ANTI-BAN GUARD ACTIVE (Limit: {CPU_LIMIT}%)...")
    
    while True:
        try:
            # Find QEMU PID
            pids = subprocess.getoutput("pgrep -f qemu-system-x86_64").split()
            for pid in pids:
                # Limit it silently
                os.system(f"cpulimit -p {pid} -l {CPU_LIMIT} -b >/dev/null 2>&1")
        except:
            pass
        time.sleep(5)

# ===========================
# MAIN EXECUTION
# ===========================
try:
    # 1. Setup Nix Tools
    install_tools()
    
    # 2. Prepare VM Files
    img, seed = prepare_vm()
    
    # 3. Start System
    start_services(img, seed)
    
    print("\n" + "="*60)
    print("✅ DEBIAN 12 VM DEPLOYED")
    print("-" * 60)
    print("👉 1. Click 'PORTS' tab below.")
    print(f"👉 2. Click the Globe Icon next to Port {WEB_PORT}.")
    print("👉 3. Add '/vnc.html' to the URL.")
    print("-" * 60)
    print("🔑 VM Login:")
    print("   Username: user")
    print("   Password: password")
    print("-" * 60)
    print("⚠️  Guard Active: CPU limited to prevent bans.")
    print("="*60 + "\n")
    
    # Keep script running to maintain Guard
    ban_guard()

except KeyboardInterrupt:
    print("\nStopped.")
