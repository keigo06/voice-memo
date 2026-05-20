import sys
import threading
import time
from pathlib import Path

import click

from voice_memo.config import load_config
from voice_memo.recorder import AudioRecorder, RecorderConfig


@click.group()
def main() -> None:
    pass


@main.command()
def record() -> None:
    """録音を開始する（Ctrl+Cで停止・保存）"""
    config = load_config()
    rec_config = RecorderConfig(
        device_name=config.device_name,
        sample_rate=config.sample_rate,
        channels=config.channels,
        max_duration=config.memo_max_duration,
    )
    recorder = AudioRecorder(rec_config)

    click.echo("録音中... Ctrl+Cで停止")

    recorder.start()
    start_time = time.time()

    stop_flag = threading.Event()

    def _print_elapsed() -> None:
        while not stop_flag.wait(timeout=1.0):
            elapsed = int(time.time() - start_time)
            minutes, seconds = divmod(elapsed, 60)
            sys.stderr.write(f"\r  経過時間: {minutes:02d}:{seconds:02d}")
            sys.stderr.flush()
            if recorder.stop_event.is_set():
                stop_flag.set()

    ticker = threading.Thread(target=_print_elapsed, daemon=True)
    ticker.start()

    try:
        # 最大時間超過イベントを待つ（Ctrl+C で KeyboardInterrupt に飛ぶ）
        recorder.stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop_flag.set()
        ticker.join(timeout=2)
        sys.stderr.write("\n")
        sys.stderr.flush()

        memo = recorder.stop()

        duration_sec = len(memo.audio_data) / memo.sample_rate

        save_dir = Path(config.save_dir).expanduser()
        memo.save_wav(save_dir / "audio" / f"{memo.id}.wav")
        memo.save_json(save_dir / "meta" / f"{memo.id}.memo.json", duration_sec)

        click.echo(f"保存しました: {memo.id} ({duration_sec:.1f}秒)")


@main.command("list")
@click.option("--all", "show_all", is_flag=True, help="全件表示")
@click.option("--date", "date_str", default=None, metavar="YYYY-MM-DD", help="日付フィルタ")
@click.option("--tag", "tag", default=None, help="タグフィルタ")
def list_cmd(show_all: bool, date_str: str | None, tag: str | None) -> None:
    """メモ一覧を表示する"""
    import json as _json

    config = load_config()
    meta_dir = Path(config.save_dir).expanduser() / "meta"

    if not meta_dir.exists():
        click.echo("メモがありません。")
        return

    records = []
    for p in meta_dir.glob("*.memo.json"):
        with p.open(encoding="utf-8") as f:
            records.append(_json.load(f))

    # 降順ソート
    records.sort(key=lambda r: r["unix_timestamp"], reverse=True)

    # 日付フィルタ
    if date_str is not None:
        records = [
            r for r in records
            if r.get("created_at", "").startswith(date_str)
        ]

    # タグフィルタ
    if tag is not None:
        records = [r for r in records if tag in r.get("tags", [])]

    # 件数制限（--all でなければ直近10件）
    if not show_all:
        records = records[:10]

    if not records:
        click.echo("該当するメモがありません。")
        return

    header = f"{'日時':<20} {'長さ':<8} {'状態':<14} タイトル"
    click.echo(header)
    click.echo("-" * len(header))

    for r in records:
        # created_at は ISO8601 形式なのでスペースで整形
        dt_raw = r.get("created_at", "")
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(dt_raw)
            dt_str = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            dt_str = dt_raw[:16]

        duration = f"{r.get('duration_sec', 0):.1f}秒"
        status = f"[{r.get('transcript_status', '?')}]"
        title = r.get("title", "") or "-"

        click.echo(f"{dt_str:<20} {duration:<8} {status:<14} {title}")


@main.command()
@click.option("--set", "set_name", default=None, metavar="NAME", help="デバイスをconfig.yamlに書き込む")
def devices(set_name: str | None) -> None:
    """利用可能なマイク一覧を表示する"""
    import sounddevice as sd
    import yaml

    config = load_config()

    if set_name is not None:
        config_path = Path("~/voice-memo/config.yaml").expanduser()
        if config_path.exists():
            with config_path.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            raw = {}

        raw["device_name"] = set_name
        with config_path.open("w", encoding="utf-8") as f:
            yaml.dump(raw, f, allow_unicode=True)

        click.echo(f"デバイスを設定しました: {set_name}")
        return

    all_devices = sd.query_devices()
    for i, dev in enumerate(all_devices):
        if dev["max_input_channels"] < 1:
            continue

        channels = dev["max_input_channels"]
        rate = int(dev["default_samplerate"])
        name = dev["name"]

        # 現在の設定と部分一致する場合に印を付ける
        marker = ""
        if config.device_name and config.device_name.lower() in name.lower():
            marker = "  <- 現在選択中"

        click.echo(f"[{i}] {name}  ({channels}ch, {rate}Hz){marker}")


@main.command()
def transcribe() -> None:
    """音声をテキストに変換する（未実装）"""
    click.echo("未実装")


@main.command()
def setup() -> None:
    """初期セットアップ（未実装）"""
    click.echo("未実装")


@main.command()
def install() -> None:
    """依存パッケージをインストールする（未実装）"""
    click.echo("未実装")


@main.command()
def server() -> None:
    """Web UIサーバーを起動する"""
    from voice_memo.server import run_server
    config = load_config()
    run_server(config)
