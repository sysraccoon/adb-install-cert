# adb-install-cert (root required)

This script automatically detect android version and choose preffered way to install certificate to system store.

If you want manually install certificate (or just want to explore, how to do that) see [my guide](./guide/README.md)

## Quick start

Change path to pem certificate and run:

```sh
nix --extra-experimental-features "nix-command flakes" run "github:sysraccoon/adb-install-cert" -- --pem-cert ~/path/to/cert.pem
```

## pip installation

```sh
pip3 install adb-install-cert
```

## NixOS flake installation

```nix
# flake.nix

{
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    inputs.adb-install-cert.url = "github:sysraccoon/adb-install-cert";
    # ...

    outputs = { self, nixpkgs, adb-install-cert, ... } {
        nixosConfigurations.HOSTNAME = nixpkgs.lib.nixosSystem rec {
            system = "x86_64-linux";
            specialArgs = { inherit self system; };
            modules = [
                {
                    environment.systemPackages = [
                        adb-install-cert.packages.${system}.adb-install-cert;
                    ];
                }
            ];
        };
    };
}
```

## Home-Manager flake installation

```nix
# flake.nix
{   
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    inputs.adb-install-cert.url = "github:sysraccoon/adb-install-cert";
    # ...

    outputs = { self, nixpkgs, adb-install-cert, ... } {
        homeConfigurations.USERNAME = home-manager.lib.homeManagerConfiguration rec {
            system = "x86_64-linux";
            specialArgs = { inherit self system; };
            modules = [
                {
                    home.packages = [
                        adb-install-cert.packages.${system}.adb-install-cert;
                    ];
                }
            ];
        };
    };
}

```

## Usage

After installation, you can plug your device and run:

```sh
$ adb-install-cert --cert ~/path/to/cert.pem
```

If certificate format detect incorrectly, pass it directly (only `der` and `pem` support):
```sh
$ adb-install-cert --cert ~/path/to/cert.crt --cert-format der
```

By default `adb-install-cert` automatically select installation mode, based on android version.
If you want override it, pass `--mode` option (see `--help` or read technical description below for more information):
```
$ adb-install-cert --cert ~/path/to/cert.pem --mode temporary
```

If multiple devices present, you can specify one by serial:

```
$ adb-install-cert --cert ~/path/to/cert.pem --device-serial some-serial
```

As alternative, you can use environment variables, as described [here](https://github.com/openatx/adbutils?tab=readme-ov-file#environment):

```
$ ANDROID_SERIAL=emulator-5556 adb-install-cert --cert ~/path/to/cert.pem
```

## Technical Description

**Before Android 10**, **permanent installation** of a certificate is possible by remounting the root directory in read-write mode. These changes may require a device reboot.

**Starting with Android 10**, the root system is available in read-only mode. To install a certificate, the utility uses remounting `/system/etc/security/cacerts` directory in `tmpfs` with a preliminary copy of all existing certificates. **After a reboot, the changes will be reset and the utility will need to be reused**.

**Starting with Android 14**, all logic described before used, but also in order for the changes to take effect, the utility updates the state of running processes.
