"""
PLI フォントスケール設定（共有モジュール）
attorney_window / defendant_window 両方から参照
"""
import os

# グローバルフォントスケール
font_scale: float = 1.0

# 起動時に保存値を復元
_fs_path = os.path.expanduser("~/pli-models/font_scale.txt")
if os.path.exists(_fs_path):
    try:
        font_scale = float(open(_fs_path).read().strip())
    except (ValueError, OSError):
        pass


def fs(base_px: int) -> str:
    """フォントサイズをスケール適用してCSS値を返す"""
    return f"{max(8, int(base_px * font_scale))}px"


def set_scale(scale: float):
    """スケール変更 + ファイル保存"""
    global font_scale
    font_scale = scale
    config_dir = os.path.expanduser("~/pli-models")
    os.makedirs(config_dir, exist_ok=True)
    try:
        with open(os.path.join(config_dir, "font_scale.txt"), "w") as f:
            f.write(str(scale))
    except OSError:
        pass
