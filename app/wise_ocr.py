"""Windows 내장 OCR(한국어)로 화면 글자와 위치를 읽는다. 편리한 임대업무 앱의 ocr.py에서 가져왔다."""
import asyncio
from dataclasses import dataclass

from PIL import Image, ImageGrab


@dataclass
class Word:
    text: str
    x: int      # 화면 좌표(가운데)
    y: int
    left: int
    top: int
    right: int
    bottom: int


@dataclass
class Line:
    text: str
    words: list

    @property
    def x(self):
        return (self.words[0].left + self.words[-1].right) // 2

    @property
    def y(self):
        return sum(w.y for w in self.words) // len(self.words)

    @property
    def left(self):
        return self.words[0].left

    @property
    def right(self):
        return self.words[-1].right


async def _recognize(img: Image.Image):
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap, BitmapAlphaMode
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    rgba = img.convert("RGBA")
    # SoftwareBitmap은 BGRA8을 받는다
    r, g, b, a = rgba.split()
    data = Image.merge("RGBA", (b, g, r, a)).tobytes()
    writer = DataWriter()
    writer.write_bytes(data)
    buf = writer.detach_buffer()
    bmp = SoftwareBitmap.create_copy_from_buffer(buf, BitmapPixelFormat.BGRA8, rgba.width, rgba.height,
                                                BitmapAlphaMode.PREMULTIPLIED)
    engine = OcrEngine.try_create_from_language(Language("ko"))
    if engine is None:
        raise RuntimeError("한국어 OCR을 쓸 수 없습니다(Windows 설정 → 언어에서 한국어 OCR 설치).")
    return await engine.recognize_async(bmp)


def read(box: tuple[int, int, int, int], scale: float = 2.0) -> list[Line]:
    """화면 box(left, top, right, bottom) 안의 글자 줄. 작은 글씨를 잘 읽게 확대해서 읽는다."""
    img = ImageGrab.grab(bbox=box, all_screens=True)
    if scale != 1:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    res = asyncio.run(_recognize(img))
    out = []
    for ln in res.lines:
        words = []
        for w in ln.words:
            r = w.bounding_rect
            left = box[0] + int(r.x / scale)
            top = box[1] + int(r.y / scale)
            right = box[0] + int((r.x + r.width) / scale)
            bottom = box[1] + int((r.y + r.height) / scale)
            words.append(Word(w.text, (left + right) // 2, (top + bottom) // 2, left, top, right, bottom))
        if words:
            out.append(Line(" ".join(w.text for w in words), words))
    return out


def compact(s: str) -> str:
    return "".join(s.split())
