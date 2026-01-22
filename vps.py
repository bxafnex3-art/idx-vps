#!/usr/bin/env python3
import os, subprocess, time, threading

# ================= CONFIG =================
VM_NAME = "debian12-idx"
VM_RAM = "4096"
VM_CORES = "2"
DISK_SIZE = "20G"
OS_URL = "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"

WEB_PORT = 6080
VNC_PORT = 5900
CPU_LIMIT = 70

BASE = os.path.expanduser("~/idxvm")
IMG = f"{BASE}/{VM_NAME}.qcow2"
SEED = f"{BASE}/{VM_NAME}-seed.iso"
MARK = os.path.expanduser("~/.idxvm.installed")

os.environ["PATH"] = os.path.expanduser("~/.nix-profile/bin") + ":" + os.environ.get("PATH", "")
os.environ["HOSTNAME"] = "localhost"

def sh(cmd):
    subprocess.run(cmd, shell=True)

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
    "nixpkgs.cloud-utils",
    "nixpkgs.wget",
    "nixpkgs.git",
    "nixpkgs.cpulimit",
    "nixpkgs.cloudflared"
])

# noVNC
if not os.path.exists("novnc"):
    sh("git clone --depth 1 https://github.com/novnc/noVNC.git novnc")
    sh("git clone --depth 1 https://github.com/novnc/websockify novnc/utils/websockify")

# Image
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
ssh_pwauth: true
""")
    with open("meta-data", "w") as f:
        f.write(f"instance-id: {VM_NAME}\n")
    sh(f"cloud-localds {SEED} user-data meta-data")
    os.remove("user-data")
    os.remove("meta-data")

# Cleanup
sh("pkill -f qemu-system-x86_64 >/dev/null 2>&1")
sh("pkill -f novnc_proxy >/dev/null 2>&1")
sh("pkill -f cloudflared >/dev/null 2>&1")

# noVNC
sh(f"HOSTNAME=localhost ./novnc/utils/novnc_proxy --vnc localhost:{VNC_PORT} --listen {WEB_PORT} &")
time.sleep(2)
print(f"\n🖥 Local: http://localhost:{WEB_PORT}/vnc.html")

# Cloudflare
print("► Starting Cloudflare tunnel...")
sh("rm -f /tmp/cf.log")
sh(f"cloudflared tunnel --url http://localhost:{WEB_PORT} --no-autoupdate >/tmp/cf.log 2>&1 &")

public = ""
for _ in range(40):
    out = subprocess.getoutput("grep -o 'https://[a-z0-9.-]*trycloudflare.com' /tmp/cf.log | tail -1")
    if out:
        public = out
        break
    time.sleep(1)

if public:
    print("\n🌐 Public URL:")
    print(public + "/vnc.html\n")
else:
    print("⚠️  Cloudflare URL not detected. Check /tmp/cf.log\n")

# CPU guard
def limit_qemu_cpu():
    while True:
        for pid in subprocess.getoutput("pgrep -f qemu-system-x86_64").split():
            sh(f"cpulimit -p {pid} -l {CPU_LIMIT} -b >/dev/null 2>&1")
        time.sleep(10)

# QEMU (VNC)
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
    f"-vnc :0 &"
)

threading.Thread(target=limit_qemu_cpu, daemon=True).start()

print("VM running.")
print("Debian login: user / password")
print("SSH: ssh user@localhost -p 2222\n")

while True:
    time.sleep(900)
