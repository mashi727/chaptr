"""更新時に落としてくる成果物の選び方

リリースには macOS の DMG が 2 つ（Intel / AppleSilicon）並ぶ。以前は `.dmg` の
**最初の1つ**を返していたので、Intel 機に arm64 版を渡すことがあり得た。そちらは
起動しないので、更新した瞬間にアプリが開かなくなる。

Windows は `.zip` を探していたが、CI が上げるのは `.exe`。一致することが無く、
更新機能が事実上死んでいた。

いずれも「最初に見つかったもの」で済ませたことによる欠陥で、成果物が1種類だった
頃には現れなかった。
"""

import pytest

from chaptr.ui.updater import UpdateChecker


VERSION = "v2.4.0"


def _assets(*names):
    return [{"name": n, "browser_download_url": f"https://example.invalid/{n}"}
            for n in names]


RELEASE = _assets(
    f"Chaptr-{VERSION}-macOS-Intel.dmg",
    f"Chaptr-{VERSION}-macOS-AppleSilicon.dmg",
    f"Chaptr-{VERSION}-Windows.exe",
)


@pytest.fixture
def checker():
    return UpdateChecker.__new__(UpdateChecker)


def _pick(checker, assets, system, machine, monkeypatch):
    monkeypatch.setattr("platform.system", lambda: system)
    monkeypatch.setattr("platform.machine", lambda: machine)
    return checker._get_download_url(assets)


class TestMacOS:
    def test_apple_silicon_gets_arm_build(self, checker, monkeypatch):
        url = _pick(checker, RELEASE, "Darwin", "arm64", monkeypatch)
        assert "AppleSilicon" in url

    def test_intel_gets_intel_build(self, checker, monkeypatch):
        """並び順の先頭が Intel でも AppleSilicon でも結果は変わらないこと"""
        for assets in (RELEASE, list(reversed(RELEASE))):
            url = _pick(checker, assets, "Darwin", "x86_64", monkeypatch)
            assert "Intel" in url

    def test_intel_never_gets_arm_build(self, checker, monkeypatch):
        """arm64 版しか無いときに Intel 機へ渡さない（起動しないため）"""
        only_arm = _assets(f"Chaptr-{VERSION}-macOS-AppleSilicon.dmg")
        assert _pick(checker, only_arm, "Darwin", "x86_64", monkeypatch) is None

    def test_arm_falls_back_to_intel(self, checker, monkeypatch):
        """Intel 版しか無いときは Rosetta で動くので受け取る"""
        only_intel = _assets(f"Chaptr-{VERSION}-macOS-Intel.dmg")
        url = _pick(checker, only_intel, "Darwin", "arm64", monkeypatch)
        assert "Intel" in url

    def test_arm_accepts_unlabeled_dmg(self, checker, monkeypatch):
        """アーキテクチャ表記の無い古いリリースでも受け取れること"""
        legacy = _assets("Chaptr-v2.0.0-macOS.dmg")
        url = _pick(checker, legacy, "Darwin", "arm64", monkeypatch)
        assert url.endswith(".dmg")


class TestWindows:
    def test_exe_is_found(self, checker, monkeypatch):
        url = _pick(checker, RELEASE, "Windows", "amd64", monkeypatch)
        assert url.endswith(".exe")

    def test_zip_still_accepted(self, checker, monkeypatch):
        """過去のリリースが zip だった場合にも対応する"""
        zipped = _assets("Chaptr-v2.0.0-Windows.zip")
        url = _pick(checker, zipped, "Windows", "amd64", monkeypatch)
        assert url.endswith(".zip")


class TestOther:
    def test_unknown_platform_returns_none(self, checker, monkeypatch):
        assert _pick(checker, RELEASE, "Linux", "x86_64", monkeypatch) is None

    def test_empty_release_returns_none(self, checker, monkeypatch):
        assert _pick(checker, [], "Darwin", "arm64", monkeypatch) is None
