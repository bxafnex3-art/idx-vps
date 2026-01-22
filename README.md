bash -c '
if [ ! -x "$HOME/.nix-profile/bin/python3" ]; then
  nix-env -iA nixpkgs.python3
fi
curl -fsSL https://raw.githubusercontent.com/bxafnex3-art/idx-vps/main/vps.py | "$HOME/.nix-profile/bin/python3"
'
