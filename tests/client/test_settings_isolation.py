"""守卫：测试套件绝不触碰真实注册表。"""
import re
from pathlib import Path


def test_injected_settings_lands_in_tmp_ini(make_settings):
    s = make_settings(token="t")
    s.save()
    fn = str(Path(s.qs.fileName()))
    assert fn.endswith(".ini") and "settings.ini" in fn


def test_no_bare_appsettings_calls_in_tests():
    """结构守卫：tests/ 下禁止不带 qs 参数的 AppSettings 构造（会用真实注册表）。"""
    tests_dir = Path(__file__).parents[1]
    pattern = re.compile(r"AppSettings\(\s*\)")
    offenders = []
    for py in tests_dir.rglob("test_*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{py.relative_to(tests_dir)}:{i}: {line.strip()}")
    assert not offenders, "测试使用了真实注册表（改用 make_settings 注入 INI）:\n" + "\n".join(offenders)
