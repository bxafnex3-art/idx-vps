#!/usr/bin/env bash
set -e
export NIX_CONFIG="download-buffer-size = 50000000"

# Ensure python (Nix path-safe)
if [ ! -x "$HOME/.nix-profile/bin/python3" ]; then
  echo "🐍 python3 not found, installing..."
  nix-env -iA nixpkgs.python3
fi

$HOME/.nix-profile/bin/python3 - << 'PYCODE'
import os, subprocess, time, threading

# ================= CONFIG =================
VM_NAME = "debian12-idx"
VM_RAM = "8192"
VM_CORES = "4"
DISK_SIZE = "30G"
OS_URL = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"

WEB_PORT = 6080
VNC_PORT = 5901
VNC_DISPLAY = ":1"
USE_CLOUDFLARE = True
CPU_LIMIT = 70

BASE = os.path.expanduser("~/idxvm")
IMG = f"{BASE}/{VM_NAME}.qcow2"
SEED = f"{BASE}/{VM_NAME}-seed.iso"
MARK = os.path.expanduser("~/.idxvm.installed")

def sh(cmd):
    subprocess.run(cmd, shell=True)

# ================= NIX INSTALL =================
def ensure_nix(pkgs):
    if os.path.exists(MARK):
        return
    missing = []
    for p in pkgs:
        name = p.split(".")[-1]
        if subprocess.call(f"nix-env -q {name} >/dev/null 2>&1", shell=True) != 0:
            missing.append(p)
    if missing:
        print("📦 Installing:", " ".join(missing))
        sh(f"nix-env -iA {' '.join(missing)}")
    open(MARK, "w").close()

ensure_nix([
    "nixpkgs.qemu",
    "nixpkgs.tigervnc",
    "nixpkgs.fluxbox",
    "nixpkgs.cloud-utils",
    "nixpkgs.wget",
    "nixpkgs.git",
    "nixpkgs.cloudflared",
    "nixpkgs.cpulimit"
])

# ================= noVNC =================
if not os.path.exists("novnc"):
    sh("git clone --depth 1 https://github.com/novnc/noVNC.git novnc")
    sh("git clone --depth 1 https://github.com/novnc/websockify novnc/utils/websockify")

# ================= IMAGE =================
os.makedirs(BASE, exist_ok=True)

if not os.path.exists(IMG):
    sh(f"wget -c -O {IMG}.tmp {OS_URL}")
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

runcmd:
  - |
      cat >/etc/systemd/system/cpu-limit.service <<'EOF'
      [Unit]
      Description=Global CPU Limit
      After=multi-user.target

      [Service]
      Type=oneshot
      ExecStart=/bin/sh -c "echo '{CPU_LIMIT}000 100000' > /sys/fs/cgroup/cpu.max || true"

      [Install]
      WantedBy=multi-user.target
      EOF
  - systemctl daemon-reload
  - systemctl enable cpu-limit.service
""")
    with open("meta-data", "w") as f:
        f.write(f"instance-id: {VM_NAME}\n")
    sh(f"cloud-localds {SEED} user-data meta-data")
    os.remove("user-data")
    os.remove("meta-data")

# ================= CLEANUP =================
sh("pkill -f Xvnc >/dev/null 2>&1")
sh("pkill -f qemu-system-x86_64 >/dev/null 2>&1")
sh("pkill -f novnc_proxy >/dev/null 2>&1")
sh("pkill -f cloudflared >/dev/null 2>&1")

# ================= START DISPLAY =================
sh(f"Xvnc {VNC_DISPLAY} -geometry 1280x720 -depth 16 -rfbport {VNC_PORT} -localhost yes -SecurityTypes None &")
time.sleep(2)
sh(f"export DISPLAY={VNC_DISPLAY}; fluxbox &")
sh(f"./novnc/utils/novnc_proxy --vnc localhost:{VNC_PORT} --listen {WEB_PORT} &")

if USE_CLOUDFLARE:
    sh(f"cloudflared tunnel --url http://localhost:{WEB_PORT} --no-autoupdate >/tmp/cf.log 2>&1 &")
    time.sleep(3)
    sh("grep -o 'https://[a-z0-9.-]*trycloudflare.com' /tmp/cf.log | tail -1")

# ================= CPU GUARD =================
def limit_qemu_cpu():
    while True:
        try:
            pids = subprocess.getoutput("pgrep -f qemu-system-x86_64").split()
            for pid in pids:
                sh(f"cpulimit -p {pid} -l {CPU_LIMIT} -b >/dev/null 2>&1")
        except:
            pass
        time.sleep(10)

# ================= START QEMU =================
sh(
    f"export DISPLAY={VNC_DISPLAY}; "
    f"qemu-system-x86_64 "
    f"-enable-kvm "
    f"-m {VM_RAM} "
    f"-smp {VM_CORES} "
    f"-cpu host "
    f"-object iothread,id=iothread0 "
    f"-drive file={IMG},format=qcow2,if=virtio,cache=writeback,iothread=iothread0 "
    f"-drive file={SEED},format=raw,if=virtio "
    f"-netdev user,id=n1,hostfwd=tcp::2222-:22 "
    f"-device virtio-net-pci,netdev=n1 "
    f"-device virtio-balloon "
    f"-vga virtio -display gtk,gl=off &"
)

threading.Thread(target=limit_qemu_cpu, daemon=True).start()

print("VM ready. user/password")

while True:
    time.sleep(900)
PYCODE
