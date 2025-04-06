# tests/test_controller_service.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY

# テスト対象のクラスと関連クラスをインポート
from browser_use.controller.service import Controller
from browser_use.controller.registry.service import Registry # Registry をインポート
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
	"""Registry のモックを作成 (インターフェースのみ)"""
	# Registry クラスのインターフェースを模倣するために spec を指定
	mock = MagicMock(spec=Registry)
	# 必要なメソッドをモック
	mock.execute_action = AsyncMock(return_value=DummyActionResult(extracted_content="Action executed"))
	mock.get_allowed_actions = MagicMock(return_value=['dummy_action']) # デフォルトで許可
	# 必要に応じて他のメソッドもモック化可能
	# mock.get_prompt_description = MagicMock(return_value="Mocked Prompt")
	# mock.create_action_model = MagicMock(return_value=DummyActionModel)
	# 内部属性 (registry.actions など) のモックは不要
	return mock

@pytest.fixture
def controller(mock_registry):
	"""Controller のインスタンスを作成 (Registryをモックで置き換え)"""
	# Controller の __init__ 内で Registry が使われるので、パッチを当てる
	with patch('browser_use.controller.service.Registry', return_value=mock_registry):
		# __init__ から common_actions と url_action_map が削除された
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

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_with_dom_changes(controller, mock_browser_context, mock_registry):
	"""actメソッドがDOM変更を検知し、結果に含めるかテスト"""

	action_to_execute = DummyActionModel(dummy_action=DummyParams())
	expected_dom_changes = [{"type": "added", "tag": "DIV", "content": "New Div"}]

	# get_allowed_actions は Controller 内部で registry.get_allowed_actions を呼ぶようになった
	# act メソッド内のバリデーションをテストするため、controller.get_allowed_actions をモック化
	with patch.object(controller, 'get_allowed_actions', return_value=['dummy_action']) as mock_get_allowed, \
		 patch('browser_use.dom.mutation_observer.subscribe', new_callable=AsyncMock) as mock_subscribe, \
		 patch('browser_use.dom.mutation_observer.unsubscribe', new_callable=AsyncMock) as mock_unsubscribe, \
		 patch('browser_use.controller.service.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:

		# subscribe されたコールバックを取得し、テスト中に呼び出す関数を定義
		captured_callback = None
		async def capture_callback(callback):
			nonlocal captured_callback
			captured_callback = callback
			# コールバックを直接呼び出してDOM変更をシミュレート
			if captured_callback: # None でないことを確認
				captured_callback(expected_dom_changes)
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
		# action.model_dump(exclude_unset=True) で params を取得するため、デフォルト値は含まれない
		mock_registry.execute_action.assert_called_once_with(
			'dummy_action', # ActionModel のキー (action_name)
			{}, # デフォルト値は exclude_unset=True で除外されるため空辞書を期待
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
		assert result.dom_changes is not None
		assert isinstance(result.dom_changes, list)
		assert len(result.dom_changes) == 1
		
		# 変更情報の内容を確認
		change = result.dom_changes[0]
		assert change['type'] == 'added'  # JavaScriptで設定されたtype
		assert change['tag'] == 'DIV'
		assert change['content'] == 'New Div'
		assert 'xpath' in change  # XPathが含まれていることを確認
		assert 'html' in change   # HTMLが含まれていることを確認
		
		# target_element は設定されていないはず（このテストではクリックやテキスト入力を行っていないため）
		assert result.target_element is None

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_without_dom_changes(controller, mock_browser_context, mock_registry):
	"""actメソッドがDOM変更なしの場合に dom_changes が None のままかテスト"""

	action_to_execute = DummyActionModel(dummy_action=DummyParams())

	# get_allowed_actions は Controller 内部で registry.get_allowed_actions を呼ぶようになった
	# act メソッド内のバリデーションをテストするため、controller.get_allowed_actions をモック化
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
		assert result.dom_changes is None
		# target_element も設定されていないはず
		assert result.target_element is None

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_with_target_element(controller, mock_browser_context, mock_registry):
	"""クリックアクションでtarget_elementが設定されるかテスト"""
	
	# クリックアクション用のモデルを作成
	class ClickParams(BaseModel):
		index: int = 1
	
	class ClickActionModel(ActionModel):
		click_element: ClickParams = Field(...)
	
	action_to_execute = ClickActionModel(click_element=ClickParams())
	
	# DOM要素のモック
	mock_element_node = MagicMock()
	mock_element_node.tag_name = "BUTTON"
	mock_element_node.xpath = "/html/body/div/button[1]"
	
	# 要素ハンドルのモック
	mock_element_handle = AsyncMock()
	mock_element_handle.evaluate = AsyncMock(return_value="<button>Click me</button>")
	
	# ブラウザコンテキストのモックを設定
	mock_browser_context.get_dom_element_by_index = AsyncMock(return_value=mock_element_node)
	mock_browser_context.get_locate_element = AsyncMock(return_value=mock_element_handle)
	mock_page = AsyncMock()
	mock_browser_context.get_current_page = AsyncMock(return_value=mock_page)
	
	# モックのActionResultを作成し、target_elementを設定
	mock_result = ActionResult(
		extracted_content="Action executed",
		target_element={
			'tag': "BUTTON",
			'xpath': "/html/body/div/button[1]",
			'html': "<button>Click me</button>"
		}
	)
	
	# registry.execute_actionが返すActionResultを設定
	mock_registry.execute_action.return_value = mock_result
	
	with patch.object(controller, 'get_allowed_actions', return_value=['click_element']) as mock_get_allowed, \
		 patch('browser_use.dom.mutation_observer.subscribe', new_callable=AsyncMock) as mock_subscribe, \
		 patch('browser_use.dom.mutation_observer.unsubscribe', new_callable=AsyncMock) as mock_unsubscribe, \
		 patch('browser_use.controller.service.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
		
		# act を実行
		result = await controller.act(
			action=action_to_execute,
			browser_context=mock_browser_context,
		)
		
		# 操作対象の要素情報が設定されていることを確認
		assert result.target_element is not None
		assert result.target_element['tag'] == "BUTTON"
		assert result.target_element['xpath'] == "/html/body/div/button[1]"
		assert result.target_element['html'] == "<button>Click me</button>"
		
		# dom_changes は設定されていないはず（このテストではDOM変更をシミュレートしていないため）
		assert result.dom_changes is None

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
def url_pattern_controller():
	"""URLパターン機能を持つ Controller インスタンスを作成"""
	# Controllerインスタンス作成 (exclude_actions などはデフォルト)
	controller_instance = Controller()

	# テスト用アクションを登録 (実際の Registry を使う)
	registry = controller_instance.registry
	# デフォルトで登録されているアクションをクリア
	registry.registry.actions.clear()

	# 共通アクションの登録 (url_patterns=None)
	@registry.action("Common Action 1", param_model=EmptyParams)
	async def common_action1(params: EmptyParams): return ActionResult(extracted_content="common1 executed")
	@registry.action("Common Action 2", param_model=EmptyParams)
	async def common_action2(params: EmptyParams): return ActionResult(extracted_content="common2 executed")

	# URL固有アクションの登録 (url_patterns を指定)
	@registry.action("Action 1 for specific", param_model=EmptyParams, url_patterns=["https://example.com/specific/*"])
	async def action1(params: EmptyParams): return ActionResult(extracted_content="action1 executed")
	@registry.action("Action 2 for example.com", param_model=EmptyParams, url_patterns=["https://example.com/*"])
	async def action2(params: EmptyParams): return ActionResult(extracted_content="action2 executed")
	@registry.action("Action 3 for any subdomain", param_model=EmptyParams, url_patterns=["https://*.example.com/users/*"])
	async def action3(params: EmptyParams): return ActionResult(extracted_content="action3 executed")
	@registry.action("Action 4 for another", param_model=EmptyParams, url_patterns=["https://another.com/"]) # 完全一致
	async def action4(params: EmptyParams): return ActionResult(extracted_content="action4 executed")

	return controller_instance

# --- URLパターン テストケース: get_allowed_actions ---

# 同期テストなのでマーク不要
def test_get_allowed_actions_common_only(url_pattern_controller):
	"""共通アクションのみが許可されるURLでのテスト"""
	allowed = url_pattern_controller.get_allowed_actions("https://unknown.com/")
	assert set(allowed) == {"common_action1", "common_action2"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_specific_match(url_pattern_controller):
	"""URL固有アクション(action2)と共通アクションが許可されるURLでのテスト"""
	allowed = url_pattern_controller.get_allowed_actions("https://example.com/other")
	assert set(allowed) == {"common_action1", "common_action2", "action2"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_more_specific_match(url_pattern_controller):
	"""より具体的なURL固有アクション(action1)と共通アクションが許可されるURLでのテスト"""
	# action1 のパターン "https://example.com/specific/*" にマッチ
	# action2 のパターン "https://example.com/*" にもマッチするが、両方許可される
	allowed = url_pattern_controller.get_allowed_actions("https://example.com/specific/page")
	assert set(allowed) == {"common_action1", "common_action2", "action1", "action2"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_wildcard_match(url_pattern_controller):
	"""ワイルドカードパターン(action3)と共通アクションが許可されるURLでのテスト"""
	allowed = url_pattern_controller.get_allowed_actions("https://sub.example.com/users/profile")
	# action3 のパターン "https://*.example.com/users/*" にマッチ
	# action2 のパターン "https://example.com/*" にはマッチしない
	assert set(allowed) == {"common_action1", "common_action2", "action3"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_exact_match(url_pattern_controller):
	"""完全一致パターン(action4)と共通アクションが許可されるURLでのテスト"""
	allowed = url_pattern_controller.get_allowed_actions("https://another.com/")
	assert set(allowed) == {"common_action1", "common_action2", "action4"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_exact_match_fail(url_pattern_controller):
	"""完全一致パターン(action4)にマッチしないURLでのテスト"""
	allowed = url_pattern_controller.get_allowed_actions("https://another.com/path")
	# action4 は許可されない
	assert set(allowed) == {"common_action1", "common_action2"}

# 同期テストなのでマーク不要
def test_get_allowed_actions_unregistered_action(url_pattern_controller):
	"""実際には登録されていないアクションは含まれないことの確認 (Registry側で担保)"""
	# このテストは Registry.get_allowed_actions の実装に依存するため、
	# Controller レベルでは不要かもしれないが、念のため残す
	# (Registry に 'unregistered' というアクションが存在しないことを前提とする)
	allowed = url_pattern_controller.get_allowed_actions("https://any.url/")
	assert 'unregistered_action' not in allowed


# --- URLパターン テストケース: act バリデーション ---

# act テスト用の ActionModel (url_pattern_controller のアクションに対応)
class UrlPatternActionModel(ActionModel):
	action1: Optional[EmptyParams] = None
	action2: Optional[EmptyParams] = None
	action3: Optional[EmptyParams] = None
	action4: Optional[EmptyParams] = None
	common_action1: Optional[EmptyParams] = None
	common_action2: Optional[EmptyParams] = None
	# forbidden_action は不要 (許可されないアクションはモデルに含まれないため)

@pytest.fixture
def mock_browser_context_with_url():
	"""URL を持つ BrowserContext のモックを作成"""
	mock_page = AsyncMock()
	mock_page.url = "https://initial.url/" # 初期URL

	mock_context = AsyncMock(spec=BrowserContext)
	mock_context.get_current_page = AsyncMock(return_value=mock_page)
	return mock_context, mock_page # ページモックも返す

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_allowed_common_action(url_pattern_controller, mock_browser_context_with_url):
	"""共通アクションがどのURLでも実行できるかテスト"""
	mock_context, mock_page = mock_browser_context_with_url
	mock_page.url = "https://any.url/path" # 任意のURL

	action_to_execute = UrlPatternActionModel(common_action1=EmptyParams())

	# registry.execute_action が呼ばれることを確認するためのモック差し替え
	url_pattern_controller.registry.execute_action = AsyncMock(return_value=ActionResult(extracted_content="common1 executed"))

	result = await url_pattern_controller.act(action_to_execute, mock_context)

	assert result.error is None
	assert result.extracted_content == "common1 executed"
	url_pattern_controller.registry.execute_action.assert_called_once()

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_allowed_specific_action(url_pattern_controller, mock_browser_context_with_url):
	"""URL固有アクションが正しいURLで実行できるかテスト"""
	mock_context, mock_page = mock_browser_context_with_url
	mock_page.url = "https://example.com/specific/deep" # action1 が許可されるURL

	action_to_execute = UrlPatternActionModel(action1=EmptyParams())
	url_pattern_controller.registry.execute_action = AsyncMock(return_value=ActionResult(extracted_content="action1 executed"))

	result = await url_pattern_controller.act(action_to_execute, mock_context)

	assert result.error is None
	assert result.extracted_content == "action1 executed"
	url_pattern_controller.registry.execute_action.assert_called_once()

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_forbidden_action(url_pattern_controller, mock_browser_context_with_url):
	"""許可されていないアクションを実行しようとした場合にエラーが返るかテスト"""
	mock_context, mock_page = mock_browser_context_with_url
	mock_page.url = "https://another.com/path" # action4 は "/" で完全一致のため許可されない

	# action4 は許可されていないはず
	action_to_execute = UrlPatternActionModel(action4=EmptyParams())
	url_pattern_controller.registry.execute_action = AsyncMock() # 呼ばれないはず

	result = await url_pattern_controller.act(action_to_execute, mock_context)

	assert result.error is not None
	assert "Action 'action4' is not allowed" in result.error
	assert "https://another.com/path" in result.error
	url_pattern_controller.registry.execute_action.assert_not_called() # execute_action が呼ばれていないこと

@pytest.mark.asyncio # 非同期テストにマーク付与
async def test_act_no_action_specified(url_pattern_controller, mock_browser_context_with_url):
	"""ActionModel が空の場合にエラーが返るかテスト"""
	mock_context, _ = mock_browser_context_with_url
	empty_action = UrlPatternActionModel() # 何もセットしない
	url_pattern_controller.registry.execute_action = AsyncMock()

	result = await url_pattern_controller.act(empty_action, mock_context)

	assert result.error == "No action specified."
	url_pattern_controller.registry.execute_action.assert_not_called()


# --- URLパターン テストケース: get_prompt_description / create_action_model ---

# 同期テストなのでマーク不要
def test_get_prompt_description_uses_allowed_actions(url_pattern_controller):
	"""get_prompt_description が get_allowed_actions の結果を使うかテスト"""
	test_url = "https://example.com/specific/path"
	# このURLで許可されるアクション (action1, action2, common1, common2)
	expected_allowed = {"common_action1", "common_action2", "action1", "action2"}

	# registry のメソッドをモック化
	url_pattern_controller.registry.get_prompt_description = MagicMock(return_value="Mocked Description")

	# get_allowed_actions が期待通りのリストを返すようにモック化 (Controllerのメソッドをテスト)
	with patch.object(url_pattern_controller, 'get_allowed_actions', return_value=list(expected_allowed)) as mock_get_allowed:
		description = url_pattern_controller.get_prompt_description(test_url)

		# get_allowed_actions が呼ばれたか
		mock_get_allowed.assert_called_once_with(test_url)
		# registry.get_prompt_description が正しい引数で呼ばれたか
		url_pattern_controller.registry.get_prompt_description.assert_called_once_with(allowed_actions=list(expected_allowed))
		# 返り値がモックの値か
		assert description == "Mocked Description"

# 同期テストなのでマーク不要
def test_create_action_model_uses_allowed_actions(url_pattern_controller):
	"""create_action_model が get_allowed_actions の結果を使うかテスト"""
	test_url = "https://sub.example.com/users/profile"
	# このURLで許可されるアクション (action3, common1, common2)
	expected_allowed = {"common_action1", "common_action2", "action3"}

	# registry のメソッドをモック化
	MockActionModel = create_model('MockActionModel', __base__=ActionModel) # ダミーのモデルクラス
	url_pattern_controller.registry.create_action_model = MagicMock(return_value=MockActionModel)

	# get_allowed_actions が期待通りのリストを返すようにモック化 (Controllerのメソッドをテスト)
	with patch.object(url_pattern_controller, 'get_allowed_actions', return_value=list(expected_allowed)) as mock_get_allowed:
		ActionModelClass = url_pattern_controller.create_action_model(test_url)

		# get_allowed_actions が呼ばれたか
		mock_get_allowed.assert_called_once_with(test_url)
		# registry.create_action_model が正しい引数で呼ばれたか
		url_pattern_controller.registry.create_action_model.assert_called_once_with(include_actions=list(expected_allowed))
		# 返り値がモックのモデルクラスか
		assert ActionModelClass == MockActionModel
