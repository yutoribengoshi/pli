"""PLI バージョン定義（単一ソース）

main.py と ui/attorney_window.py の双方から参照する。
main → ui → core の一方向依存を保つため core/ 配下に置く
（attorney_window が main を import すると循環になる）。
リリース時はここと pyproject.toml の version を更新する。
"""

__version__ = "2.0.0"
