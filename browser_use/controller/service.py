import asyncio
import asyncio # しおり: sleepのために追加
import json
import enum
import logging
import os
from typing import Dict, Generic, Optional, Type, TypeVar, List # しおり: List, Dict を追加

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate

# from lmnr.sdk.laminar import Laminar
from pydantic import BaseModel

from browser_use.agent.views import ActionModel, ActionResult
from browser_use.browser.context import BrowserContext
from browser_use.controller.registry.service import Registry
from browser_use.controller.views import (
	ClickElementAction,
	DoneAction,
	GoToUrlAction,
	InputTextAction,
	NoParamsAction,
	OpenTabAction,
	ScrollAction,
	SearchGoogleAction,
	SendKeysAction,
	SwitchTabAction,
)
from browser_use.utils import time_execution_sync
from browser_use.dom import mutation_observer # しおり: DOM変更監視モジュールをインポート

from PyPDF2 import PdfReader

logger = logging.getLogger(__name__)

from langchain_core.messages import HumanMessage

def build_messages_from_pdf(images_b64, goal):
	messages = [
		HumanMessage(
			content=[
				{
					"type": "text",
					"text": f"以下のPDFの画像やWebサイトのスクリーンショットを見て、抽出ゴールに関係する情報を抜き出してください。これはWebページの情報なので「Webページから情報を抽出しました」という形で報告してください。\n\n抽出ゴール: {goal}"
				}
			] + [
				{
					"type": "image_url",
					"image_url": f"data:image/png;base64,{b64}"
				} for b64 in images_b64
			]
		)
	]
	return messages

import pymupdf
from PIL import Image
import io
import base64

def convert_pdf_to_images(pdf_path, max_pages=None, max_size=1500):
	"""
	PDFを画像化し、各ページをbase64 PNGとして返す。
	
	:param pdf_path: PDFファイルパス
	:param max_pages: 最大ページ数（Noneなら全ページ）
	:param max_size: 画像の長辺サイズ（ピクセル）
	:return: base64 PNG画像のリスト（1ページにつき1つ）
	"""
	images_b64 = []
	doc = pymupdf.open(pdf_path)

	for i, page in enumerate(doc):
		if max_pages is not None and i >= max_pages:
			break

		pix = page.get_pixmap(dpi=200)  # 高品質に変換
		img = Image.open(io.BytesIO(pix.tobytes("png")))

		# 長辺を max_size に収めるようにリサイズ
		w, h = img.size
		if w > h:
			new_w = max_size
			new_h = int(h * (max_size / w))
		else:
			new_h = max_size
			new_w = int(w * (max_size / h))
		img = img.resize((new_w, new_h), Image.LANCZOS)

		# base64エンコード
		buffered = io.BytesIO()
		img.save(buffered, format="PNG")
		img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
		images_b64.append(img_b64)

	return images_b64


Context = TypeVar('Context')

class Controller(Generic[Context]):
	def __init__(
		self,
		exclude_actions: list[str] = [],
		output_model: Optional[Type[BaseModel]] = None,
		# url_action_map と common_actions は削除
	):
		# exclude_actions のみを Registry に渡す
		self.registry = Registry[Context](exclude_actions)
		# url_action_map, sorted_url_prefixes, _pending_common_actions, common_actions は削除

		"""Register all default browser actions"""
		# --- ここからアクション登録 ---
		# アクション登録時に url_patterns を指定する例 (必要に応じて追加)
		# 例: @self.registry.action(..., url_patterns=["https://example.com/*"])

		if output_model is not None:
			# Create a new model that extends the output model with success parameter
			class ExtendedOutputModel(BaseModel):  # type: ignore
				success: bool = True
				data: output_model

			@self.registry.action(
				'Complete task - with return text and if the task is finished (success=True) or not yet  completly finished (success=False), because last step is reached',
				param_model=ExtendedOutputModel,
			)
			async def done(params: ExtendedOutputModel):
				# Exclude success from the output JSON since it's an internal parameter
				output_dict = params.data.model_dump()

				# Enums are not serializable, convert to string
				for key, value in output_dict.items():
					if isinstance(value, enum.Enum):
						output_dict[key] = value.value

				return ActionResult(is_done=True, success=params.success, extracted_content=json.dumps(output_dict, ensure_ascii=False))
		else:

			@self.registry.action(
				'Complete task - with return text and if the task is finished (success=True) or not yet  completly finished (success=False), because last step is reached',
				param_model=DoneAction,
			)
			async def done(params: DoneAction):
				return ActionResult(is_done=True, success=params.success, extracted_content=params.text)

		# Basic Navigation Actions
		@self.registry.action(
			'Search the query in Google in the current tab, the query should be a search query like humans search in Google, concrete and not vague or super long. More the single most important items. ',
			param_model=SearchGoogleAction,
		)
		async def search_google(params: SearchGoogleAction, browser: BrowserContext):
			page = await browser.get_current_page()
			search_url = f'https://www.google.com/search?q={params.query}&udm=14'
			await page.goto(search_url)
			await page.wait_for_load_state()
			
			# Add this line to update the navigation history
			await browser._track_page_navigation(page, search_url)
			
			msg = f'🔍  Searched for "{params.query}" in Google'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, changed_to_new_page=True)

		@self.registry.action('Navigate to URL in the current tab', param_model=GoToUrlAction)
		async def go_to_url(params: GoToUrlAction, browser: BrowserContext):
			page = await browser.get_current_page()
			await page.goto(params.url)
			await page.wait_for_load_state()
			
			# Add this line to update the navigation history
			await browser._track_page_navigation(page, params.url)
			
			msg = f'🔗  Navigated to {params.url}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, changed_to_new_page=True)

		@self.registry.action('Go back', param_model=NoParamsAction)
		async def go_back(_: NoParamsAction, browser: BrowserContext):
			await browser.go_back()
			msg = '🔙  Navigated back'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, changed_to_new_page=True)
		
		@self.registry.action('Go forward', param_model=NoParamsAction)
		async def go_forward(_: NoParamsAction, browser: BrowserContext):
			await browser.go_forward()
			msg = '🔙  Navigated forward'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, changed_to_new_page=True)

		# wait for x seconds
		@self.registry.action('Wait for x seconds default 3')
		async def wait(seconds: int = 3):
			msg = f'🕒  Waiting for {seconds} seconds'
			logger.info(msg)
			await asyncio.sleep(seconds)
			return ActionResult(extracted_content=msg, include_in_memory=True)

		# Element Interaction Actions
		@self.registry.action('Click element', param_model=ClickElementAction)
		async def click_element(params: ClickElementAction, browser: BrowserContext):
			session = await browser.get_session()

			if params.index not in await browser.get_selector_map():
				raise Exception(f'Element with index {params.index} does not exist - retry or use alternative actions')

			element_node = await browser.get_dom_element_by_index(params.index)
			initial_pages = len(session.context.pages)

			# if element has file uploader then dont click
			if await browser.is_file_uploader(element_node):
				msg = f'Index {params.index} - has an element which opens file upload dialog. To upload files please use a specific function to upload files '
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)

			msg = None
			page_changed = False
			try:
				download_path, page_changed = await browser._click_element_node(element_node)
				if download_path:
					msg = f'💾  Downloaded file to {download_path}'
				else:
					msg = f'🖱️  Clicked button with index {params.index}: {element_node.get_all_text_till_next_clickable_element(max_depth=2)}'

				logger.info(msg)
				logger.debug(f'Element xpath: {element_node.xpath}')
				if len(session.context.pages) > initial_pages:
					new_tab_msg = 'New tab opened - switching to it'
					msg += f' - {new_tab_msg}'
					logger.info(new_tab_msg)
					await browser.switch_to_tab(len(session.context.pages) - 1)
				return ActionResult(extracted_content=msg, include_in_memory=True, changed_to_new_page=page_changed)
			except Exception as e:
				logger.warning(f'Element not clickable with index {params.index} - most likely the page changed')
				return ActionResult(error=str(e))

		@self.registry.action(
			'Input text into a input interactive element',
			param_model=InputTextAction,
		)
		async def input_text(params: InputTextAction, browser: BrowserContext, has_sensitive_data: bool = False):
			if params.index not in await browser.get_selector_map():
				raise Exception(f'Element index {params.index} does not exist - retry or use alternative actions')

			element_node = await browser.get_dom_element_by_index(params.index)
			await browser._input_text_element_node(element_node, params.text)
			if not has_sensitive_data:
				msg = f'⌨️  Input {params.text} into index {params.index}'
			else:
				msg = f'⌨️  Input sensitive data into index {params.index}'
			logger.info(msg)
			logger.debug(f'Element xpath: {element_node.xpath}')
			return ActionResult(extracted_content=msg, include_in_memory=True)

		# Tab Management Actions
		@self.registry.action('Switch tab', param_model=SwitchTabAction)
		async def switch_tab(params: SwitchTabAction, browser: BrowserContext):
			await browser.switch_to_tab(params.page_id)
			# Wait for tab to be ready
			page = await browser.get_current_page()
			await page.wait_for_load_state()
			msg = f'🔄  Switched to tab {params.page_id}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, changed_to_new_page=True)

		@self.registry.action('Open url in new tab', param_model=OpenTabAction)
		async def open_tab(params: OpenTabAction, browser: BrowserContext):
			await browser.create_new_tab(params.url)
			msg = f'🔗  Opened new tab with {params.url}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True, changed_to_new_page=True)

		# Content Actions
		@self.registry.action(
			'Extract page content to retrieve specific information from the page, e.g. all company names, a specifc description, all information about, links with companies in structured format or simply links。画像やPDFの解析もできますので、建物の外観とか食べ物の外観とかもページから調べてもらってください。',
		)
		async def extract_content(goal: str, browser: BrowserContext, page_extraction_llm: BaseChatModel):
			page = await browser.get_current_page()
			import markdownify

			# Step 1: ページのテキスト抽出
			is_pdf = False
			try:
				pdf_path, pdf_content = await self.maybe_get_content_if_pdf(browser, page)
				if pdf_content is not None:
					content = pdf_content
					is_pdf = True
				else:
					page_content = await page.content() # 先に取得
					content = markdownify.markdownify(page_content) if page_content else "" # 空チェック追加
			except Exception as e:
				import traceback
				traceback.print_exc()
				content = ""

			# Step 2: テキストを使って LLM にコンテンツ抽出させる
			prompt_template = PromptTemplate(
				input_variables=['goal', 'page'],
				template=(
					'You are given a webpage and a goal. Extract relevant content from the page in relation to the goal. '
					'If the content is insufficient or the page is mostly empty (like logins, loaders, blank pages), '
					'you must reply with: "<INSUFFICIENT_CONTENT>". Otherwise, respond in markdown.\n\n'
					'Goal: {goal}\n\nPage:\n{page}'
				)
			)

			try:
				output = await page_extraction_llm.invoke(prompt_template.format(goal=goal, page=content))
				extracted = output.content.strip()

				if "<INSUFFICIENT_CONTENT>" in extracted:
					raise ValueError("テキストに十分なコンテンツが含まれていないと判断されました。")

				msg = f'📄 Extracted from text content:\n{extracted}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)

			except Exception as e:
				logger.warning(f'Text content insufficient or error occurred: {e}')

				# Step 3: Fallback — スクショを使って LLM に渡す
				try:
					if is_pdf:
						images_base64 = convert_pdf_to_images(pdf_path)
					else:
						images_base64 = [await browser.take_screenshot(full_page=True)]
					messages = build_messages_from_pdf(images_base64, goal)
					output = page_extraction_llm.invoke(messages)

					msg = f'🖼️ Webサイトを解析して得られた解析結果：\n{output.content}'
					logger.info(msg)
					return ActionResult(extracted_content=msg, include_in_memory=True)

				except Exception as e:
					logger.error(f'Failed to extract from screenshot: {e} (content={content})')
					return ActionResult(extracted_content=f"❌ Failed to extract content from the web page {e} (content={content}")

		@self.registry.action(
			'Scroll down the page by pixel amount - if no amount is specified, scroll down one page',
			param_model=ScrollAction,
		)
		async def scroll_down(params: ScrollAction, browser: BrowserContext):
			page = await browser.get_current_page()
			if params.amount is not None:
				await page.evaluate(f'window.scrollBy(0, {params.amount});')
			else:
				await page.evaluate('window.scrollBy(0, window.innerHeight);')

			amount = f'{params.amount} pixels' if params.amount is not None else 'one page'
			msg = f'🔍  Scrolled down the page by {amount}'
			logger.info(msg)
			return ActionResult(
				extracted_content=msg,
				include_in_memory=True,
			)

		# scroll up
		@self.registry.action(
			'Scroll up the page by pixel amount - if no amount is specified, scroll up one page',
			param_model=ScrollAction,
		)
		async def scroll_up(params: ScrollAction, browser: BrowserContext):
			page = await browser.get_current_page()
			if params.amount is not None:
				await page.evaluate(f'window.scrollBy(0, -{params.amount});')
			else:
				await page.evaluate('window.scrollBy(0, -window.innerHeight);')

			amount = f'{params.amount} pixels' if params.amount is not None else 'one page'
			msg = f'🔍  Scrolled up the page by {amount}'
			logger.info(msg)
			return ActionResult(
				extracted_content=msg,
				include_in_memory=True,
			)

		# send keys
		@self.registry.action(
			'Send strings of special keys like Escape,Backspace, Insert, PageDown, Delete, Enter, Shortcuts such as `Control+o`, `Control+Shift+T` are supported as well. This gets used in keyboard.press. ',
			param_model=SendKeysAction,
		)
		async def send_keys(params: SendKeysAction, browser: BrowserContext):
			page = await browser.get_current_page()

			try:
				await page.keyboard.press(params.keys)
			except Exception as e:
				if 'Unknown key' in str(e):
					# loop over the keys and try to send each one
					for key in params.keys:
						try:
							await page.keyboard.press(key)
						except Exception as e:
							logger.debug(f'Error sending key {key}: {str(e)}')
							raise e
				else:
					raise e
			msg = f'⌨️  Sent keys: {params.keys}'
			logger.info(msg)
			return ActionResult(extracted_content=msg, include_in_memory=True)

		@self.registry.action(
			description='If you dont find something which you want to interact with, scroll to it',
		)
		async def scroll_to_text(text: str, browser: BrowserContext):  # type: ignore
			page = await browser.get_current_page()
			try:
				# Try different locator strategies
				locators = [
					page.get_by_text(text, exact=False),
					page.locator(f'text={text}'),
					page.locator(f"//*[contains(text(), '{text}')]"),
				]

				for locator in locators:
					try:
						# First check if element exists and is visible
						if await locator.count() > 0 and await locator.first.is_visible():
							await locator.first.scroll_into_view_if_needed()
							await asyncio.sleep(0.5)  # Wait for scroll to complete
							msg = f'🔍  Scrolled to text: {text}'
							logger.info(msg)
							return ActionResult(extracted_content=msg, include_in_memory=True)
					except Exception as e:
						logger.debug(f'Locator attempt failed: {str(e)}')
						continue

				msg = f"Text '{text}' not found or not visible on page"
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)

			except Exception as e:
				msg = f"Failed to scroll to text '{text}': {str(e)}"
				logger.error(msg)
				return ActionResult(error=msg, include_in_memory=True)

		@self.registry.action(
			description='Get all options from a native dropdown',
		)
		async def get_dropdown_options(index: int, browser: BrowserContext) -> ActionResult:
			"""Get all options from a native dropdown"""
			page = await browser.get_current_page()
			selector_map = await browser.get_selector_map()
			dom_element = selector_map[index]

			try:
				# Frame-aware approach since we know it works
				all_options = []
				frame_index = 0

				for frame in page.frames:
					try:
						options = await frame.evaluate(
							"""
							(xpath) => {
								const select = document.evaluate(xpath, document, null,
									XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
								if (!select) return null;

								return {
									options: Array.from(select.options).map(opt => ({
										text: opt.text, //do not trim, because we are doing exact match in select_dropdown_option
										value: opt.value,
										index: opt.index
									})),
									id: select.id,
									name: select.name
								};
							}
						""",
							dom_element.xpath,
						)

						if options:
							logger.debug(f'Found dropdown in frame {frame_index}')
							logger.debug(f'Dropdown ID: {options["id"]}, Name: {options["name"]}')

							formatted_options = []
							for opt in options['options']:
								# encoding ensures AI uses the exact string in select_dropdown_option
								encoded_text = json.dumps(opt['text'], ensure_ascii=False)
								formatted_options.append(f'{opt["index"]}: text={encoded_text}')

							all_options.extend(formatted_options)

					except Exception as frame_e:
						logger.debug(f'Frame {frame_index} evaluation failed: {str(frame_e)}')

					frame_index += 1

				if all_options:
					msg = '\n'.join(all_options)
					msg += '\nUse the exact text string in select_dropdown_option'
					logger.info(msg)
					return ActionResult(extracted_content=msg, include_in_memory=True)
				else:
					msg = 'No options found in any frame for dropdown'
					logger.info(msg)
					return ActionResult(extracted_content=msg, include_in_memory=True)

			except Exception as e:
				logger.error(f'Failed to get dropdown options: {str(e)}')
				msg = f'Error getting options: {str(e)}'
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)

		@self.registry.action(
			description='Select dropdown option for interactive element index by the text of the option you want to select',
		)
		async def select_dropdown_option(
			index: int,
			text: str,
			browser: BrowserContext,
		) -> ActionResult:
			"""Select dropdown option by the text of the option you want to select"""
			page = await browser.get_current_page()
			selector_map = await browser.get_selector_map()
			dom_element = selector_map[index]

			# Validate that we're working with a select element
			if dom_element.tag_name != 'select':
				logger.error(f'Element is not a select! Tag: {dom_element.tag_name}, Attributes: {dom_element.attributes}')
				msg = f'Cannot select option: Element with index {index} is a {dom_element.tag_name}, not a select'
				return ActionResult(extracted_content=msg, include_in_memory=True)

			logger.debug(f"Attempting to select '{text}' using xpath: {dom_element.xpath}")
			logger.debug(f'Element attributes: {dom_element.attributes}')
			logger.debug(f'Element tag: {dom_element.tag_name}')

			xpath = '//' + dom_element.xpath

			try:
				frame_index = 0
				for frame in page.frames:
					try:
						logger.debug(f'Trying frame {frame_index} URL: {frame.url}')

						# First verify we can find the dropdown in this frame
						find_dropdown_js = """
							(xpath) => {
								try {
									const select = document.evaluate(xpath, document, null,
										XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
									if (!select) return null;
									if (select.tagName.toLowerCase() !== 'select') {
										return {
											error: `Found element but it's a ${select.tagName}, not a SELECT`,
											found: false
										};
									}
									return {
										id: select.id,
										name: select.name,
										found: true,
										tagName: select.tagName,
										optionCount: select.options.length,
										currentValue: select.value,
										availableOptions: Array.from(select.options).map(o => o.text.trim())
									};
								} catch (e) {
									return {error: e.toString(), found: false};
								}
							}
						"""

						dropdown_info = await frame.evaluate(find_dropdown_js, dom_element.xpath)

						if dropdown_info:
							if not dropdown_info.get('found'):
								logger.error(f'Frame {frame_index} error: {dropdown_info.get("error")}')
								continue

							logger.debug(f'Found dropdown in frame {frame_index}: {dropdown_info}')

							# "label" because we are selecting by text
							# nth(0) to disable error thrown by strict mode
							# timeout=1000 because we are already waiting for all network events, therefore ideally we don't need to wait a lot here (default 30s)
							selected_option_values = (
								await frame.locator('//' + dom_element.xpath).nth(0).select_option(label=text, timeout=1000)
							)

							msg = f'selected option {text} with value {selected_option_values}'
							logger.info(msg + f' in frame {frame_index}')

							return ActionResult(extracted_content=msg, include_in_memory=True)

					except Exception as frame_e:
						logger.error(f'Frame {frame_index} attempt failed: {str(frame_e)}')
						logger.error(f'Frame type: {type(frame)}')
						logger.error(f'Frame URL: {frame.url}')

					frame_index += 1

				msg = f"Could not select option '{text}' in any frame"
				logger.info(msg)
				return ActionResult(extracted_content=msg, include_in_memory=True)

			except Exception as e:
				msg = f'Selection failed: {str(e)}'
				logger.error(msg)
				return ActionResult(error=msg, include_in_memory=True)

		# --- アクション登録の終わり ---
		# common_actions の設定ロジックは削除

	# --- ここからメソッド定義 (クラスレベルのインデント) ---
	def get_allowed_actions(self, url: str) -> List[str]:
		"""Get allowed actions for a given URL using the registry."""
		# Registry の get_allowed_actions を呼び出す
		return self.registry.get_allowed_actions(url)

	def get_prompt_description(self, url: str) -> str:
		"""Get a description of allowed actions for the prompt based on the URL."""
		# まず許可されたアクションを取得
		allowed_actions = self.get_allowed_actions(url)
		# 許可されたアクションに基づいてプロンプト記述を取得
		return self.registry.get_prompt_description(allowed_actions=allowed_actions)

	def create_action_model(self, url: str) -> Type[ActionModel]:
		"""Creates a Pydantic model from allowed actions based on the URL."""
		# まず許可されたアクションを取得
		allowed_actions = self.get_allowed_actions(url)
		# 許可されたアクションのみを含むモデルを作成
		return self.registry.create_action_model(include_actions=allowed_actions)

	# Register ---------------------------------------------------------------

	async def maybe_get_content_if_pdf(self, context, page):
		# すでに開いているページのURLを取得
		current_url = page.url
		suggested_filename = current_url.split("/")[-1]
		print(current_url, suggested_filename)
		unique_filename = await context._get_unique_filename(context.config.save_downloads_path, suggested_filename)
		download_path = os.path.join(context.config.save_downloads_path, unique_filename)
		# セッションを維持したまま再リクエストする
		response = await page.request.get(current_url)
		if response:
			content_type = response.headers.get("content-type", "").lower()
			if "application/pdf" in content_type:
				if response.status != 200:
					print(f"PDFの取得に失敗しました (ステータスコード: {response.status})")
					return None

				# PDFのバイナリデータを取得してファイルに書き出す
				pdf_data = await response.body()
				with open(download_path, "wb") as f:
					f.write(pdf_data)
				pdf = PdfReader(download_path)
				text = ''
				for page in pdf.pages:
					text += page.extract_text() or ''
				return download_path, text
		return None, None

	def action(self, description: str, **kwargs):
		"""Decorator for registering custom actions

		@param description: Describe the LLM what the function does (better description == better function calling)
		"""
		return self.registry.action(description, **kwargs)

	# Act --------------------------------------------------------------------

	@time_execution_sync('--act')
	async def act(
		self,
		action: ActionModel,
		browser_context: BrowserContext,
		#
		page_extraction_llm: Optional[BaseChatModel] = None,
		sensitive_data: Optional[Dict[str, str]] = None,
		available_file_paths: Optional[list[str]] = None,
		#
		context: Context | None = None,
	) -> ActionResult:
		"""Execute an action"""
		# しおり: DOM変更を一時的に保持するリストとコールバック (同期関数に変更)
		detected_changes: List[Dict[str, str]] = []
		def _dom_change_callback(changes: List[Dict[str, str]]):
			nonlocal detected_changes
			detected_changes.extend(changes)
			# 重複を除去（念のため）
			unique_changes = []
			seen = set()
			for change in detected_changes:
				change_tuple = (change.get('tag'), change.get('content'))
				if change_tuple not in seen:
					unique_changes.append(change)
					seen.add(change_tuple)
			detected_changes = unique_changes

		try:
			result = None
			action_name = ""
			params = None # params をループの外で初期化

			# action モデルから実行するアクション名とパラメータを取得
			action_data = action.model_dump(exclude_unset=True)
			if not action_data:
				return ActionResult(error="No action specified.") # アクションが指定されていない場合

			# 通常、action_data には1つのキーしかないはず
			action_name = next(iter(action_data))
			params = action_data[action_name]

			if params is not None:
					# --- URLベースのアクションバリデーション (Registry を使用) ---
					current_page = await browser_context.get_current_page()
					current_url = current_page.url
					# Registry から許可されたアクションリストを取得
					allowed_actions = self.get_allowed_actions(current_url)

					if action_name not in allowed_actions:
						error_msg = f"Action '{action_name}' is not allowed for the current URL: {current_url}. Allowed actions: {allowed_actions}"
						logger.error(error_msg)
						return ActionResult(error=error_msg, include_in_memory=True) # エラーを返す
					# --- バリデーション終了 ---

					# しおり: アクション実行前にDOM監視を開始
					await mutation_observer.subscribe(_dom_change_callback)
					try: # しおり: アクション実行部分を try で囲む
						# with Laminar.start_as_current_span(
						# 	name=action_name,
					# 	input={ # しおり: インデント修正
					# 		'action': action_name,
					# 		'params': params,
					# 	},
					# 	span_type='TOOL',
					# ):
						result = await self.registry.execute_action(
							action_name,
							params,
							browser=browser_context,
							page_extraction_llm=page_extraction_llm,
							sensitive_data=sensitive_data,
							available_file_paths=available_file_paths,
							context=context,
						)
					finally: # しおり: try に対応する finally (タブインデント)
							# しおり: アクション実行後に少し待ってからDOM監視を停止
							await asyncio.sleep(0.5) # 変更が反映されるのを待つ
							await mutation_observer.unsubscribe(_dom_change_callback)

					# Laminar.set_span_output(result)

			# しおり: ActionResultにDOM変更情報を追加する（インデントを for ループのレベルに戻す - タブ文字使用）
			if isinstance(result, ActionResult):
				result.dom_changes = detected_changes # 次のステップで有効化
				if detected_changes:
					# action_name が未定義の場合があるため、チェックを追加
					log_action_name = action_name if action_name else "Unknown Action"
					logger.info(f"DOM changes detected during action {log_action_name}: {detected_changes}")
					# 必要であれば、既存の extracted_content に情報を追記
					# result.extracted_content += f"\nDOM Changes: {json.dumps(detected_changes, ensure_ascii=False)}"

			if isinstance(result, str): # しおり: インデント修正 (タブ文字使用)
				return ActionResult(extracted_content=result)
			elif isinstance(result, ActionResult): # しおり: インデント修正 (タブ文字使用)
				return result
			elif result is None: # しおり: インデント修正 (タブ文字使用)
				# ループが一度も実行されなかった場合 (action.model_dump が空など)
				return ActionResult()
			else: # しおり: インデント修正 (タブ文字使用)
				raise ValueError(f'Invalid action result type: {type(result)} of {result}')
			# return ActionResult() # しおり: この行は不要 (ループ後に到達しないため削除)
		except Exception as e:
			raise e
