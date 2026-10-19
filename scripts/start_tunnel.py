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

# =============== 📦 安装依赖 ===============
def install_dependencies() -> None:
    """安装所有必要的依赖"""
    try:
        print("📦 安装 pip 依赖库...")
        pip_packages = [
            "google-auth-oauthlib",
            "google-api-python-client"
        ]
        subprocess.check_call(["pip3", "install", *pip_packages])
        print("✅ pip 依赖安装完成")

        print("📥 下载并安装 age (v1.3.2)...")
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
        print("✅ age 安装完成")

        print("📥 安装 rclone...")
        subprocess.run(
            "curl -fsSL https://rclone.org/install.sh | sudo bash",
            shell=True,
            executable="/bin/bash",
            check=True,
        )
        print("✅ rclone 安装完成")
    except Exception as e:
        raise RuntimeError(f"❌ 依赖安装失败: {e}")

# =============== 🔧 配置与挂载 ===============
def setup_rclone_config() -> None:
    """设置 rclone 配置"""
    try:
        rclone_secret = os.getenv("RCLONE_SECRET_DATA")
        if not rclone_secret:
            raise RuntimeError("❌ RCLONE_SECRET_DATA 环境变量未设置")
        
        conf_dir = os.path.expanduser("~/.config/rclone")
        os.makedirs(conf_dir, exist_ok=True)
        conf_path = os.path.join(conf_dir, "rclone.conf")
        
        with open(conf_path, "w", encoding="utf-8") as f:
            f.write(rclone_secret)
        
        print(f"✅ rclone 配置已写入: {conf_path}")
    except Exception as e:
        raise RuntimeError(f"❌ rclone 配置失败: {e}")

def mount_remote_command() -> None:
    """挂载网盘"""
    try:
        mount_point = pathlib.Path(CONFIG.MOUNT_POINT)
        mount_point.mkdir(parents=True, exist_ok=True)
        log_file = pathlib.Path("/tmp/rclone-command.log")
        
        cmd = [
            "rclone",
            "mount",
            CONFIG.RCLONE_REMOTE_PATH,
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
                    f"{CONFIG.RCLONE_REMOTE_PATH} → {mount_point}"
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
    except Exception as e:
        raise RuntimeError(f"❌ 挂载失败: {e}")

def decrypt_and_extract_ls() -> pathlib.Path:
    """解密并解压文件"""
    age_private_key = None
    key_file = None
    
    try:
        age_private_key = os.getenv("AGE_PRIVATE_KEY")
        if not age_private_key:
            raise RuntimeError("❌ AGE_PRIVATE_KEY 环境变量未设置")
        
        encrypted_archive = pathlib.Path(CONFIG.LS_ARCHIVE)
        extract_dir = pathlib.Path(CONFIG.LS_EXTRACT_DIR)

        if not encrypted_archive.is_file():
            raise FileNotFoundError(
                f"❌ 找不到加密文件: {encrypted_archive}"
            )
        
        # 清理上一次的解压内容
        if extract_dir.exists():
            print(f"🧹 删除旧目录: {extract_dir}")
            shutil.rmtree(extract_dir)
        
        extract_dir.mkdir(parents=True, exist_ok=True)
        
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
        
        # 创建 age 进程
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
        
        # 创建 tar 进程
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
        
        # 关闭 age 进程的 stdout,以便 tar 进程可以读取
        if age_process.stdout is not None:
            age_process.stdout.close()
        
        _, tar_stderr = tar_process.communicate()
        age_stderr = (
            age_process.stderr.read()
            if age_process.stderr
            else b""
        )
        age_return_code = age_process.wait()
        
        # 检查 age 是否成功
        if age_return_code != 0:
            error = age_stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
            raise RuntimeError(
                f"❌ age 解密失败,返回码: "
                f"{age_return_code}\n{error}"
            )
        
        # 检查 tar 是否成功
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
    
    except Exception as e:
        raise RuntimeError(f"❌ 解密解压失败: {e}")
    
    finally:
        # 删除临时密钥文件
        if key_file is not None:
            try:
                key_file.unlink(missing_ok=True)
            except Exception as e:
                print(f"⚠️ 删除临时密钥文件失败: {e}")

# =============== 📋 主程序 ===============
def main() -> None:
    """执行所有步骤"""
    extract_dir = None
    
    try:
        print("[1/6] 安装依赖...")
        install_dependencies()

        print("[2/6] 设置 rclone 配置...")
        setup_rclone_config()

        print("[3/6] 挂载网盘目录 remote:/Command 到 /tmp/Command ...")
        mount_remote_command()

        print("[4/6] 解密并解压 start_docker.tar.xz.age...")
        extract_dir = decrypt_and_extract_ls()

        print("[5/6] 列出挂载目录内容...")
        ls_res = run(f"ls -al {extract_dir}", capture=True)
        print(ls_res.stdout)

        print("[6/6] 执行解压出来的 start_docker 命令...")
        command_path = pathlib.Path(extract_dir) / "start_docker"
        
        if not command_path.exists():
            raise FileNotFoundError(f"❌ 找不到命令文件: {command_path}")
        
        os.chmod(command_path, 0o755)
        subprocess.run([str(command_path)], check=True)
        
        print("✅ 所有步骤执行成功!")
    
    except FileNotFoundError as e:
        print(f"❌ 文件未找到: {e}", file=sys.stderr)
        sys.exit(1)
    
    except RuntimeError as e:
        print(f"❌ 运行时错误: {e}", file=sys.stderr)
        sys.exit(1)
    
    except subprocess.CalledProcessError as e:
        print(f"❌ 子进程执行失败: {e}", file=sys.stderr)
        sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断执行", file=sys.stderr)
        sys.exit(130)
    
    except Exception as e:
        print(f"❌ 未预期的错误: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
