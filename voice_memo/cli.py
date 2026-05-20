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
    pass


@main.command()
@click.option("--set", "set_name", default=None, metavar="NAME", help="デバイスをconfig.yamlに書き込む")
def devices(set_name: str | None) -> None:
    """利用可能なマイク一覧を表示する"""
    pass


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
    """Web UIサーバーを起動する（未実装）"""
    click.echo("未実装")
