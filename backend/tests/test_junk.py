"""잡동사니 판별 룰 단위테스트 (정리 마법사 Phase 1)."""

from app.organize.junk import classify


def test_screenshot_prefixes():
    assert classify("Screenshot_20240101-101112.jpg") == "screenshot"
    assert classify("스크린샷 2024-01-01.jpg") == "screenshot"
    assert classify("SCR_20240101.jpg") == "screenshot"


def test_png_counts_as_screenshot():
    # 카메라 원본은 PNG가 아니다 — 캡처/저장 이미지로 취급.
    assert classify("image.PNG") == "screenshot"
    assert classify("다운로드.png") == "screenshot"


def test_messenger_prefixes():
    assert classify("KakaoTalk_20240101_101112.jpg") == "messenger"
    assert classify("FB_IMG_123.jpg") == "messenger"
    assert classify("Received_9876.jpeg") == "messenger"


def test_camera_originals_pass():
    assert classify("20240101_101112.jpg") is None
    assert classify("IMG_1234.JPG") is None
    assert classify("DSC00042.jpg") is None
    assert classify("1745752158000.jpg") is None  # ms-epoch 저장본도 v1은 보존


def test_nested_path_uses_basename():
    assert classify("/homes/u/Photos/2024-01/Screenshot_1.jpg") == "screenshot"
