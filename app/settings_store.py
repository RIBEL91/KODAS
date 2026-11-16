"""사용자 설정 저장 (%APPDATA%\\공문작성기\\settings.json).

계정은 '기억하기'를 고른 경우에만 저장하며, app_config의 머신 종속 암호화
(MachineGuid 파생 키)로 암호화한다. 다른 PC로 옮기면 복호화되지 않는다.
"""
import json
import os
import tempfile

from paths import user_dir

SECRET_KEYS = ("vpn_id", "vpn_pw", "homnet_id", "homnet_pw")
PATH = os.path.join(user_dir(), "settings.json")


def _crypto():
    from app_config import decrypt, encrypt
    return encrypt, decrypt


def load_raw() -> dict:
    """설정 파일을 그대로 읽는다(계정은 암호화된 채). 없거나 깨졌으면 빈 dict."""
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def set_value(key: str, value) -> None:
    """설정 한 항목만 바꿔 저장한다(계정 등 다른 항목은 그대로)."""
    data = load_raw()
    data[key] = value
    _write(data)


def load() -> dict:
    """설정을 읽는다. 없거나 깨졌으면 빈 dict (계정 복호화 실패도 빈 값)."""
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    _, decrypt = _crypto()
    for key in SECRET_KEYS:
        if data.get(key):
            try:
                data[key] = decrypt(data[key])
            except Exception:
                data[key] = ""
    return data


def save(values: dict, remember_accounts: bool) -> None:
    """설정을 저장한다. remember_accounts가 False면 계정 항목은 지운다."""
    encrypt, _ = _crypto()
    data = dict(values)
    for key in SECRET_KEYS:
        v = (data.get(key) or "").strip() if remember_accounts else ""
        if v:
            data[key] = encrypt(v)
        else:
            data.pop(key, None)
    data["remember"] = remember_accounts
    _write(data)


def clear() -> None:
    """저장된 계정을 지운다(담당자가 바뀔 때). 기본정보는 남긴다."""
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        data = {}
    for key in SECRET_KEYS:
        data.pop(key, None)
    data["remember"] = False
    _write(data)


def _write(data: dict) -> None:
    """임시 파일에 쓰고 바꿔치기해, 쓰다가 끊겨도 기존 파일이 깨지지 않게 한다."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(PATH), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
