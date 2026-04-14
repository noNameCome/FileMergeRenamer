"""
아이콘 생성 스크립트 (빌드 전 자동 실행)
Pillow로 icon.ico 생성
"""
from PIL import Image, ImageDraw
import os


def draw_folder(draw, x, y, w, h, color):
    """폴더 모양 그리기"""
    tab_w = w * 0.4
    tab_h = h * 0.18
    # 탭 (위쪽 돌출 부분)
    draw.rounded_rectangle([x, y, x + tab_w, y + tab_h + 4], radius=3, fill=color)
    # 본체
    draw.rounded_rectangle([x, y + tab_h, x + w, y + h], radius=5, fill=color)


def create_icon():
    sizes = [256, 128, 64, 48, 32, 16]
    images = []

    for size in sizes:
        img   = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw  = ImageDraw.Draw(img)
        s     = size

        # ── 배경 원 ──────────────────────────────
        draw.ellipse([2, 2, s - 2, s - 2], fill=(21, 101, 192, 255))

        # ── 폴더 1 (왼쪽 위) ─────────────────────
        fw = int(s * 0.35)
        fh = int(s * 0.28)
        fx = int(s * 0.10)
        fy = int(s * 0.18)
        draw_folder(draw, fx, fy, fw, fh, (255, 255, 255, 220))

        # ── 폴더 2 (오른쪽 위) ───────────────────
        fx2 = int(s * 0.55)
        draw_folder(draw, fx2, fy, fw, fh, (255, 255, 255, 220))

        # ── 화살표 (아래 방향 ↓ 병합) ────────────
        cx  = s // 2
        ay1 = int(s * 0.48)
        ay2 = int(s * 0.60)
        aw  = max(2, int(s * 0.03))
        ah  = max(4, int(s * 0.06))

        # 화살표 줄기
        draw.rectangle([cx - aw, ay1, cx + aw, ay2], fill=(255, 235, 59, 255))
        # 화살표 머리
        pts = [
            (cx - ah * 2, ay2),
            (cx + ah * 2, ay2),
            (cx,          ay2 + ah * 2),
        ]
        draw.polygon(pts, fill=(255, 235, 59, 255))

        # ── 결과 폴더 (아래 중앙) ─────────────────
        rfw = int(s * 0.44)
        rfh = int(s * 0.22)
        rfx = (s - rfw) // 2
        rfy = int(s * 0.70)
        draw_folder(draw, rfx, rfy, rfw, rfh, (255, 255, 255, 255))

        images.append(img)

    # ICO 저장
    images[0].save(
        'icon.ico',
        format='ICO',
        sizes=[(sz, sz) for sz in sizes],
        append_images=images[1:]
    )
    print("icon.ico 생성 완료")


if __name__ == '__main__':
    create_icon()
