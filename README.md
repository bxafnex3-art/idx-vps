bash -c '
# 1) Ensure python exists in IDX
if [ ! -x "$HOME/.nix-profile/bin/python3" ]; then
  echo "Installing python3..."
  nix-env -iA nixpkgs.python3
fi

# 2) Ensure cloudflared exists
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Installing cloudflared..."
  nix-env -iA nixpkgs.cloudflared
fi

# 3) Auto-fix SSH host-key mismatch (safe, does NOT delete VM)
ssh-keygen -R "[localhost]:2222" >/dev/null 2>&1 || true

# 4) Run the VM launcher
curl -fsSL https://raw.githubusercontent.com/bxafnex3-art/idx-vps/main/vps.py | "$HOME/.nix-profile/bin/python3"
'
