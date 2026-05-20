import click

from voice_memo.config import load_config


@click.group()
def main() -> None:
    pass


@main.command()
def record() -> None:
    """録音を開始する（Ctrl+Cで停止・保存）"""
    pass


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
