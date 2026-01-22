#!/usr/bin/env python3
import os
import subprocess
import time
import sys

# ===========================
# CONFIGURATION
# ===========================
# MEMORY SET TO 12GB (Max safe limit for IDX to prevent crashing)
VM_RAM = "12288"      
VM_CORES = "4"        
DISK_SIZE = "10G"     
WEB_PORT = 6085       # Port 6085 (Avoids conflicts)
VNC_PORT = 5905
VNC_DISPLAY = ":5"

def run_cmd(cmd):
    """Runs a shell command silently."""
    os.system(cmd + " >/dev/null 2>&1")

def install_dependencies():
    """Installs required tools using Nix."""
    print("📦 1. CHECKING & INSTALLING TOOLS...")
    # We install process management tools (psmisc) and the VM tools
    packages = [
        "nixpkgs.tigervnc", "nixpkgs.websockify", "nixpkgs.fluxbox",
        "nixpkgs.qemu", "nixpkgs.cpulimit", "nixpkgs.wget", 
        "nixpkgs.git", "nixpkgs.psmisc" 
    ]
    # Install all at once
    os.system(f"nix-env -iA {' '.join(packages)} >/dev/null 2>&1")
    
    # Download NoVNC if missing
    if not os.path.exists("./novnc"):
        print("   ⬇️  Downloading NoVNC...")
        run_cmd("git clone --depth 1 https://github.com/novnc/noVNC.git novnc")
        run_cmd("git clone --depth 1 https://github.com/novnc/websockify novnc/utils/websockify")

def cleanup():
    """Kills old processes to free up RAM."""
    print("🧹 2. CLEANING UP OLD PROCESSES...")
    run_cmd("pkill -9 -f qemu-system-x86_64")
    run_cmd("pkill -9 -f Xvnc")
    run_cmd("pkill -9 -f websockify")
    run_cmd("rm -rf /tmp/.X*-lock /tmp/.X11-unix")

def setup_vm():
    """Downloads and resizes the VM image."""
    print(f"🛠️  3. SETTING UP VM ({DISK_SIZE})...")
    os.makedirs(os.path.expanduser("~/vms"), exist_ok=True)
    img = os.path.expanduser(f"~/vms/debian12.img")
    
    # Download if missing
    if not os.path.exists(img):
        print("   ⬇️  Downloading Debian 12...")
        subprocess.run(["wget", "-q", "-O", img + ".tmp", "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"])
        os.rename(img + ".tmp", img)
    
    # Force Resize
    print(f"   💾 Resizing Disk...")
    run_cmd(f"qemu-img resize {img} {DISK_SIZE}")
    return img

def start_services(img_path):
    """Starts the VNC server and VM."""
    print(f"🚀 4. STARTING SYSTEM...")
    
    # 1. Start VNC
    run_cmd(f"Xvnc {VNC_DISPLAY} -geometry 1280x720 -depth 16 -rfbport {VNC_PORT} -localhost yes -SecurityTypes None &")
    time.sleep(2)
    
    # 2. Start Fluxbox (Window Manager)
    run_cmd(f"export DISPLAY={VNC_DISPLAY}; fluxbox &")
    
    # 3. Start NoVNC (Web Interface)
    print(f"   ► Starting Web Bridge on Port {WEB_PORT}...")
    run_cmd(f"./novnc/utils/novnc_proxy --vnc localhost:{VNC_PORT} --listen {WEB_PORT} &")
    
    # 4. Start QEMU (The VM)
    print(f"   ► Booting VM ({VM_RAM}MB RAM)...")
    qemu_cmd = (
        f"export DISPLAY={VNC_DISPLAY}; "
        f"qemu-system-x86_64 "
        f"-enable-kvm "
        f"-m {VM_RAM} "
        f"-smp {VM_CORES} "
        f"-cpu host "
        f"-drive file={img_path},format=qcow2 "
        f"-netdev user,id=n1 -device virtio-net-pci,netdev=n1 "
        f"-vga virtio -display gtk,gl=off &"
    )
    run_cmd(qemu_cmd)

def main():
    install_dependencies()
    cleanup()
    img = setup_vm()
    start_services(img)
    
    print("\n" + "="*60)
    print(f"✅ VM STARTED (12GB RAM / 10GB Disk)")
    print("-" * 60)
    print(f"👉 1. REFRESH your browser (F5) if the Ports tab is buggy.")
    print(f"👉 2. Open Port {WEB_PORT} in the Ports tab.")
    print(f"👉 3. Add '/vnc.html' to the URL.")
    print("="*60 + "\n")
    
    # Keep script running
    while True:
        time.sleep(10)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
