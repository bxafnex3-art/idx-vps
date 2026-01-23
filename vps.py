#!/usr/bin/env python3
import os, subprocess, time, threading, sys

# --- CONFIGURATION ---
VM_NAME = "debian12-v17-stable"
VM_RAM = "8192"                 # 5GB RAM (Safe Limit for Containers)
VM_CORES = "6"                  # 4 Cores (Stability)
DISK_SIZE = "10G"               # 10GB Disk
CRD_PIN = "121212"              # PIN

# CPU LIMIT: 70% of 4 Cores = 280
CPU_LIMIT_PERCENT = 280

# --- INSTALLER SCRIPT (Runs inside VM) ---
INSTALL_SCRIPT = """
set -e
export DEBIAN_FRONTEND=noninteractive
echo "--------------------------------------------------"
echo "📦 STARTING LIVE INSTALLATION"
echo "--------------------------------------------------"

# 1. Basic Setup & Repos
echo ">> Updating Repositories..."
sudo apt-get update -qq >/dev/null

echo ">> Installing Basic Tools..."
sudo apt-get install -y -qq curl wget git unzip zip xclip python3-psutil haveged qemu-guest-agent sshpass >/dev/null

# 2. Desktop Environment (XFCE)
echo ">> Installing XFCE Desktop..."
sudo apt-get install -y -qq xfce4 xfce4-goodies lightdm dbus-x11 xbase-clients x11-xserver-utils >/dev/null

# 3. Antigravity
echo ">> Installing Antigravity..."
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://us-central1-apt.pkg.dev/doc/repo-signing-key.gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/antigravity-repo-key.gpg
echo "deb [signed-by=/etc/apt/keyrings/antigravity-repo-key.gpg] https://us-central1-apt.pkg.dev/projects/antigravity-auto-updater-dev/ antigravity-debian main" | sudo tee /etc/apt/sources.list.d/antigravity.list > /dev/null
sudo apt-get update -qq >/dev/null
sudo apt-get install -y -qq antigravity >/dev/null

# 4. Browsers (Chrome + Chromium)
echo ">> Installing Google Chrome..."
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt-get install -y ./google-chrome-stable_current_amd64.deb >/dev/null 2>&1 || sudo apt-get install -f -y >/dev/null
rm google-chrome-stable_current_amd64.deb

echo ">> Installing Chromium..."
sudo apt-get install -y -qq chromium >/dev/null

# 5. Chrome Remote Desktop
echo ">> Installing Chrome Remote Desktop..."
wget -q https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb
sudo apt-get install -y ./chrome-remote-desktop_current_amd64.deb >/dev/null 2>&1 || sudo apt-get install -f -y >/dev/null
rm chrome-remote-desktop_current_amd64.deb

# 6. Shortcuts
echo ">> Creating Shortcuts..."
mkdir -p /home/user/Desktop
echo '[Desktop Entry]\nVersion=1.0\nType=Application\nName=Antigravity\nExec=xfce4-terminal -e "antigravity"\nIcon=utilities-terminal\nTerminal=false\nStartupNotify=false' > /home/user/Desktop/antigravity.desktop
echo '[Desktop Entry]\nVersion=1.0\nType=Application\nName=Google Chrome\nExec=google-chrome-stable\nIcon=google-chrome\nTerminal=false\nStartupNotify=true' > /home/user/Desktop/google-chrome.desktop
chmod +x /home/user/Desktop/*.desktop
chown user:user /home/user/Desktop/*.desktop

# 7. Final Config
echo "exec /usr/bin/xfce4-session" > /home/user/.chrome-remote-desktop-session
sudo systemctl set-default graphical.target

# CRITICAL FIX: Unmask service before enabling
sudo systemctl unmask chrome-remote-desktop.service
sudo systemctl enable chrome-remote-desktop.service
sudo systemctl restart chrome-remote-desktop.service

echo "--------------------------------------------------"
echo "✅ INSTALLATION COMPLETE!"
echo "--------------------------------------------------"
"""

BASE = os.path.expanduser("~/idxvm")
IMG = f"{BASE}/{VM_NAME}.qcow2"
SEED = f"{BASE}/{VM_NAME}-seed.iso"
MARK = os.path.expanduser("~/.idxvm.installed")

IS_EXISTING_VM = os.path.exists(IMG)

os.environ["PATH"] = os.path.expanduser("~/.nix-profile/bin") + ":" + os.environ.get("PATH", "")
os.environ["HOSTNAME"] = "localhost"

def sh(cmd): subprocess.run(cmd, shell=True)

# 1. INSTALL HOST DEPENDENCIES
def ensure_nix(pkgs):
    if os.path.exists(MARK): return
    print("📦 Installing host dependencies...")
    missing = [p for p in pkgs if subprocess.call(f"nix-env -q {p.split('.')[-1]} >/dev/null 2>&1", shell=True) != 0]
    if missing: sh(f"nix-env -iA {' '.join(missing)}")
    open(MARK, "w").close()

ensure_nix(["nixpkgs.qemu", "nixpkgs.cloud-utils", "nixpkgs.wget", "nixpkgs.cpulimit", "nixpkgs.openssh", "nixpkgs.sshpass"])

# 2. PREPARE DISK
os.makedirs(BASE, exist_ok=True)
if not os.path.exists(IMG):
    print(f"⬇️ Downloading Debian 12...")
    sh(f"wget -c -O {IMG}.tmp https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2")
    os.rename(f"{IMG}.tmp", IMG)
    print(f"🔧 Resizing disk to {DISK_SIZE}...")
    sh(f"qemu-img resize {IMG} {DISK_SIZE}")

# 3. CLOUD-INIT (MINIMAL)
if not os.path.exists(SEED):
    print("⚙️ Generating minimal configuration...")
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
# No packages installed here to ensure fast boot
package_update: false
packages:
  - openssh-server

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
      
      sudo systemctl stop chrome-remote-desktop >/dev/null 2>&1
      rm -rf ~/.config/chrome-remote-desktop
      
      while true; do
          echo ""
          echo "👉 Paste the 'Debian Linux' command from Google (starts with DISPLAY=):"
          read CRD_CMD
          if [[ "$CRD_CMD" == DISPLAY=* ]]; then
              break
          else
              echo "❌ Invalid input. Try again."
          fi
      done

      echo "🚀 Registering..."
      eval "$CRD_CMD --pin={CRD_PIN}"
      
      echo "---------------------------------------------"
      echo "✅ SUCCESS! Go to https://remotedesktop.google.com/access"
      echo "---------------------------------------------"

runcmd:
  # Swap File
  - fallocate -l 4G /swapfile
  - chmod 600 /swapfile
  - mkswap /swapfile
  - swapon /swapfile
  - echo '/swapfile none swap sw 0 0' >> /etc/fstab
""")
    with open("meta-data", "w") as f: f.write(f"instance-id: {VM_NAME}\n")
    sh(f"cloud-localds {SEED} user-data meta-data")
    os.remove("user-data"); os.remove("meta-data")

# 4. CPU LIMIT
def limit_cpu():
    time.sleep(30) # Wait for boot
    while True:
        for pid in subprocess.getoutput("pgrep -f qemu-system-x86_64").split():
            subprocess.run(f"cpulimit -p {pid} -l {CPU_LIMIT_PERCENT} -b >/dev/null 2>&1", shell=True)
        time.sleep(10)

sh("pkill -f qemu-system-x86_64 >/dev/null 2>&1")

print(f"🚀 Booting {VM_NAME} ({VM_RAM}MB RAM)...")
sh(
    f"qemu-system-x86_64 -enable-kvm -m {VM_RAM} -smp {VM_CORES} -cpu host "
    f"-drive file={IMG},format=qcow2,if=virtio "
    f"-drive file={SEED},format=raw,if=virtio "
    f"-netdev user,id=n1,hostfwd=tcp::2222-:22 "
    f"-device virtio-net-pci,netdev=n1 -display none &"
)

threading.Thread(target=limit_cpu, daemon=True).start()

# 5. AUTO-CONNECT & INSTALL
print("⏳ Waiting for VM connectivity...")
while True:
    if subprocess.call("pgrep -f qemu-system-x86_64 >/dev/null", shell=True) != 0:
        print("❌ CRITICAL: VM Process Died. (RAM was too high for container)")
        sys.exit(1)
        
    # Using sshpass to check connection without prompting
    if subprocess.call("sshpass -p password ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no -p 2222 user@localhost 'echo ok' >/dev/null 2>&1", shell=True) == 0:
        print("✅ SSH Connected!")
        break
    time.sleep(2)

if not IS_EXISTING_VM:
    print("\n📦 Pushing Live Installer to VM...")
    # Write script to file inside VM (Authed via sshpass)
    p = subprocess.Popen(["sshpass", "-p", "password", "ssh", "-o", "StrictHostKeyChecking=no", "-p", "2222", "user@localhost", "cat > install.sh"], stdin=subprocess.PIPE)
    p.communicate(input=INSTALL_SCRIPT.encode())
    
    # Run it (Authed via sshpass)
    print("▶️ Executing Installer (Auto-Password)...")
    subprocess.run("sshpass -p password ssh -o StrictHostKeyChecking=no -p 2222 user@localhost 'chmod +x install.sh && ./install.sh'", shell=True)
    
    print("\n✅ Install Done. Rebooting...")
    subprocess.run("sshpass -p password ssh -o StrictHostKeyChecking=no -p 2222 user@localhost 'sudo reboot'", shell=True)
    time.sleep(10)

# 6. INSTRUCTIONS
print("\n" + "="*50)
print("     🚀 READY FOR SETUP")
print("="*50)
print("1. Go to: https://remotedesktop.google.com/headless")
print("2. Click Begin -> Next -> Authorize -> Copy 'Debian Linux' code.")
print("3. Run this command here:")
print(f"   sshpass -p password ssh -o StrictHostKeyChecking=no -p 2222 user@localhost setup-crd")
print("   (Password: password)")
print("="*50)

while True: time.sleep(3600)
