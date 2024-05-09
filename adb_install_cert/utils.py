import logging
import os
import subprocess
import typing
from contextlib import contextmanager
from adbutils._utils import adb_path
from pathlib import Path
from adbutils import AdbDevice


def prepare_pem(pem_cert_filename: Path, out_dir_path: Path) -> Path:
    pem_filename = get_pem_info(pem_cert_filename, fields=["-subject_hash_old"]).strip() + ".0"
    pem_cert_contet = get_pem_info(pem_cert_filename, keep_cert = True)
    pem_additional_content = get_pem_info(pem_cert_filename, fields=["-text", "-fingerprint"])
    pem_out_path = out_dir_path / pem_filename
    with pem_out_path.open(mode="w") as pem_out:
        pem_out.writelines([pem_cert_contet, pem_additional_content])
    return pem_out_path


def get_pem_info(pem_cert_filename: Path, fields: typing.List[str] = [], keep_cert: bool = False):
    keep_cert = [] if keep_cert else ["-noout"]
    cert_proc_result = subprocess.run(
        [
            "openssl", "x509", "-inform", "PEM",
            *fields, *keep_cert,
            "-in", str(pem_cert_filename)],
        capture_output=True, text=True, check=True
    )
    return cert_proc_result.stdout


# @contextmanager
# def open_root_shell(device: AdbDevice):
#     root_sh_cmd = [adb_path(), "-s", device.serial] if device.serial else [adb_path()]
#     root_sh_cmd.extend(["shell", "su"])
#     with subprocess.Popen(
#         root_sh_cmd,
#         stdout=subprocess.PIPE,
#         stderr=subprocess.PIPE,
#         stdin=subprocess.PIPE,
#         text=True,
#         bufsize=1
#     ) as root_sh:
#         os.set_blocking(root_sh.stdout.fileno(), False)
#         os.set_blocking(root_sh.stderr.fileno(), False)
#         def perform_command_as_root(cmd: typing.List[str]):
#             cmd = list2cmdline(cmd)

#             logging.debug(f"perform_command_as_root: {cmd}")
#             root_sh.stdin.write(cmd + "\n")
#             root_sh.stdin.flush()

#             stdout = root_sh.stdout.readlines() 
#             stderr = root_sh.stderr.readlines()
#             print(stdout, stderr)

#             return stdout, stderr

#         yield perform_command_as_root

@contextmanager
def open_root_shell(device):
    def perform_command_as_root(cmd: typing.List[str]):
        root_sh_cmd = [adb_path(), "-s", device.serial] if device.serial else [adb_path()]
        root_sh_cmd.extend(["shell", "su"])
        with subprocess.Popen(
            root_sh_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1
        ) as root_sh:
            cmd = list2cmdline(cmd)
            logging.debug(f"perform_command_as_root: {cmd}")
            stdin, stderr = root_sh.communicate(cmd)
            return stdin, stderr
    yield perform_command_as_root


def list2cmdline(args: typing.List[str]):
    return " ".join(args)


def device_is_rooted(device: AdbDevice) -> bool:
    return len(device.shell(["which", "su"]).strip()) > 0


def get_android_version(device: AdbDevice) -> int:
    return int(device.prop.get("ro.build.version.release"))