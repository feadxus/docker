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
    LS_EXTRACT_DIR = "/tmp/ls_test"
    LS_ARCHIVE = f"{MOUNT_POINT}/ls.tar.xz.age"
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
    ]
    print("执行命令:", " ".join(cmd))
    # 这里使用前台运行方式，便于直接看到错误
    subprocess.Popen(cmd)
    for _ in range(30):
        time.sleep(1)
        result = subprocess.run(
            ["mountpoint", "-q", str(mount_point)],
            check=False,
        )
        if result.returncode == 0:
            print(
                f"✅ 已挂载 {Config.RCLONE_REMOTE_PATH}"
                f" → {mount_point}"
            )
            return
    raise RuntimeError(
        f"挂载超时，{mount_point} 不是有效挂载点"
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
                f"❌ age 解密失败，返回码: "
                f"{age_return_code}\n{error}"
            )
        if tar_process.returncode != 0:
            error = tar_stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            raise RuntimeError(
                f"❌ tar 解压失败，返回码: "
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
        # 设置 rclone
        print("[1/4] 设置 rclone 配置...")
        setup_rclone_config()

        # 挂载网盘
        print("[2/4] 挂载 remote:/Command 到 /tmp/Command ...")
        mount_remote_command()

        print("[4/4] 解密并解压 ls.tar.xz.age...")
        extract_dir = decrypt_and_extract_ls()

        # 列出挂载目录内容
        ls_res = run("ls -al /tmp/Command", capture=True)

        print(f"\n📂 {Config.MOUNT_POINT} 内容：")
        print(ls_res.stdout)

        print("[4/4] 解密并解压 ls.tar.xz.age...")
        decrypt_and_extract_ls()

        # 固定执行路径
        ls_path = extract_dir / "ls"

        if not ls_path.is_file():
            raise RuntimeError(
                f"❌ 解压后找不到可执行文件: {ls_path}"
            )

        # 增加执行权限
        current_mode = ls_path.stat().st_mode
        os.chmod(ls_path, current_mode | 0o700)

        print(f"✅ 找到文件: {ls_path}")
        print("▶️ 开始测试执行...")

        test_result = subprocess.run(
            [str(ls_path), "--version"],
            cwd=str(extract_dir),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        output = (
            test_result.stdout.strip()
            or test_result.stderr.strip()
        )

        if test_result.returncode != 0:
            raise RuntimeError(
                "❌ ls 执行失败\n"
                f"返回码: {test_result.returncode}\n"
                f"输出:\n{output}"
            )

        print("✅ ls 执行成功")
        print(f"📄 输出:\n{output}")
        print("\n🎉 解密、解压和执行测试全部成功")

    except Exception as e:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now_str}] ❌ 错误: {e}")
        sys.exit(1)

    finally:
        # 测试结束后删除固定解压目录
        if extract_dir.exists():
            print(f"🧹 删除解压目录: {extract_dir}")
            shutil.rmtree(extract_dir, ignore_errors=True)

if __name__ == "__main__":
    main()
