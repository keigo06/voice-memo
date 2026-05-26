import logging
import sys
import threading
from pathlib import Path

from voice_memo.config import Config
from voice_memo.recorder import AudioRecorder, RecorderConfig

logger = logging.getLogger(__name__)


class HotkeyRecorder:
    """ホットキーによる録音トグルを管理するクラス"""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._recorder: AudioRecorder | None = None
        self._lock = threading.Lock()
        self._is_recording = False

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def toggle(self) -> None:
        with self._lock:
            if self._is_recording:
                self._stop()
            else:
                self._start()

    def _start(self) -> None:
        rec_config = RecorderConfig(
            device_name=self._config.device_name,
            sample_rate=self._config.sample_rate,
            channels=self._config.channels,
            max_duration=self._config.memo_max_duration,
        )
        self._recorder = AudioRecorder(rec_config)
        self._recorder.start()
        self._is_recording = True
        logger.info("録音開始 (ホットキー)")
        # max_duration 後に自動停止するバックグラウンドスレッド
        threading.Thread(target=self._auto_stop_on_timeout, daemon=True).start()

    def _auto_stop_on_timeout(self) -> None:
        recorder = self._recorder
        if recorder is None:
            return
        recorder.stop_event.wait()
        with self._lock:
            if self._is_recording and self._recorder is recorder:
                logger.info("最大録音時間に達したため自動停止します")
                print("\n最大録音時間に達しました。自動保存します。", flush=True)
                self._stop()

    def _stop(self) -> None:
        self._is_recording = False
        if self._recorder is None:
            return
        recorder = self._recorder
        self._recorder = None  # clear reference before stop() to prevent double-stop
        try:
            memo = recorder.stop()
        except Exception:
            logger.exception("録音の停止に失敗しました")
            return

        duration_sec = len(memo.audio_data) / memo.sample_rate
        save_dir = Path(self._config.save_dir).expanduser()
        memo.save_wav(save_dir / "audio" / f"{memo.id}.memo.wav")
        memo.save_json(save_dir / "meta" / f"{memo.id}.memo.json", duration_sec)
        logger.info("録音保存: %s (%.1f秒)", memo.id, duration_sec)
        print(f"\n保存しました: {memo.id} ({duration_sec:.1f}秒)", flush=True)


def run_hotkey_listener(config: Config) -> None:
    """グローバルホットキーリスナーを起動してブロックする"""
    try:
        from pynput import keyboard
    except ImportError:
        print("エラー: pynput が見つかりません。`uv sync` を実行してください。", file=sys.stderr)
        raise SystemExit(1)

    recorder = HotkeyRecorder(config)

    def on_activate() -> None:
        if recorder.is_recording:
            print("\r録音を停止しています...", end="", flush=True)
        else:
            print("録音を開始しました。もう一度ホットキーを押すと停止・保存します。", flush=True)
        recorder.toggle()

    hotkey_str = config.hotkey
    print(f"ホットキー待機中: {hotkey_str}  (Ctrl+C で終了)", flush=True)

    with keyboard.GlobalHotKeys({hotkey_str: on_activate}) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            pass

    # 録音中に終了した場合は保存する
    if recorder.is_recording:
        print("\nCtrl+C で停止・保存します...", flush=True)
        recorder.toggle()
