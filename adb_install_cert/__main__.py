
import click
import typing
import logging

from adbutils import adb, AdbDevice
from tempfile import TemporaryDirectory
from pathlib import Path

from adb_install_cert.utils import \
    prepare_pem, open_root_shell, device_is_rooted, get_android_version, apex_is_present


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
    
    if android_version >= 10 and android_version < 14:
        new_temporary_install_cert(device, REMOTE_CACERTS_DIR, remote_prepared_pem_filename)

    if android_version >= 14:
        new_temporary_install_cert(device, APEX_CACERTS_DIR, remote_prepared_pem_filename)
        reload_runtime_cert_store(device, remote_prepared_pem_filename)

    if clean_remote_temp:
        with open_root_shell(device) as perform_as_root:
            perform_as_root(["rm", "-r", str(REMOTE_TEMP_CACERTS_DIR)])
            perform_as_root(["rm", "-r", str(remote_prepared_pem_filename)])
        logging.info("[+] clean temporary files")


def legacy_permanent_install_cert(device: AdbDevice, remote_pem: Path):
    with open_root_shell(device) as sudo:
        # remount /system in read write mode
        sudo(["mount", "-o", "rw,remount,rw", "/system"])
        # copy certificate to system store
        sudo(["cp", str(remote_pem), str(REMOTE_CACERTS_DIR)])
        # fix permissions of certificate
        sudo(["chmod", "644",  str(REMOTE_CACERTS_DIR / remote_pem.name)])
        # revert remounting
        sudo(["mount", "-o", "ro,remount,ro", "/system"])
        logging.info("[+] permanent install complete")


def new_temporary_install_cert(device: AdbDevice, source_cacerts_dir: Path, remote_pem: Path):
    with open_root_shell(device) as sudo:
        # make temporary directory for certificates
        sudo(["mkdir", "-p", "-m", "700", str(REMOTE_TEMP_CACERTS_DIR)])
        # copy source certificates
        sudo(["cp", str(source_cacerts_dir / "*"), str(REMOTE_TEMP_CACERTS_DIR)])
        # remount system cacerts directory as tmpfs
        sudo(["mount", "-t", "tmpfs", "tmpfs", str(REMOTE_CACERTS_DIR)])
        # copy all preliminary saved certificates to system cacerts directory
        sudo(["cp", str(REMOTE_TEMP_CACERTS_DIR / "*"), str(REMOTE_CACERTS_DIR)])
        # copy new certificate to mounted directory
        sudo(["cp", str(remote_pem), str(REMOTE_CACERTS_DIR)])
        # fix permissions of certificate
        sudo(["chmod", "644", str(REMOTE_CACERTS_DIR / remote_pem.name)])
        # fix selinux context labels
        sudo(["chcon", "u:object_r:system_file:s0", str(REMOTE_CACERTS_DIR / "*")])
        sudo(["chcon", "u:object_r:system_file:s0", str(REMOTE_CACERTS_DIR)])
        logging.info("[+] temporary install complete")


def reload_runtime_cert_store(device: AdbDevice, remote_pem: Path):
    def pids_of(proccess_name: str):
        return [int(pid) for pid in device.shell(["pidof", proccess_name]).split()]

    def reload_zygote_and_childs(zygote_pid: int):
        pids = [int(pid) for pid in device.shell(f"ps -o 'PID' -P {zygote_pid} | grep -v PID").splitlines()]
        pids.append(zygote_pid)
        with open_root_shell(device) as sudo:
            for pid in pids:
                sudo([
                    "nsenter", f"--mount=/proc/{pid}/ns/mnt", "--",
                    "/bin/mount", "--bind", str(REMOTE_CACERTS_DIR), str(APEX_CACERTS_DIR),
                ])

    # some devices appear to have both (and multiple) instances!
    zygote_pids = pids_of("zygote")
    zygote_pids.extend(pids_of("zygote64"))

    for zygote_pid in zygote_pids:
        logging.info(f"[*] found zygote proccess with pid {zygote_pid}. Inject certificates to them and all childs")
        reload_zygote_and_childs(zygote_pid)
    
    logging.info(f"[+] runtime certificate injection complete")


if __name__ == "__main__":
    main()