#!/usr/bin/env python3
import os, subprocess, time, threading

# --- CONFIGURATION ---
VM_NAME = "debian12-crd-fixed"  # Changed name to force fresh install
VM_RAM = "6144"                 # 6GB RAM
VM_CORES = "6"                  # 6 Cores
DISK_SIZE = "10G"               # 10GB Disk (Requested)
CRD_PIN = "121212"              # PIN

CPU_LIMIT_PERCENT = 420         # 70% of 6 Cores

BASE = os.path.expanduser("~/idxvm")
IMG = f"{BASE}/{VM_NAME}.qcow2"
SEED = f"{BASE}/{VM_NAME}-seed.iso"
MARK = os.path.expanduser("~/.idxvm.installed")

# Check if this is a fresh install or a resume
IS_EXISTING_VM = os.path.exists(IMG)

os.environ["PATH"] = os.path.expanduser("~/.nix-profile/bin") + ":" + os.environ.get("PATH", "")
os.environ["HOSTNAME"] = "localhost"

def sh(cmd): subprocess.run(cmd, shell=True)

# 1. INSTALL DEPENDENCIES
def ensure_nix(pkgs):
    if os.path.exists(MARK): return
    print("📦 Installing dependencies...")
    missing = [p for p in pkgs if subprocess.call(f"nix-env -q {p.split('.')[-1]} >/dev/null 2>&1", shell=True) != 0]
    if missing: sh(f"nix-env -iA {' '.join(missing)}")
    open(MARK, "w").close()

ensure_nix(["nixpkgs.qemu", "nixpkgs.cloud-utils", "nixpkgs.wget", "nixpkgs.cpulimit", "nixpkgs.openssh"])

# 2. PREPARE DISK
os.makedirs(BASE, exist_ok=True)
if not os.path.exists(IMG):
    print(f"⬇️ Downloading Debian 12...")
    sh(f"wget -c -O {IMG}.tmp https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2")
    os.rename(f"{IMG}.tmp", IMG)
    sh(f"qemu-img resize {IMG} {DISK_SIZE}")

# 3. CLOUD-INIT
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
  - xbase-clients
  - xrandr
  - curl
  - wget
  - git
  - nano
  - unzip
  - zip
  - build-essential
  - xclip
  - chromium
  - python3-psutil
write_files:
  - path: /usr/local/bin/fix-res
    permissions: '0755'
    content: |
      #!/bin/bash
      xrandr --newmode "1920x1080_60.00" 173.00 1920 2048 2248 2576 1080 1083 1088 1120 -hsync +vsync
      xrandr --addmode Virtual-1 1920x1080_60.00
      xrandr -s 1920x1080
  - path: /usr/local/bin/setup-crd
    permissions: '0755'
    content: |
      #!/bin/bash
      echo "---------------------------------------------"
      echo "  SETTING UP CHROME REMOTE DESKTOP"
      echo "---------------------------------------------"
      echo "1. Stopping any running services..."
      sudo systemctl stop chrome-remote-desktop
      
      echo "2. Cleaning old configs..."
      rm -rf ~/.config/chrome-remote-desktop
      
      echo "3. Paste the 'Debian Linux' command from Google now:"
      read CRD_CMD
      
      if [ -z "$CRD_CMD" ]; then
        echo "❌ Error: You didn't paste anything!"
        exit 1
      fi

      echo "4. Registering with PIN {CRD_PIN}..."
      # Use eval to execute the pasted command with the PIN appended
      eval "$CRD_CMD --pin={CRD_PIN}"
      
      echo "---------------------------------------------"
      echo "✅ SUCCESS! Go to https://remotedesktop.google.com/access"
      echo "---------------------------------------------"

runcmd:
  - wget https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb
  - apt install -y ./chrome-remote-desktop_current_amd64.deb
  - rm chrome-remote-desktop_current_amd64.deb
  - bash -c 'echo "exec /etc/X11/Xsession /usr/bin/xfce4-session" > /etc/chrome-remote-desktop-session'
  - mkdir -p /etc/apt/keyrings
  - curl -fsSL https://us-central1-apt.pkg.dev/doc/repo-signing-key.gpg | gpg --dearmor --yes -o /etc/apt/keyrings/antigravity-repo-key.gpg
  - echo "deb [signed-by=/etc/apt/keyrings/antigravity-repo-key.gpg] https://us-central1-apt.pkg.dev/projects/antigravity-auto-updater-dev/ antigravity-debian main" > /etc/apt/sources.list.d/antigravity.list
  - apt update
  - apt install -y antigravity
  - systemctl set-default graphical.target
  - reboot
""")
    with open("meta-data", "w") as f: f.write(f"instance-id: {VM_NAME}\n")
    sh(f"cloud-localds {SEED} user-data meta-data")
    os.remove("user-data"); os.remove("meta-data")

# 4. CPU LIMIT & RUN
def limit_cpu():
    while True:
        for pid in subprocess.getoutput("pgrep -f qemu-system-x86_64").split():
            subprocess.run(f"cpulimit -p {pid} -l {CPU_LIMIT_PERCENT} -b >/dev/null 2>&1", shell=True)
        time.sleep(10)

sh("pkill -f qemu-system-x86_64 >/dev/null 2>&1")

print(f"🚀 Booting {VM_NAME}...")
sh(
    f"qemu-system-x86_64 -enable-kvm -m {VM_RAM} -smp {VM_CORES} -cpu host "
    f"-drive file={IMG},format=qcow2,if=virtio "
    f"-drive file={SEED},format=raw,if=virtio "
    f"-netdev user,id=n1,hostfwd=tcp::2222-:22 "
    f"-device virtio-net-pci,netdev=n1 -display none &"
)
threading.Thread(target=limit_cpu, daemon=True).start()

# 5. SMART INSTRUCTIONS
print("⏳ Waiting for VM connectivity (This will take 3-5 mins)...")
while subprocess.call("ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no -p 2222 user@localhost 'echo ok' >/dev/null 2>&1", shell=True) != 0:
    time.sleep(2)

print("\n" + "="*50)
if IS_EXISTING_VM:
    print("     ✅ VM RESUMED (Data Saved)")
    print("="*50)
    print("1. Go to: https://remotedesktop.google.com/access")
    print(f"2. Click on '{VM_NAME}' (it should come online in ~30s)")
    print("3. Enter PIN: 121212")
else:
    print("     🚀 NEW INSTALLATION DETECTED")
    print("="*50)
    print("1. Go to: https://remotedesktop.google.com/headless")
    print("2. Click Begin -> Next -> Authorize -> Copy 'Debian Linux' code.")
    print("3. Run this command here:")
    print(f"   ssh -o StrictHostKeyChecking=no -p 2222 user@localhost setup-crd")
    print("   (Password: password)")
print("="*50)
while True: time.sleep(3600)
