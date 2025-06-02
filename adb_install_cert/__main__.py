
import click
import logging

from adbutils import adb, AdbDevice
from tempfile import TemporaryDirectory
from pathlib import Path, PurePosixPath

from adb_install_cert.utils import \
    prepare_pem, open_root_shell, device_is_rooted, get_android_version, \
    convert_der_to_pem, convert_pem_to_pem


REMOTE_OUTPUT_DIR = PurePosixPath("/data/local/tmp")
REMOTE_TEMP_CACERTS_DIR = REMOTE_OUTPUT_DIR / "cacerts"
REMOTE_CACERTS_DIR = PurePosixPath("/system/etc/security/cacerts")
APEX_CACERTS_DIR = PurePosixPath("/apex/com.android.conscrypt/cacerts")

INFORM_AUTO = "auto"
INFORM_CONVERTS = {
    "pem": convert_pem_to_pem,
    "der": convert_der_to_pem,
}

MODE_AUTO = "auto"
MODE_PERMANENTLY = "permanently"
MODE_TEMPORARY = "temporary"
MODE_APEX_CONSCRYPT = "apex-temporary"


def main():
    adb_install_cert()


@click.command()
@click.option("--cert", "cert_filename", help="set path to certificate", required=True, type=click.Path(exists=True, file_okay=True, dir_okay=False, resolve_path=True))
@click.option(
    "--cert-format",
    help=f"set certificate format ({INFORM_AUTO} - automatic select format by file extension and fail if unknown)",
    type=click.Choice([INFORM_AUTO, *INFORM_CONVERTS.keys()]),
    default=INFORM_AUTO,
    show_default=True,
)
@click.option(
    "--mode",
    help=f"""
    set strategy of certificate installation:

    {MODE_AUTO} - automatic select installation method, based on android version

    {MODE_PERMANENTLY} - install certificate permanently to {REMOTE_CACERTS_DIR}.
    Work on Android 9 or older. On sdk `emulator` should work with `-writable-system` option

    {MODE_TEMPORARY} - install certificate temporary to {REMOTE_CACERTS_DIR}.  Work on Android 10 - 13

    {MODE_APEX_CONSCRYPT} - install certificate temporary to {APEX_CACERTS_DIR} and remount cert
    directory inside zygote child proccess namespaces. Work on Android 14 or newer
    
    \b
    """,
    type=click.Choice([MODE_AUTO, MODE_PERMANENTLY, MODE_TEMPORARY, MODE_APEX_CONSCRYPT]),
    default=MODE_AUTO,
    show_default=True,
)
@click.option("--device-serial", help="select device by serial", default=None)
@click.option("--verbose/--silent", help="display logs", is_flag=True, show_default=True, default=True)
@click.option("--clean-remote-temp/--no-clean-remote-temp", help="remove temporary files after complete installation", is_flag=True, show_default=True, default=True)
def adb_install_cert(cert_filename, cert_format, mode, device_serial, verbose, clean_remote_temp):
    logging.getLogger().setLevel(logging.INFO if verbose else logging.ERROR)

    device = adb.device(serial=device_serial)

    if not device_is_rooted(device):
        logging.critical(f"Root device required. Recheck connected device ${device}")
        exit(1)

    remote_prepared_certificate = prepare_and_push_certificate(device, Path(cert_filename), cert_format)

    {
        MODE_AUTO: run_mode_auto,
        MODE_PERMANENTLY: run_mode_permanently,
        MODE_TEMPORARY: run_mode_temporary,
        MODE_APEX_CONSCRYPT: run_mode_apex_conscrypt,
    }[mode](device, remote_prepared_certificate)

    if clean_remote_temp:
        with open_root_shell(device) as perform_as_root:
            perform_as_root(["rm", "-r", str(REMOTE_TEMP_CACERTS_DIR)], check_error=False)
            perform_as_root(["rm", "-r", str(remote_prepared_certificate)], check_error=False)
        logging.info("[+] clean temporary files")


def prepare_and_push_certificate(device: AdbDevice, cert_filename: Path, cert_format: str) -> Path:
    ext = cert_filename.suffix[1:] if cert_format == INFORM_AUTO else cert_format

    if ext not in INFORM_CONVERTS:
        logging.critical(f"Unknown certificate file extension {ext}. Specify format directly with --cert-format option")

    convert_func = INFORM_CONVERTS[ext]

    with TemporaryDirectory() as tmp_dir:
        converted_cert_filename = (Path(tmp_dir) / cert_filename.name).with_suffix(".pem")
        convert_func(cert_filename, converted_cert_filename)

        local_prepared_pem_filename = prepare_pem(converted_cert_filename, Path(tmp_dir))
        logging.info(f"[+] prepare certificate: ${local_prepared_pem_filename}")

        remote_prepared_pem_filename = REMOTE_OUTPUT_DIR / local_prepared_pem_filename.name
        device.sync.push(local_prepared_pem_filename, str(remote_prepared_pem_filename))
        logging.info(f"[+] push prepared certificate: ${local_prepared_pem_filename}")

    return remote_prepared_pem_filename


def run_mode_auto(device: AdbDevice, remote_pem: Path):
    android_version = get_android_version(device)
    logging.info(f"[*] detect android version {android_version}")

    if android_version <= 9:
        run_mode_permanently(device, remote_pem)
    
    if android_version >= 10 and android_version < 14:
        run_mode_temporary(device, remote_pem)

    if android_version >= 14:
        run_mode_apex_conscrypt(device, remote_pem)


def run_mode_permanently(device: AdbDevice, remote_cert: Path):
    logging.info("[*] perform mode pemanently")
    legacy_permanent_install_cert(device, remote_cert)


def run_mode_temporary(device: AdbDevice, remote_cert: Path):
    logging.info("[*] perform mode temporary")
    new_temporary_install_cert(device, REMOTE_CACERTS_DIR, remote_cert)


def run_mode_apex_conscrypt(device: AdbDevice, remote_cert: Path):
    logging.info("[*] perform mode apex-conscrypt")
    new_temporary_install_cert(device, APEX_CACERTS_DIR, remote_cert)
    reload_runtime_cert_store(device, remote_cert)


def legacy_permanent_install_cert(device: AdbDevice, remote_cert: Path):
    with open_root_shell(device) as sudo:
        # remount /system in read write mode
        sudo(["mount", "-o", "rw,remount,rw", "/system"])
        # copy certificate to system store
        sudo(["cp", str(remote_cert), str(REMOTE_CACERTS_DIR)])
        # fix permissions of certificate
        sudo(["chmod", "644",  str(REMOTE_CACERTS_DIR / remote_cert.name)])
        # revert remounting
        sudo(["mount", "-o", "ro,remount,ro", "/system"])
        logging.info("[+] permanent install complete")


def new_temporary_install_cert(device: AdbDevice, source_cacerts_dir: Path, remote_cert: Path):
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
        sudo(["cp", str(remote_cert), str(REMOTE_CACERTS_DIR)])
        # fix permissions of certificate
        sudo(["chmod", "644", str(REMOTE_CACERTS_DIR / remote_cert.name)])
        # fix selinux context labels
        sudo(["chcon", "u:object_r:system_file:s0", str(REMOTE_CACERTS_DIR / "*")])
        sudo(["chcon", "u:object_r:system_file:s0", str(REMOTE_CACERTS_DIR)])
        logging.info("[+] temporary install complete")


def reload_runtime_cert_store(device: AdbDevice, remote_cert: Path):
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
    
    logging.info("[+] runtime certificate injection complete")


if __name__ == "__main__":
    main()
