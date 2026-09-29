#!/usr/bin/env python3

import os
import sys
import time
import shutil
import pathlib
import tarfile
import tempfile
import subprocess
import urllib.request
from datetime import datetime

# =============== 🛠️ 工具函数 ===============
def run(cmd: str, cwd: str = None, capture: bool = False) -> subprocess.CompletedProcess:
    """执行 shell 命令的通用函数"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            executable="/bin/bash",
            cwd=cwd,
            capture_output=capture,
            text=True,
            check=True
        )
        return result
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"命令执行失败: {cmd}\n{e.stderr}")

# =============== ⚙️ 配置类 ===============
class Config:
    # 在 rclone 配置文件中使用的远程名称
    RCLONE_REMOTE = "FEADXUS-Google-Drive"
    # 挂载此目录
    RCLONE_REMOTE_PATH = f"{RCLONE_REMOTE}:/Command/"

    MOUNT_POINT = "/tmp/Command"
    LS_EXTRACT_DIR = "/tmp/test"
    LS_ARCHIVE = f"{MOUNT_POINT}/start_docker.tar.xz.age"
CONFIG = Config()

# =============== 📦 安装类 ===============
# 安装 pip 依赖库
pip_packages = [
    "google-auth-oauthlib",
    "google-api-python-client"
]
# ⚠️ 注意:不能使用 sys.executable,直接调用系统环境的 pip3
subprocess.check_call(["pip3", "install", *pip_packages])

# 下载并安装特定版本的 age (v1.3.2)
age_version = "v1.3.2"
url = f"https://github.com/FiloSottile/age/releases/download/{age_version}/age-{age_version}-linux-amd64.tar.gz"
tar_path = "/tmp/age.tar.gz"
extract_dir = "/tmp/age_bin"
urllib.request.urlretrieve(url, tar_path)
os.makedirs(extract_dir, exist_ok=True)
with tarfile.open(tar_path, "r:gz") as tar:
    tar.extractall(path=extract_dir)
src_dir = os.path.join(extract_dir, "age")
subprocess.check_call(["sudo", "cp", f"{src_dir}/age", f"{src_dir}/age-keygen", "/usr/local/bin/"])
subprocess.check_call(["sudo", "chmod", "+x", "/usr/local/bin/age", "/usr/local/bin/age-keygen"])

# 安装 Google Drive rclone 与 skopeo 工具
subprocess.run(
    "curl -fsSL https://rclone.org/install.sh | sudo bash",
    shell=True,
    executable="/bin/bash",
    check=True,
)
# 设置 rclone 配置
def setup_rclone_config() -> None:
    rclone_secret = os.getenv("RCLONE_SECRET_DATA")
    if not rclone_secret:
        raise RuntimeError("❌ RCLONE_SECRET_DATA 环境变量未设置")
    conf_dir = os.path.expanduser("~/.config/rclone")
    os.makedirs(conf_dir, exist_ok=True)
    conf_path = os.path.join(conf_dir, "rclone.conf")
    with open(conf_path, "w", encoding="utf-8") as f:
        f.write(rclone_secret)
    print(f"✅ rclone 配置已写入: {conf_path}")

# 挂载网盘
def mount_remote_command() -> None:
    mount_point = pathlib.Path(Config.MOUNT_POINT)
    mount_point.mkdir(parents=True, exist_ok=True)
    log_file = pathlib.Path("/tmp/rclone-command.log")
    cmd = [
        "rclone",
        "mount",
        Config.RCLONE_REMOTE_PATH,
        str(mount_point),
        "--config",
        os.path.expanduser("~/.config/rclone/rclone.conf"),
        "--vfs-cache-mode",
        "writes",
        "--log-level",
        "INFO",
        "--log-file",
        str(log_file),
    ]
    print("启动 rclone 后台挂载...")
    print(f"日志文件: {log_file}")
    with open(log_file, "w", encoding="utf-8") as log:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    # 等待挂载成功,同时检查 rclone 是否已经异常退出
    for _ in range(30):
        time.sleep(1)
        # rclone 已经退出,说明启动失败
        return_code = process.poll()
        if return_code is not None:
            log_content = ""

            if log_file.exists():
                log_content = log_file.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            raise RuntimeError(
                f"❌ rclone 启动失败,返回码: {return_code}\n"
                f"日志内容:\n{log_content}"
            )
        # 检查是否已经成为有效挂载点
        result = subprocess.run(
            ["mountpoint", "-q", str(mount_point)],
            check=False,
        )
        if result.returncode == 0:
            print(
                f"✅ 已后台挂载"
                f"{Config.RCLONE_REMOTE_PATH} → {mount_point}"
            )
            return
    # 等待超时
    process.terminate()
    log_content = ""
    if log_file.exists():
        log_content = log_file.read_text(
            encoding="utf-8",
            errors="replace",
        )
    raise RuntimeError(
        f"❌ 挂载超时: {mount_point}\n"
        f"rclone 日志:\n{log_content}"
    )

# 解密并解压文件并返回解压目录
def decrypt_and_extract_ls() -> pathlib.Path:
    age_private_key = os.getenv("AGE_PRIVATE_KEY")
    if not age_private_key:
        raise RuntimeError("❌ AGE_PRIVATE_KEY 环境变量未设置")
    encrypted_archive = pathlib.Path(Config.LS_ARCHIVE)
    extract_dir = pathlib.Path(Config.LS_EXTRACT_DIR)

    if not encrypted_archive.is_file():
        raise FileNotFoundError(
            f"❌ 找不到加密文件: {encrypted_archive}"
        )
    # 清理上一次的解压内容
    if extract_dir.exists():
        print(f"🧹 删除旧目录: {extract_dir}")
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    key_file = None
    try:
        # 创建临时密钥文件
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="age_key_",
            dir="/tmp",
            delete=False,
        ) as f:
            key_file = pathlib.Path(f.name)
            f.write(age_private_key)
            f.write("\n")
        os.chmod(key_file, 0o600)
        print(f"📦 加密文件: {encrypted_archive}")
        print(f"📂 解压目录: {extract_dir}")
        age_process = subprocess.Popen(
            [
                "age",
                "-d",
                "-i",
                str(key_file),
                str(encrypted_archive),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        tar_process = subprocess.Popen(
            [
                "tar",
                "-xJf",
                "-",
                "-C",
                str(extract_dir),
            ],
            stdin=age_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if age_process.stdout is not None:
            age_process.stdout.close()
        _, tar_stderr = tar_process.communicate()
        age_stderr = (
            age_process.stderr.read()
            if age_process.stderr
            else b""
        )
        age_return_code = age_process.wait()
        if age_return_code != 0:
            error = age_stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            raise RuntimeError(
                f"❌ age 解密失败,返回码: "
                f"{age_return_code}\n{error}"
            )
        if tar_process.returncode != 0:
            error = tar_stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            raise RuntimeError(
                f"❌ tar 解压失败,返回码: "
                f"{tar_process.returncode}\n{error}"
            )
        print("✅ age 解密成功")
        print("✅ tar 解压成功")
        return extract_dir
    finally:
        # 删除临时密钥文件
        if key_file is not None:
            key_file.unlink(missing_ok=True)

# 执行每个模块
def main() -> None:
    try:
        print("[1/4] 设置 rclone 配置...")
        setup_rclone_config()

        print("[2/4] 挂载网盘目录 remote:/Command 到 /tmp/Command ...")
        mount_remote_command()

        print("[4/4] 解密并解压 start_docker.tar.xz.age...")
        extract_dir = decrypt_and_extract_ls()

        print("[5/5] 列出挂载目录内容...")
        ls_res = run(f"ls -al {extract_dir}", capture=True)
        print(ls_res.stdout)

        print("[6/6] 执行解压出来的 start_docker 命令...")
        # 拼接地址
        command_path = extract_dir / "start_docker"
        # 增加执行权限
        os.chmod(command_path, 0o755)
        # 执行命令
        subprocess.run(
            [str(command_path)],
            check=True
        )
    except Exception as e:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now_str}] ❌ 错误: {e}")
        sys.exit(1)
    # 测试结束后删除固定解压目录
    finally:
        if extract_dir is not None and extract_dir.exists():
            print(f"🧹 删除解压目录: {extract_dir}")
            shutil.rmtree(extract_dir, ignore_errors=True)

if __name__ == "__main__":
    main()
