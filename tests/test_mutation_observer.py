# tests/test_mutation_observer.py
import asyncio
import pytest
from typing import List, Dict
import json # しおり: dom_mutation_change_detected のテストで使うためインポート

# テスト対象のモジュールをインポート
from browser_use.dom import mutation_observer

# pytest-asyncio を使うためのマーク (しおり: ファイル全体への適用を削除)
# pytestmark = pytest.mark.asyncio

@pytest.mark.asyncio # しおり: 個別の関数にデコレータを追加
async def test_subscribe_unsubscribe():
	"""subscribe と unsubscribe が正しく動作するかテスト"""
	
	# テスト用のコールバック関数
	callback_called = False
	received_changes = None
	# しおり: コールバックは同期関数なので async def ではなく def
	def test_callback(changes: List[Dict[str, str]]):
		nonlocal callback_called, received_changes
		callback_called = True
		received_changes = changes
		print(f"Callback called with: {changes}") # デバッグ用

	# --- テスト実行前にリストをクリア ---
	# 他のテストの影響を受けないように、グローバルなリストをクリア
	async with mutation_observer._lock:
		mutation_observer.DOM_change_callback.clear()
	assert len(mutation_observer.DOM_change_callback) == 0
	# ---------------------------------

	# subscribe を実行
	await mutation_observer.subscribe(test_callback)
	
	# コールバックが1つ登録されているはず
	assert len(mutation_observer.DOM_change_callback) == 1
	assert mutation_observer.DOM_change_callback[0] == test_callback

	# 同じコールバックを再度 subscribe してもリストの長さは変わらないはず
	await mutation_observer.subscribe(test_callback)
	assert len(mutation_observer.DOM_change_callback) == 1

	# unsubscribe を実行
	await mutation_observer.unsubscribe(test_callback)
	
	# コールバックリストは空に戻るはず
	assert len(mutation_observer.DOM_change_callback) == 0

	# 存在しないコールバックを unsubscribe してもエラーにならないはず
	await mutation_observer.unsubscribe(test_callback)
	assert len(mutation_observer.DOM_change_callback) == 0

	# --- dom_mutation_change_detected の簡単なテストもここで行う ---
	# 再度 subscribe
	await mutation_observer.subscribe(test_callback)
	assert len(mutation_observer.DOM_change_callback) == 1

	# dom_mutation_change_detected を呼び出す
	test_changes_data = [{"tag": "DIV", "content": "New Content"}]
	test_changes_json = json.dumps(test_changes_data)
	# dom_mutation_change_detected は非同期関数なので await する
	await mutation_observer.dom_mutation_change_detected(test_changes_json)

	# コールバックが呼ばれ、変更内容が渡されているはず
	# asyncio.sleep を少し入れて、コールバックの実行を待つ（非同期処理のため）
	# しおり: dom_mutation_change_detected 内でコールバック呼び出しは await されるので sleep 不要かも？ -> いや、コールバック自体は同期なので不要
	assert callback_called is True
	assert received_changes == test_changes_data

	# unsubscribe して後始末
	await mutation_observer.unsubscribe(test_callback)
	assert len(mutation_observer.DOM_change_callback) == 0

	# リセット
	callback_called = False
	received_changes = None

	# unsubscribe した後ではコールバックは呼ばれないはず
	await mutation_observer.dom_mutation_change_detected(test_changes_json)
	# await asyncio.sleep(0.1) # しおり: 不要
	assert callback_called is False
	assert received_changes is None

	# --- テスト実行後にリストをクリア ---
	async with mutation_observer._lock:
		mutation_observer.DOM_change_callback.clear()
	# ---------------------------------

@pytest.mark.asyncio # しおり: 個別の関数にデコレータを追加
async def test_dom_mutation_change_detected_invalid_json():
	"""dom_mutation_change_detected が不正なJSONを処理できるかテスト"""
	# テスト用のコールバック関数（呼ばれないはず）
	callback_called = False
	def test_callback(changes: List[Dict[str, str]]):
		nonlocal callback_called
		callback_called = True

	# --- テスト実行前にリストをクリア ---
	async with mutation_observer._lock:
		mutation_observer.DOM_change_callback.clear()
	await mutation_observer.subscribe(test_callback)
	# ---------------------------------

	invalid_json = '{"tag": "DIV", "content": "Missing bracket"' # 不正なJSON
	
	# 不正なJSONを渡してもエラーが発生しないはず (ログにはエラーが出る)
	await mutation_observer.dom_mutation_change_detected(invalid_json)
	
	# コールバックは呼ばれないはず
	assert callback_called is False

	# --- テスト実行後にリストをクリア ---
	async with mutation_observer._lock:
		mutation_observer.DOM_change_callback.clear()
	# ---------------------------------

def test_get_add_mutation_observer_script():
	"""get_add_mutation_observer_script が正しいJavaScriptコードを生成するかテスト"""
	script = mutation_observer.get_add_mutation_observer_script()

	# スクリプト内に重要なキーワードが含まれているか確認
	assert "new MutationObserver" in script
	assert "window.dom_mutation_change_detected" in script
	assert "observer.observe(document.documentElement || document.body" in script
	# 除外IDが正しく使われているか確認
	assert "!node.closest('#playwright-highlight-container')" in script 
	# 引数で渡したIDが使われるか確認
	custom_id = "my-custom-overlay-id"
	script_custom = mutation_observer.get_add_mutation_observer_script(overlay_id=custom_id)
	assert f"!node.closest('#{custom_id}')" in script_custom

# しおり: 統合テストは Playwright のセットアップが必要なので、ここでは省略します。
# 必要であれば別途追加できます。
