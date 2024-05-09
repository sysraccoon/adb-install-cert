
import click
import typing
import logging

from adbutils import adb, AdbDevice
from tempfile import TemporaryDirectory
from pathlib import Path

from adb_install_cert.utils import prepare_pem, open_root_shell, device_is_rooted, get_android_version


REMOTE_OUTPUT_DIR = Path("/data/local/tmp")
REMOTE_TEMP_CACERTS_DIR = REMOTE_OUTPUT_DIR / "cacerts"
REMOTE_CACERTS_DIR = Path("/system/etc/security/cacerts")
APEX_CACERTS_DIR = Path("/apex/com.android.conscrypt/cacerts")


def main():
    adb_install_cert()


@click.command()
@click.option("--pem-cert", "pem_cert_filename", help="set path to PEM certificate", required=True, type=click.Path(exists=True, file_okay=True, dir_okay=False, resolve_path=True))
@click.option("--device-serial", help="select device by serial", default=None)
@click.option("--clean-remote-temp/--no-clean-remote-temp", help="remove temporary files after complete installation", is_flag=True, show_default=True, default=True)
def adb_install_cert(pem_cert_filename, device_serial, clean_remote_temp):
    logging.getLogger().setLevel(logging.DEBUG)

    device = adb.device(serial=device_serial)

    if not device_is_rooted(device):
        logging.critical(f"Root device required. Recheck connected device ${device}")
        exit(1)

    with TemporaryDirectory() as tmp_dir:
        local_prepared_pem_filename = prepare_pem(pem_cert_filename, Path(tmp_dir))
        logging.info(f"[+] prepare certificate: ${local_prepared_pem_filename}")

        remote_prepared_pem_filename = REMOTE_OUTPUT_DIR / local_prepared_pem_filename.name
        device.sync.push(local_prepared_pem_filename, str(remote_prepared_pem_filename))
        logging.info(f"[+] push prepared certificate: ${local_prepared_pem_filename}")

    android_version = get_android_version(device)

    if android_version <= 9:
        legacy_permanent_install_cert(device, remote_prepared_pem_filename)
    
    # applying new installation method to old devices too
    # this allow immediately get effect
    new_temporary_install_cert(device, remote_prepared_pem_filename)

    if android_version >= 14:
        reload_runtime_cert_store(device, remote_prepared_pem_filename)

    if clean_remote_temp:
        with open_root_shell(device) as perform_as_root:
            perform_as_root(["rm", "-r", str(REMOTE_TEMP_CACERTS_DIR)])
            perform_as_root(["rm", str(remote_prepared_pem_filename)])
        logging.info("[+] clean temporary files")


def legacy_permanent_install_cert(device: AdbDevice, remote_pem: Path):
    with open_root_shell(device) as sudo:
        sudo(["mount", "-o", "rw,remount,rw", "/"])
        sudo(["mv", str(remote_pem), str(REMOTE_CACERTS_DIR)])
        sudo(["chmod", "644",  str(REMOTE_CACERTS_DIR / remote_pem.name)])
        sudo(["mount", "-o", "ro,remount,ro", "/"])
        logging.info("[+] permanent install complete")


def new_temporary_install_cert(device: AdbDevice, remote_pem: Path):
    with open_root_shell(device) as sudo:
        sudo(["mkdir", "-p", "-m", "700", str(REMOTE_TEMP_CACERTS_DIR)])
        sudo(["cp", str(REMOTE_CACERTS_DIR / "*"), str(REMOTE_TEMP_CACERTS_DIR)])
        sudo(["mount", "-t", "tmpfs", "tmpfs", str(REMOTE_CACERTS_DIR)])
        sudo(["cp", str(REMOTE_TEMP_CACERTS_DIR / "*"), str(REMOTE_CACERTS_DIR)])
        sudo(["mv", str(remote_pem), str(REMOTE_CACERTS_DIR)])
        sudo(["chmod", "644", str(REMOTE_CACERTS_DIR / remote_pem.name)])
        logging.info("[+] temporary install complete")


def reload_runtime_cert_store(device: AdbDevice, remote_pem: Path):
    with open_root_shell(device) as sudo:
        sudo(["chcon", "u:object_r:system_file:s0", str(REMOTE_CACERTS_DIR / "*")])
        zygote_pid = int(device.shell("pidof zygote || pidof zygote64"))
        sudo([
            "nsenter", f"--mount=/proc/{zygote_pid}/ns/mnt", "--",
            "/bin/mount", "--bind", str(REMOTE_CACERTS_DIR), str(APEX_CACERTS_DIR)
        ])
        zygote_childs = [int(pid) for pid in device.shell(f"ps -o 'PID' -P {zygote_pid} | grep -v PID").splitlines()]
        for zygote_child in zygote_childs:
            sudo([
                "nsenter", f"--mount=/proc/{zygote_child}/ns/mnt", "--",
                "/bin/mount", "--bind", str(REMOTE_CACERTS_DIR), str(APEX_CACERTS_DIR),
            ])


if __name__ == "__main__":
    main()