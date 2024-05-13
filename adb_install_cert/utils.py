import logging
import subprocess
import typing
from contextlib import contextmanager
from adbutils._utils import adb_path
from pathlib import Path
from adbutils import AdbDevice, AdbError


def convert_der_to_pem(der_cert_filename: Path, out_pem_filename: Path):
    _openssl_x509(str(der_cert_filename), "DER", "-out", out_pem_filename)


def convert_pem_to_pem(pem_cert_filename: Path, out_pem_filename: Path):
    _openssl_x509(str(pem_cert_filename), "PEM", "-out", out_pem_filename)


def prepare_pem(pem_cert_filename: Path, out_dir_path: Path) -> Path:
    pem_filename = get_pem_info(pem_cert_filename, fields=["-subject_hash_old"]).strip() + ".0"
    pem_cert_contet = get_pem_content(pem_cert_filename)
    pem_additional_content = get_pem_info(pem_cert_filename, fields=["-text", "-fingerprint"])
    pem_out_path = out_dir_path / pem_filename
    with pem_out_path.open(mode="w") as pem_out:
        pem_out.writelines([pem_cert_contet, pem_additional_content])
    return pem_out_path


def get_pem_info(pem_cert_filename: Path, fields: typing.List[str] = []):
    return _openssl_x509(pem_cert_filename, "PEM", "-noout", *fields)


def get_pem_content(cert_filename: Path) -> str:
    return _openssl_x509(cert_filename, "PEM")


def _openssl_x509(cert_filename: Path, inform: str, *args: typing.List[str]) -> str:
    cert_proc_result = subprocess.run(
        [
            "openssl", "x509", "-inform", inform,
            *args,
            "-in", str(cert_filename)
        ],
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
    def perform_command_as_root(cmd: typing.List[str], check_error=True):
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
            stdin, stderr = root_sh.communicate(cmd + ";\necho $?;")

            output_lines = stdin.splitlines()
            exit_code = int(output_lines[-1])

            if check_error and exit_code != 0:
                raise AdbError(f"command exit with error (exit_code: {exit_code})\nstderr: {stderr}")

            return stdin, stderr
    yield perform_command_as_root


def list2cmdline(args: typing.List[str]):
    return " ".join(args)


def device_is_rooted(device: AdbDevice) -> bool:
    return len(device.shell(["which", "su"]).strip()) > 0


def get_android_version(device: AdbDevice) -> int:
    release = device.prop.get("ro.build.version.release").split(".")
    return int(release[0])


def apex_is_present(device: AdbDevice) -> bool:
    return device.shell2(["stat", "/apex"]).returncode == 0