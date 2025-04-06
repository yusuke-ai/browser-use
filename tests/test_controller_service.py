# tests/test_controller_service.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY

# テスト対象のクラスと関連クラスをインポート
from browser_use.controller.service import Controller
from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser.context import BrowserContext
from browser_use.dom import mutation_observer
from pydantic import BaseModel, Field, create_model # create_model を追加
from typing import List, Dict, Optional

# pytestmark = pytest.mark.asyncio # ファイル全体の asyncio マークを削除済み

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
	# get_allowed_actions のフィルタリング (`action in self.registry.registry.actions`) のために
	# ネストされた registry オブジェクトとその actions 辞書をモックする
	# Registry インスタンスが持つ registry 属性 (ActionRegistryインスタンス) をモック
	mock.registry = MagicMock()
	# ActionRegistry インスタンスが持つ actions 属性 (辞書) をモックし、dummy_action を含める
	# ※ get_allowed_actions のフィルタリングは Controller 側で行われるため、
	#   Controller の __init__ で渡される mock_registry がこの構造を持つことが重要
	mock.registry.actions = {'dummy_action': MagicMock()}
	return mock

@pytest.fixture
def controller(mock_registry):
	"""Controller のインスタンスを作成 (Registryをモックで置き換え)"""
	# Controller の __init__ 内で Registry が使われるので、パッチを当てる
	with patch('browser_use.controller.service.Registry', return_value=mock_registry):
		# test_act_* のテストで URL バリデーションをパスするために、
		# common_actions に dummy_action を含めて初期化する
		instance = Controller(common_actions=['dummy_action'])
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

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_with_dom_changes(controller, mock_browser_context, mock_registry):
	"""actメソッドがDOM変更を検知し、結果に含めるかテスト"""

	action_to_execute = DummyActionModel(dummy_action=DummyParams())
	expected_dom_changes = [{"tag": "DIV", "content": "New Div"}]

	# URLバリデーションを回避するために get_allowed_actions をモック化し、他のモックと一つの with 文にまとめる
	with patch.object(controller, 'get_allowed_actions', return_value=['dummy_action']) as mock_get_allowed, \
		 patch('browser_use.dom.mutation_observer.subscribe', new_callable=AsyncMock) as mock_subscribe, \
		 patch('browser_use.dom.mutation_observer.unsubscribe', new_callable=AsyncMock) as mock_unsubscribe, \
		 patch('browser_use.controller.service.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:

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

		# get_allowed_actions が呼ばれたことを確認
		mock_get_allowed.assert_called_once()
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

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_without_dom_changes(controller, mock_browser_context, mock_registry):
	"""actメソッドがDOM変更なしの場合に dom_changes が None のままかテスト"""

	action_to_execute = DummyActionModel(dummy_action=DummyParams())

	# URLバリデーションを回避するために get_allowed_actions をモック化し、他のモックと一つの with 文にまとめる
	with patch.object(controller, 'get_allowed_actions', return_value=['dummy_action']) as mock_get_allowed, \
		 patch('browser_use.dom.mutation_observer.subscribe', new_callable=AsyncMock) as mock_subscribe, \
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

		# get_allowed_actions が呼ばれたことを確認
		mock_get_allowed.assert_called_once()
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


# --- URL Action Map テスト用の準備 ---

# ダミーアクション関数 (非同期である必要あり)
async def dummy_action_func_1(params: BaseModel): return ActionResult(extracted_content="action1 executed")
async def dummy_action_func_2(params: BaseModel): return ActionResult(extracted_content="action2 executed")
async def common_action_func_1(params: BaseModel): return ActionResult(extracted_content="common1 executed")
async def common_action_func_2(params: BaseModel): return ActionResult(extracted_content="common2 executed")

# ダミーパラメータモデル
class EmptyParams(BaseModel):
	pass

@pytest.fixture
def url_controller():
	"""URL Action Map 機能を持つ Controller インスタンスを作成"""
	url_map = {
		"https://example.com/specific/": ["action1"],
		"https://example.com/": ["action2"],
		"https://another.com/": [], # 固有アクションなし
	}
	# common_actions には登録するアクション名を指定
	common = ["common_action1", "common_action2"]

	# Controllerインスタンス作成時にマップと共通アクションを渡す
	controller_instance = Controller(url_action_map=url_map, common_actions=common)

	# テスト用アクションを登録 (実際の Registry を使う)
	registry = controller_instance.registry

	# 共通アクションの登録 (common_actions のリストと関数名を合わせる)
	@registry.action("Common Action 1", param_model=EmptyParams)
	async def common_action1(params: EmptyParams): return ActionResult(extracted_content="common1 executed")
	@registry.action("Common Action 2", param_model=EmptyParams)
	async def common_action2(params: EmptyParams): return ActionResult(extracted_content="common2 executed")

	# URL固有アクションの登録 (url_map のリストと関数名を合わせる)
	@registry.action("Action 1 for specific", param_model=EmptyParams)
	async def action1(params: EmptyParams): return ActionResult(extracted_content="action1 executed")
	@registry.action("Action 2 for example.com", param_model=EmptyParams)
	async def action2(params: EmptyParams): return ActionResult(extracted_content="action2 executed")

	# __init__ の最後で common_actions が設定される処理は Controller 内部で行われるため、
	# ここで registry.actions を直接触る必要はない。

	return controller_instance

# --- URL Action Map テストケース: get_allowed_actions ---

# 同期テストなのでマーク不要
def test_get_allowed_actions_common(url_controller):
	"""共通アクションのみが許可されるURLでのテスト"""
	allowed = url_controller.get_allowed_actions("https://unknown.com/")
	# 共通アクションのみが含まれることを確認 (順序は問わないのでセットで比較)
	assert set(allowed) == {"common_action1", "common_action2"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_specific(url_controller):
	"""URL固有アクションと共通アクションが許可されるURLでのテスト"""
	allowed = url_controller.get_allowed_actions("https://example.com/other")
	# action2 と共通アクションが含まれることを確認
	assert set(allowed) == {"common_action1", "common_action2", "action2"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_longest_prefix(url_controller):
	"""より長いプレフィックスが優先されるかのテスト"""
	allowed = url_controller.get_allowed_actions("https://example.com/specific/page")
	# action1 と共通アクションが含まれることを確認
	assert set(allowed) == {"common_action1", "common_action2", "action1"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_no_specific(url_controller):
	"""URL固有アクションが定義されていないURLでのテスト"""
	allowed = url_controller.get_allowed_actions("https://another.com/some/path")
	# 共通アクションのみが含まれることを確認
	assert set(allowed) == {"common_action1", "common_action2"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_root(url_controller):
	"""ルートURLでのテスト (example.com/ にマッチ)"""
	allowed = url_controller.get_allowed_actions("https://example.com/")
	# action2 と共通アクションが含まれることを確認
	assert set(allowed) == {"common_action1", "common_action2", "action2"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_unregistered_in_map(url_controller):
	"""マップにはあるが実際には登録されていないアクションは除外されるか"""
	# マップに "unregistered_action" を追加したコントローラーを仮定 (フィクスチャ内で追加しても良い)
	url_controller.url_action_map["https://special.com/"] = ["unregistered_action"]
	url_controller.sorted_url_prefixes = sorted(url_controller.url_action_map.keys(), key=len, reverse=True) # 再ソート

	allowed = url_controller.get_allowed_actions("https://special.com/page")
	# 共通アクションのみが含まれ、unregistered_action は含まれないことを確認
	assert set(allowed) == {"common_action1", "common_action2"}


# --- URL Action Map テストケース: act バリデーション ---

# act テスト用の ActionModel (ダミー)
class UrlActionModel(ActionModel):
	action1: Optional[EmptyParams] = None
	action2: Optional[EmptyParams] = None
	common_action1: Optional[EmptyParams] = None
	common_action2: Optional[EmptyParams] = None
	forbidden_action: Optional[EmptyParams] = None # 許可されないアクション

@pytest.fixture
def mock_browser_context_with_url():
	"""URL を持つ BrowserContext のモックを作成"""
	mock_page = AsyncMock()
	mock_page.url = "https://initial.url/" # 初期URL

	mock_context = AsyncMock(spec=BrowserContext)
	mock_context.get_current_page = AsyncMock(return_value=mock_page)
	return mock_context, mock_page # ページモックも返す

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_allowed_common_action(url_controller, mock_browser_context_with_url):
	"""共通アクションがどのURLでも実行できるかテスト"""
	mock_context, mock_page = mock_browser_context_with_url
	mock_page.url = "https://any.url/path" # 任意のURL

	action_to_execute = UrlActionModel(common_action1=EmptyParams())

	# registry.execute_action が呼ばれることを確認するためのモック差し替え
	url_controller.registry.execute_action = AsyncMock(return_value=ActionResult(extracted_content="common1 executed"))

	result = await url_controller.act(action_to_execute, mock_context)

	assert result.error is None
	assert result.extracted_content == "common1 executed"
	url_controller.registry.execute_action.assert_called_once()

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_allowed_specific_action(url_controller, mock_browser_context_with_url):
	"""URL固有アクションが正しいURLで実行できるかテスト"""
	mock_context, mock_page = mock_browser_context_with_url
	mock_page.url = "https://example.com/specific/deep" # action1 が許可されるURL

	action_to_execute = UrlActionModel(action1=EmptyParams())
	url_controller.registry.execute_action = AsyncMock(return_value=ActionResult(extracted_content="action1 executed"))

	result = await url_controller.act(action_to_execute, mock_context)

	assert result.error is None
	assert result.extracted_content == "action1 executed"
	url_controller.registry.execute_action.assert_called_once()

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_forbidden_action(url_controller, mock_browser_context_with_url):
	"""許可されていないアクションを実行しようとした場合にエラーが返るかテスト"""
	mock_context, mock_page = mock_browser_context_with_url
	mock_page.url = "https://example.com/" # action2 と common が許可されるURL

	# action1 は許可されていないはず
	action_to_execute = UrlActionModel(action1=EmptyParams())
	url_controller.registry.execute_action = AsyncMock() # 呼ばれないはず

	result = await url_controller.act(action_to_execute, mock_context)

	assert result.error is not None
	assert "Action 'action1' is not allowed" in result.error
	assert "https://example.com/" in result.error
	url_controller.registry.execute_action.assert_not_called() # execute_action が呼ばれていないこと

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_no_action_specified(url_controller, mock_browser_context_with_url):
	"""ActionModel が空の場合にエラーが返るかテスト"""
	mock_context, _ = mock_browser_context_with_url
	empty_action = UrlActionModel() # 何もセットしない
	url_controller.registry.execute_action = AsyncMock()

	result = await url_controller.act(empty_action, mock_context)

	assert result.error == "No action specified."
	url_controller.registry.execute_action.assert_not_called()


# --- URL Action Map テストケース: get_prompt_description / create_action_model ---

# 同期テストなのでマーク不要
def test_get_prompt_description_uses_allowed_actions(url_controller):
	"""get_prompt_description が get_allowed_actions の結果を使うかテスト"""
	test_url = "https://example.com/specific/path"
	expected_allowed = {"common_action1", "common_action2", "action1"}

	# registry のメソッドをモック化
	url_controller.registry.get_prompt_description = MagicMock(return_value="Mocked Description")

	# get_allowed_actions が期待通りのリストを返すようにモック化 (念のため)
	with patch.object(url_controller, 'get_allowed_actions', return_value=list(expected_allowed)) as mock_get_allowed:
		description = url_controller.get_prompt_description(test_url)

		# get_allowed_actions が呼ばれたか
		mock_get_allowed.assert_called_once_with(test_url)
		# registry.get_prompt_description が正しい引数で呼ばれたか
		url_controller.registry.get_prompt_description.assert_called_once_with(allowed_actions=list(expected_allowed))
		# 返り値がモックの値か
		assert description == "Mocked Description"

# 同期テストなのでマーク不要
def test_create_action_model_uses_allowed_actions(url_controller):
	"""create_action_model が get_allowed_actions の結果を使うかテスト"""
	test_url = "https://example.com/"
	expected_allowed = {"common_action1", "common_action2", "action2"}

	# registry のメソッドをモック化
	MockActionModel = create_model('MockActionModel', __base__=ActionModel) # ダミーのモデルクラス
	url_controller.registry.create_action_model = MagicMock(return_value=MockActionModel)

	# get_allowed_actions が期待通りのリストを返すようにモック化 (念のため)
	with patch.object(url_controller, 'get_allowed_actions', return_value=list(expected_allowed)) as mock_get_allowed:
		ActionModelClass = url_controller.create_action_model(test_url)

		# get_allowed_actions が呼ばれたか
		mock_get_allowed.assert_called_once_with(test_url)
		# registry.create_action_model が正しい引数で呼ばれたか
		url_controller.registry.create_action_model.assert_called_once_with(include_actions=list(expected_allowed))
		# 返り値がモックのモデルクラスか
		assert ActionModelClass == MockActionModel
