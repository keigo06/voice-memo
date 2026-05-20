# ROS の PYTHONPATH が venv に混入するため、テスト実行時はクリアする
test:
	PYTHONPATH= .venv/bin/pytest tests/ -v

test-cov:
	PYTHONPATH= .venv/bin/pytest tests/ -v --cov=voice_memo --cov-report=term-missing

.PHONY: test test-cov
