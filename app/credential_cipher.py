"""凭据加密模块(借鉴 ZCode credential-cipher.ts 的设计)

- 算法: AES-256-GCM,密文格式 "enc:v1:<iv_b64>.<auth_tag_b64>.<ciphertext_b64>"
- 密钥: 优先取环境变量 TESTASSISTANT_CREDENTIAL_SECRET;否则由机器绑定信息
  (主机名/平台/用户名/安装路径)派生 —— 数据文件被拷到其他机器后密文自动失效
- 兼容: 未带 enc:v1: 前缀的值视为历史明文,decrypt 原样返回(读旧库不炸),
  写入路径统一走 encrypt 完成惰性迁移
"""
import base64
import hashlib
import os
import platform
import socket


from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_ENCRYPTED_PREFIX = "enc:v1:"
_IV_BYTES = 12
_SECRET_ENV_KEY = "TESTASSISTANT_CREDENTIAL_SECRET"


def _derive_machine_secret() -> str:
    """由机器绑定信息派生密钥材料(与 ZCode homedir/platform/userInfo 思路一致)。
    注意:不能包含 sys.executable/安装路径等随部署形态变化的量,否则同一台机器
    上"容器加密→exe 解密"或"升级后解密"都会失败。"""
    parts = [
        platform.system(),
        platform.machine(),
        platform.node() or socket.gethostname(),
        os.path.expanduser("~"),
    ]
    return "|".join(parts)


def _resolve_secret_key() -> bytes:
    material = os.getenv(_SECRET_ENV_KEY, "").strip() or _derive_machine_secret()
    return hashlib.sha256(material.encode("utf-8")).digest()


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(_ENCRYPTED_PREFIX)


def encrypt_credential(plain: str) -> str:
    """加密凭据;空值原样返回"""
    if not plain or is_encrypted(plain):
        return plain
    key = _resolve_secret_key()
    iv = os.urandom(_IV_BYTES)
    cipher_text = AESGCM(key).encrypt(iv, plain.encode("utf-8"), None)
    auth_tag, body = cipher_text[-16:], cipher_text[:-16]
    b64 = base64.urlsafe_b64encode
    return _ENCRYPTED_PREFIX + ".".join([
        b64(iv).decode(),
        b64(auth_tag).decode(),
        b64(body).decode(),
    ])


def decrypt_credential(value: str) -> str:
    """解密凭据;未加密(历史明文)原样返回,损坏密文抛异常由调用方兜底"""
    if not is_encrypted(value):
        return value
    try:
        key = _resolve_secret_key()
        iv_raw, tag_raw, body_raw = value[len(_ENCRYPTED_PREFIX):].split(".")
        iv = base64.urlsafe_b64decode(iv_raw)
        body = base64.urlsafe_b64decode(body_raw) + base64.urlsafe_b64decode(tag_raw)
        return AESGCM(key).decrypt(iv, body, None).decode("utf-8")
    except Exception as e:
        raise ValueError(
            "凭据解密失败:密文来自其他机器或已损坏。"
            "请到模型管理重新保存 API Key,或设置 TESTASSISTANT_CREDENTIAL_SECRET 后重试。"
        ) from e
