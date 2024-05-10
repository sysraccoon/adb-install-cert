{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  inputs.poetry2nix.url = "github:nix-community/poetry2nix";

  outputs = { self, nixpkgs, poetry2nix }:
    let
      supportedSystems = [ "x86_64-linux" "x86_64-darwin" "aarch64-linux" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      pkgs = forAllSystems (system: nixpkgs.legacyPackages.${system});
      pypkgs-build-requirements = {
        apkutils2 = [ "setuptools" ];
        adbutils = [ "setuptools" "pbr" ];
      };
      p2n-overrides = (p2n: p2n.defaultPoetryOverrides.extend (final: prev:
          builtins.mapAttrs (package: build-requirements:
            (builtins.getAttr package prev).overridePythonAttrs (old: {
              buildInputs = (old.buildInputs or [ ]) ++ (builtins.map (pkg: if builtins.isString pkg then builtins.getAttr pkg prev else pkg) build-requirements);
            })
        ) pypkgs-build-requirements));
    in
    {
      apps = rec {
          default = adb-install-cert;
          adb-install-cert = {
            type = "app";
            program = "${self.packages.adb-install-cert}/bin/adb-install-cert";
          };
      };

      packages = forAllSystems (system: let
        p2n = (poetry2nix.lib.mkPoetry2Nix { pkgs = pkgs.${system}; });
      in rec {
        default = adb-install-cert;
        adb-install-cert = p2n.mkPoetryApplication {
          projectDir = self;
          propogateBuildInputs = [ pkgs.${system}.openssl ];
          overrides = p2n-overrides p2n;
        };
      });

      devShells = forAllSystems (system: let
        p2n = (poetry2nix.lib.mkPoetry2Nix { pkgs = pkgs.${system}; });
      in rec {
        default = adb-install-cert;
        adb-install-cert = pkgs.${system}.mkShellNoCC {
          packages = with pkgs.${system}; [
            (p2n.mkPoetryEnv {
              projectDir = self;
              overrides = p2n-overrides p2n;
            }) poetry
          ];
        };
      });
    };
}
