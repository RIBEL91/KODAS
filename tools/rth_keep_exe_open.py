# PyInstaller 시작 훅: 켜 둔 앱이 exe 파일을 계속 읽게 한다.
#
# 한 파일(onefile) exe는 처음 쓰는 파이썬 모듈을 그때그때 'exe 파일 이름'으로 다시 열어 꺼낸다.
# 앱을 켜 둔 채 새 버전으로 빌드하면(옛 exe는 .old로 이름만 바뀜) 같은 이름의 '새' exe에서 옛 위치를 읽게 되어
# "Error -3 while decompressing data: incorrect header check"로 작업이 실패한다.
# 그래서 켤 때 exe를 한 번 열어 두고(이름 바꾸기·지우기는 막지 않게 FILE_SHARE_DELETE) 그 핸들에서만 읽는다.
def _keep_exe_open():
    import ctypes
    import marshal
    import msvcrt
    import os
    import sys
    import threading
    import zlib
    from ctypes import wintypes

    import pyimod01_archive as pa
    import pyimod02_importers as pim

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    reader = getattr(pim, "pyz_archive", None)        # 부트로더가 만든 읽기 장치(exe 경로·위치를 안다)
    fn = getattr(reader, "_filename", "")
    if not fn or not os.path.isfile(fn):
        return
    # GENERIC_READ, 읽기·쓰기·지우기(이름 바꾸기) 모두 허용, OPEN_EXISTING
    h = k32.CreateFileW(fn, 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)
    if not h or h == ctypes.c_void_p(-1).value:
        return
    fp = os.fdopen(msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY), "rb")
    files = {os.path.normcase(fn): fp}
    lock = threading.Lock()
    orig = pa.ZlibArchiveReader.extract

    def extract(self, name, raw=False):
        f = files.get(os.path.normcase(self._filename))
        entry = self.toc.get(name)
        if f is None or entry is None:
            return orig(self, name, raw)
        typecode, offset, length = entry
        if typecode == pa.PYZ_ITEM_NSPKG:
            return None
        with lock:
            f.seek(self._start_offset + offset)
            obj = f.read(length)
        try:
            obj = zlib.decompress(obj)
            if typecode in (pa.PYZ_ITEM_MODULE, pa.PYZ_ITEM_PKG) and not raw:
                obj = marshal.loads(obj)
        except EOFError as e:
            raise ImportError(f"Failed to unmarshal PYZ entry {name!r}!") from e
        return obj

    pa.ZlibArchiveReader.extract = extract


try:
    _keep_exe_open()
except Exception:      # 실패해도 예전처럼 돈다
    pass
