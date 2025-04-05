# tests/test_controller_service.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY

# テスト対象のクラスと関連クラスをインポート
from browser_use.controller.service import Controller
from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser.context import BrowserContext
from browser_use.dom import mutation_observer
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

# pytest-asyncio を使うためのマーク
pytestmark = pytest.mark.asyncio

# --- テスト用のダミークラス ---
class DummyParams(BaseModel):
	param1: str = "value1"

class DummyActionModel(ActionModel):
	dummy_action: DummyParams = Field(...)

class DummyActionResult(ActionResult):
	# ActionResult を継承してテストしやすくする (本来は不要かも)
	pass

# --- テスト本体 ---

@pytest.fixture
def mock_browser_context():
	"""BrowserContext のモックを作成"""
	mock = AsyncMock(spec=BrowserContext)
	return mock

@pytest.fixture
def mock_registry():
	"""Registry のモックを作成"""
	mock = MagicMock()
	# execute_action が ActionResult を返すように設定
	mock.execute_action = AsyncMock(return_value=DummyActionResult(extracted_content="Action executed"))
	return mock

@pytest.fixture
def controller(mock_registry):
	"""Controller のインスタンスを作成 (Registryをモックで置き換え)"""
	# Controller の __init__ 内で Registry が使われるので、パッチを当てる
	with patch('browser_use.controller.service.Registry', return_value=mock_registry):
		# exclude_actions などはデフォルトで良いとする
		instance = Controller()
		# モックを差し替えたことを確認（任意）
		instance.registry = mock_registry
	return instance

@pytest.fixture(autouse=True)
async def clear_mutation_callbacks():
	"""各テストの前後で mutation_observer のコールバックリストをクリア"""
	async with mutation_observer._lock:
		mutation_observer.DOM_change_callback.clear()
	yield # テスト実行
	async with mutation_observer._lock:
		mutation_observer.DOM_change_callback.clear()

# --- テストケース ---

async def test_act_with_dom_changes(controller, mock_browser_context, mock_registry):
	"""actメソッドがDOM変更を検知し、結果に含めるかテスト"""
	
	action_to_execute = DummyActionModel(dummy_action=DummyParams())
	expected_dom_changes = [{"tag": "DIV", "content": "New Div"}]

	# mutation_observer の subscribe/unsubscribe をモック化
	with patch('browser_use.dom.mutation_observer.subscribe', new_callable=AsyncMock) as mock_subscribe, \
		 patch('browser_use.dom.mutation_observer.unsubscribe', new_callable=AsyncMock) as mock_unsubscribe, \
		 patch('browser_use.controller.service.asyncio.sleep', new_callable=AsyncMock) as mock_sleep: # sleepもモック化

		# subscribe されたコールバックを取得し、テスト中に呼び出す関数を定義
		captured_callback = None
		async def capture_callback(callback):
			nonlocal captured_callback
			captured_callback = callback
			# コールバックが呼ばれたタイミングでDOM変更をシミュレート
			# (actメソッド内の sleep の前にコールバックが呼ばれる想定)
			# await asyncio.sleep(0.1) # わずかに待機
			callback(expected_dom_changes) # <= コールバックを直接呼び出す
		mock_subscribe.side_effect = capture_callback

		# act を実行
		result = await controller.act(
			action=action_to_execute,
			browser_context=mock_browser_context,
		)

		# subscribe が1回呼ばれたことを確認
		mock_subscribe.assert_called_once()
		assert captured_callback is not None # コールバックがキャプチャされたか

		# registry.execute_action が呼ばれたことを確認
		mock_registry.execute_action.assert_called_once_with(
			'dummy_action', # ActionModel のキー
			{}, # しおり: exclude_unset=True によりデフォルト値は除外されるため、空辞書を期待する
			browser=mock_browser_context,
			page_extraction_llm=None,
			sensitive_data=None,
			available_file_paths=None,
			context=None
		)
		
		# sleep が呼ばれたことを確認
		mock_sleep.assert_called_once_with(0.5)

		# unsubscribe が1回呼ばれたことを確認
		mock_unsubscribe.assert_called_once_with(captured_callback)

		# 返された ActionResult を確認
		assert isinstance(result, ActionResult)
		assert result.extracted_content == "Action executed" # モックの返り値
		
		# dom_changes が設定されていることを確認
		# ※注意: このテストは act メソッド内の result.dom_changes = detected_changes の
		# コメントアウトが解除されていることを前提としています。
		assert result.dom_changes == expected_dom_changes
			
async def test_act_without_dom_changes(controller, mock_browser_context, mock_registry):
	"""actメソッドがDOM変更なしの場合に dom_changes が None のままかテスト"""

	action_to_execute = DummyActionModel(dummy_action=DummyParams())

	# mutation_observer の subscribe/unsubscribe をモック化
	with patch('browser_use.dom.mutation_observer.subscribe', new_callable=AsyncMock) as mock_subscribe, \
		 patch('browser_use.dom.mutation_observer.unsubscribe', new_callable=AsyncMock) as mock_unsubscribe, \
		 patch('browser_use.controller.service.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:

		captured_callback = None
		async def capture_callback(callback):
			nonlocal captured_callback
			captured_callback = callback
			# ここではDOM変更をシミュレートしない
		mock_subscribe.side_effect = capture_callback

		# act を実行
		result = await controller.act(
			action=action_to_execute,
			browser_context=mock_browser_context,
		)

		# subscribe/unsubscribe が呼ばれたことを確認
		mock_subscribe.assert_called_once()
		assert captured_callback is not None
		mock_unsubscribe.assert_called_once_with(captured_callback)
		
		# sleep が呼ばれたことを確認
		mock_sleep.assert_called_once_with(0.5)

		# 返された ActionResult を確認
		assert isinstance(result, ActionResult)
		assert result.extracted_content == "Action executed"
		# DOM変更がないので dom_changes は None のはず
		assert result.dom_changes == []

# TODO: アクションが str や None を返す場合のテストも追加 (現状維持方針なら不要)
