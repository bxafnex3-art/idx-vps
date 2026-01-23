#!/usr/bin/env python3
import os, subprocess, time, threading

# --- CONFIGURATION ---
VM_NAME = "debian12-idx-crd-v2"
VM_RAM = "7168"         # 7GB RAM
VM_CORES = "6"          # 6 Cores
DISK_SIZE = "10G"       # 10GB Disk
CRD_PIN = "121212"      # Requested PIN

# CPU LIMIT: 70% of *TOTAL* allocated power.
# cpulimit uses 100% per core. So for 6 cores, 70% load = 6 * 70 = 420% limit.
CPU_LIMIT_PERCENT = int(VM_CORES) * 70 

# Debian 12 Cloud Image
OS_URL = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"

# Paths
BASE = os.path.expanduser("~/idxvm")
IMG = f"{BASE}/{VM_NAME}.qcow2"
SEED = f"{BASE}/{VM_NAME}-seed.iso"
MARK = os.path.expanduser("~/.idxvm.installed")

# Set Environment
os.environ["PATH"] = os.path.expanduser("~/.nix-profile/bin") + ":" + os.environ.get("PATH", "")
os.environ["HOSTNAME"] = "localhost"

def sh(cmd):
    subprocess.run(cmd, shell=True)

# 1. INSTALL DEPENDENCIES
def ensure_nix(pkgs):
    if os.path.exists(MARK): return
    print("📦 Installing dependencies via Nix...")
    missing = []
    for p in pkgs:
        name = p.split(".")[-1]
        if subprocess.call(f"nix-env -q {name} >/dev/null 2>&1", shell=True) != 0:
            missing.append(p)
    if missing:
        sh(f"nix-env -iA {' '.join(missing)}")
    open(MARK, "w").close()

ensure_nix(["nixpkgs.qemu", "nixpkgs.cloud-utils", "nixpkgs.wget", "nixpkgs.cpulimit", "nixpkgs.openssh"])

# 2. PREPARE DISK
os.makedirs(BASE, exist_ok=True)
if not os.path.exists(IMG):
    print(f"⬇️ Downloading Debian 12...")
    sh(f"wget -c -O {IMG}.tmp {OS_URL}")
    os.rename(f"{IMG}.tmp", IMG)
    print(f"🔧 Resizing disk to {DISK_SIZE}...")
    sh(f"qemu-img resize {IMG} {DISK_SIZE}")

# 3. CLOUD-INIT (Runs once to install internal tools)
if not os.path.exists(SEED):
    print("⚙️ Generating configuration...")
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

package_update: true
packages:
  - xfce4
  - xfce4-goodies
  - curl
  - wget
  - xclip
  - python3-psutil
  - xbase-clients
  - xrandr

runcmd:
  # Chrome Remote Desktop
  - wget https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb
  - apt install -y ./chrome-remote-desktop_current_amd64.deb
  - rm chrome-remote-desktop_current_amd64.deb

  # Set XFCE as default
  - bash -c 'echo "exec /etc/X11/Xsession /usr/bin/xfce4-session" > /etc/chrome-remote-desktop-session'
  
  # --- HELPER: Auto-Resolution ---
  - echo '#!/bin/bash' > /usr/local/bin/fix-res
  - echo 'xrandr --newmode "1920x1080_60.00" 173.00 1920 2048 2248 2576 1080 1083 1088 1120 -hsync +vsync' >> /usr/local/bin/fix-res
  - echo 'xrandr --addmode Virtual-1 1920x1080_60.00' >> /usr/local/bin/fix-res
  - echo 'xrandr -s 1920x1080' >> /usr/local/bin/fix-res
  - chmod +x /usr/local/bin/fix-res

  # --- HELPER: Re-registration ---
  - echo '#!/bin/bash' > /usr/local/bin/setup-crd
  - echo 'echo "Cleaning up old session..."' >> /usr/local/bin/setup-crd
  - echo 'systemctl stop chrome-remote-desktop' >> /usr/local/bin/setup-crd
  - echo 'rm -rf ~/.config/chrome-remote-desktop' >> /usr/local/bin/setup-crd
  - echo 'read -p "Paste Google Auth Command: " CRD_CMD' >> /usr/local/bin/setup-crd
  - echo 'eval "$CRD_CMD --pin={CRD_PIN}"' >> /usr/local/bin/setup-crd
  - echo 'echo "✅ Registered! Access at https://remotedesktop.google.com/access"' >> /usr/local/bin/setup-crd
  - chmod +x /usr/local/bin/setup-crd

  - systemctl set-default graphical.target
  - reboot
""")
    with open("meta-data", "w") as f:
        f.write(f"instance-id: {VM_NAME}\n")
    sh(f"cloud-localds {SEED} user-data meta-data")
    os.remove("user-data")
    os.remove("meta-data")

# 4. CPU LIMIT GUARD
def limit_qemu_cpu():
    print(f"🛡️  CPU Limiter Active: Capping QEMU at {CPU_LIMIT_PERCENT}% total load.")
    while True:
        # Find QEMU PID
        pids = subprocess.getoutput("pgrep -f qemu-system-x86_64").split()
        for pid in pids:
            # -l is percentage of 1 core. To limit 6 cores to 70%, we use 420.
            # -b runs in background
            subprocess.run(f"cpulimit -p {pid} -l {CPU_LIMIT_PERCENT} -b >/dev/null 2>&1", shell=True)
        time.sleep(10)

# 5. RUN VM
sh("pkill -f qemu-system-x86_64 >/dev/null 2>&1")

print(f"🚀 Booting {VM_NAME}...")
sh(
    f"qemu-system-x86_64 "
    f"-enable-kvm "
    f"-m {VM_RAM} "
    f"-smp {VM_CORES} "
    f"-cpu host "
    f"-drive file={IMG},format=qcow2,if=virtio "
    f"-drive file={SEED},format=raw,if=virtio "
    f"-netdev user,id=n1,hostfwd=tcp::2222-:22 "
    f"-device virtio-net-pci,netdev=n1 "
    f"-vga virtio "
    f"-display none &"
)

# Start CPU Limiter in background
threading.Thread(target=limit_qemu_cpu, daemon=True).start()

# 6. WAIT FOR SSH
print("⏳ Waiting for VM connectivity...")
while subprocess.call("ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no -p 2222 user@localhost 'echo ok' >/dev/null 2>&1", shell=True) != 0:
    time.sleep(2)

print("\n" + "="*50)
print("     🚀 VM READY - CONNECT NOW")
print("="*50)
print("1. Open: https://remotedesktop.google.com/headless")
print("2. Click Begin -> Next -> Authorize -> Copy 'Debian Linux' code.")
print("3. Run this command here:")
print(f"\n   ssh -o StrictHostKeyChecking=no -p 2222 user@localhost setup-crd\n")
print("   (Password: password)")
print("-" * 50)
print("💡 Resolution Issue? Open terminal in VM and run: fix-res")
print("="*50)

while True: time.sleep(3600)
