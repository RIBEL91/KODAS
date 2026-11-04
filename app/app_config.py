"""실행 경로 판별, 머신 종속 암호화, config.json 영속화를 담당한다.

암호화 키는 이 PC의 MachineGuid에서 파생된다. 키 파일을 따로 두지 않는 대신
config.json은 다른 PC로 옮기면 복호화되지 않는다. 의도된 제약이다.

설정 파일을 읽지 못했을 때 빈 값으로 간주하고 넘어가면, 이어지는 저장이
파일을 통째로 덮어써 저장된 계정이 사라진다. 그래서 '파일 없음'과
'읽기 실패'를 구분해 후자는 ConfigError로 올린다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
import winreg

from cryptography.fernet import Fernet, InvalidToken

__all__ = [
    "APPLICATION_PATH",
    "CONFIG_FILE",
    "CREDENTIAL_KEYS",
    "ConfigError",
    "ConfigStore",
    "InvalidToken",
    "resource_path",
]

# config.json의 credentials에 들어가는 필드. 전부 암호화해 저장한다.
CREDENTIAL_KEYS = ("lh_id", "lh_pw", "kohom_id", "kohom_pw")

_REGISTRY_PATH = r"SOFTWARE\Microsoft\Cryptography"
_FALLBACK_GUID = "fallback_default_guid_for_vpn_helper"


def _resolve_application_path() -> str:
    """PyInstaller exe와 소스 실행 양쪽에서 '프로그램이 놓인 폴더'를 돌려준다."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APPLICATION_PATH = _resolve_application_path()
CONFIG_FILE = os.path.join(APPLICATION_PATH, "config.json")


def resource_path(name: str) -> str:
    """번들에 함께 묶인 리소스(아이콘 등)의 경로.

    APPLICATION_PATH와 다르다. onefile exe는 실행할 때마다 리소스를 임시
    폴더에 풀고 그 경로를 sys._MEIPASS에 넣는다. 설정 파일처럼 사용자가
    보관해야 하는 파일에는 쓰지 않는다.
    """
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def _build_machine_key() -> bytes:
    """하드웨어 고유 ID를 기반으로 Fernet 키를 만든다 (키 파일 저장 불필요)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REGISTRY_PATH) as key:
            machine_guid = winreg.QueryValueEx(key, "MachineGuid")[0]
    except OSError:
        machine_guid = _FALLBACK_GUID

    key_hash = hashlib.sha256(machine_guid.encode()).digest()
    return base64.urlsafe_b64encode(key_hash)


_cipher = Fernet(_build_machine_key())


def encrypt(value: str) -> str:
    return _cipher.encrypt(value.encode()).decode("utf-8")


def decrypt(token: str) -> str:
    return _cipher.decrypt(token.encode("utf-8")).decode()


class ConfigError(Exception):
    """설정 파일을 신뢰할 수 없는 상태. 이 경우 절대 덮어쓰지 않는다."""


class ConfigStore:
    """계정 정보와 화면 설정을 담은 config.json 하나를 읽고 쓴다."""

    def __init__(self, path: str = CONFIG_FILE) -> None:
        self.path = path

    # --- 파일 단위 입출력 ---

    def load(self) -> dict:
        """설정 전체를 읽는다.

        파일이 아직 없으면 빈 구조를 돌려주고, 있는데 읽지 못하면 ConfigError를
        올린다. 호출부가 이 둘을 구분해야 계정 정보를 잃지 않는다.
        """
        if not os.path.exists(self.path):
            return {"credentials": {}, "settings": {}}

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"설정 파일을 읽을 수 없습니다: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigError("설정 파일 형식이 올바르지 않습니다.")

        data.setdefault("credentials", {})
        data.setdefault("settings", {})
        return data

    def save(self, data: dict) -> None:
        """임시 파일에 쓴 뒤 교체한다. 쓰다가 중단돼도 기존 파일이 남는다."""
        directory = os.path.dirname(self.path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp_path, self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # --- 계정 정보 ---

    def has_credentials(self) -> bool:
        return any(self.load().get("credentials", {}).get(key) for key in CREDENTIAL_KEYS)

    def load_credentials(self) -> dict[str, str]:
        """복호화된 계정 정보를 돌려준다. 복호화 실패 시 InvalidToken이 올라온다."""
        stored = self.load().get("credentials", {})
        return {key: decrypt(stored[key]) for key in CREDENTIAL_KEYS if stored.get(key)}

    def save_credentials(self, values: dict[str, str]) -> None:
        """입력된 값만 암호화해 저장하고, 빈 값은 항목 자체를 지운다."""
        data = self.load()
        credentials = data.setdefault("credentials", {})

        for key in CREDENTIAL_KEYS:
            value = (values.get(key) or "").strip()
            if value:
                credentials[key] = encrypt(value)
            else:
                credentials.pop(key, None)

        self.save(data)

    # --- 화면 설정(체크박스) ---

    def load_settings(self) -> dict:
        return self.load().get("settings", {})

    def update_settings(self, settings: dict) -> None:
        data = self.load()
        data.setdefault("settings", {}).update(settings)
        self.save(data)
