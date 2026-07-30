"""运行所有单元测试的便捷脚本."""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = [
    "test_matcher",
    "test_sources",
    "test_player",
    # "test_api",  # 需要 fastapi + httpx + pytest
]


def main() -> int:
    failed = 0
    for name in TESTS:
        print(f"\n=== {name} ===")
        mod = importlib.import_module(f"tests.{name}")
        # 调用模块的 main() (各 test 文件内置 runner)
        if hasattr(mod, "main"):
            rc = mod.main()
            if rc:
                failed += 1
    print(f"\n{'=' * 40}\n  done; failed_modules={failed}\n{'=' * 40}")
    return failed


if __name__ == "__main__":
    sys.exit(main())
