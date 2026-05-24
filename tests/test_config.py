"""voice_memo.config の振る舞いテスト"""

import textwrap
from pathlib import Path

import pytest

from voice_memo.config import Config, load_config


def test_load_config_returns_defaults_when_no_file_exists(tmp_path, monkeypatch):
    """設定ファイルが存在しないとき、デフォルト値の Config が返る"""
    # ~/voice-memo/config.yaml とリポジトリ config.yaml が見つからない状態を作る
    monkeypatch.setattr(
        "voice_memo.config._repo_config",
        lambda: tmp_path / "nonexistent.yaml",
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    cfg = load_config(path=tmp_path / "also_nonexistent.yaml")

    assert isinstance(cfg, Config)
    assert cfg.sample_rate == 16000
    assert cfg.channels == 1
    assert cfg.memo_max_duration == 300
    assert cfg.save_dir == "~/voice-memo/data"
    assert cfg.server_port == 8765
    assert cfg.open_browser is True
    assert cfg.whisper_model == "small"
    assert cfg.whisper_language == "ja"
    assert cfg.whisper_device == "cpu"
    assert cfg.whisper_prompt == ""
    assert cfg.device_name is None


def test_load_config_overrides_with_yaml_values(tmp_path, monkeypatch):
    """YAML ファイルの値でデフォルト値が上書きされる"""
    cfg_file = tmp_path / "test_config.yaml"
    cfg_file.write_text(
        textwrap.dedent("""\
            sample_rate: 44100
            whisper_model: "base"
            whisper_language: "en"
            server_port: 9000
        """)
    )
    monkeypatch.setattr(
        "voice_memo.config._repo_config",
        lambda: tmp_path / "nonexistent.yaml",
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    cfg = load_config(path=cfg_file)

    assert cfg.sample_rate == 44100
    assert cfg.whisper_model == "base"
    assert cfg.whisper_language == "en"
    assert cfg.server_port == 9000
    # 指定していない値はデフォルト
    assert cfg.channels == 1


def test_load_config_home_yaml_takes_priority_over_repo_yaml(tmp_path, monkeypatch):
    """~/voice-memo/config.yaml が リポジトリ config.yaml より優先される"""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    home_config = home_dir / "voice-memo" / "config.yaml"
    home_config.parent.mkdir(parents=True)
    home_config.write_text("server_port: 1111\n")

    repo_config = tmp_path / "repo_config.yaml"
    repo_config.write_text("server_port: 2222\n")

    monkeypatch.setattr("voice_memo.config._repo_config", lambda: repo_config)
    monkeypatch.setenv("HOME", str(home_dir))

    cfg = load_config()

    assert cfg.server_port == 1111
