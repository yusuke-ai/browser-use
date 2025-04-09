# browser_use/dom/mutation_observer.py
import asyncio
import json
import logging
from typing import Callable, List, Dict, Any

logger = logging.getLogger(__name__)

# グローバル変数としてコールバックリストを保持（Agent-Eの設計を踏襲）
# 本来はクラスに持たせる方が良いかもしれませんが、まずは元の設計に合わせます
DOM_change_callback: List[Callable[[List[Dict[str, Any]]], None]] = []
_lock = asyncio.Lock()

async def subscribe(callback: Callable[[List[Dict[str, Any]]], None]):
    """DOM変更通知を受け取るコールバック関数を登録します。"""
    async with _lock:
        if callback not in DOM_change_callback:
            DOM_change_callback.append(callback)
            logger.debug(f"DOM mutation observer subscribed by: {callback.__name__}")

async def unsubscribe(callback: Callable[[List[Dict[str, Any]]], None]):
    """登録されたコールバック関数を解除します。"""
    async with _lock:
        if callback in DOM_change_callback:
            DOM_change_callback.remove(callback)
            logger.debug(f"DOM mutation observer unsubscribed by: {callback.__name__}")

async def dom_mutation_change_detected(changes_json: str):
    """
    JavaScriptから呼び出される関数。
    検知されたDOM変更情報をJSON文字列で受け取り、登録されたコールバックに通知します。
    """
    try:
        changes_detected: List[Dict[str, str]] = json.loads(changes_json)
        if changes_detected:
            # logger.info(f"DOM mutation detected: {changes_detected}")
            # 現在登録されているコールバックのコピーに対して通知（ループ中の変更に対応）
            callbacks_to_notify = []
            async with _lock:
                callbacks_to_notify = DOM_change_callback[:]
            
            for callback in callbacks_to_notify:
                try:
                    # コールバックが非同期関数の場合
                    if asyncio.iscoroutinefunction(callback):
                        await callback(changes_detected)
                    # 同期関数の場合（非推奨だが念のため）
                    else:
                        callback(changes_detected)
                except Exception as e:
                    logger.error(f"Error executing DOM mutation callback {callback.__name__}: {e}", exc_info=True)
    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON from dom_mutation_change_detected: {changes_json}")
    except Exception as e:
        logger.error(f"Error in dom_mutation_change_detected: {e}", exc_info=True)

def get_add_mutation_observer_script(overlay_id: str = "playwright-highlight-container") -> str: # しおり: デフォルト引数を修正
    """
    MutationObserverをページに追加し、DOM変更を監視して
    window.dom_mutation_change_detected を呼び出すJavaScriptコードを返します。
    """
    # センパイとの会話履歴にあったJavaScriptコードをベースに作成
    # overlay_id を引数で受け取り、無視する要素の判定に使う
    return f"""
    (() => {{
        if (window.mutationObserverAttached) {{
            console.log("Mutation observer already attached.");
            return;
        }}
        console.log("Attaching mutation observer...");

        // XPathを取得するヘルパー関数
        function getXPathForElement(element) {{
            if (!element) return '';
            
            // 要素がdocument.bodyの場合は特別扱い
            if (element === document.body) return '/html/body';
            
            // 親要素のXPathを取得（再帰）
            let parentXPath = '';
            if (element.parentNode && element.parentNode !== document) {{
                parentXPath = getXPathForElement(element.parentNode);
            }}
            
            // 現在の要素のタグ名
            const tagName = element.tagName.toLowerCase();
            
            // 同じタグ名の兄弟要素の中での位置を計算
            let count = 1;
            let sibling = element.previousElementSibling;
            while (sibling) {{
                if (sibling.tagName.toLowerCase() === tagName) {{
                    count++;
                }}
                sibling = sibling.previousElementSibling;
            }}
            
            // XPathを構築
            return `${{parentXPath}}/${{tagName}}[${{count}}]`;
        }}

        const observer = new MutationObserver((mutationsList, observer) => {{
            let changes_detected = []; // 変更情報を格納する配列
            for(let mutation of mutationsList) {{
                // 1. 子要素リストの変更（要素の追加・削除）があった場合
                if (mutation.type === 'childList') {{
                    let allAddedNodes = mutation.addedNodes; // 追加されたノードのリストを取得
                    for(let node of allAddedNodes) {{
                        // スクリプトタグなどを除外し、表示されていて内容がある要素のみを対象
                        // overlay_id を持つ要素も除外
                        if(node.nodeType === Node.ELEMENT_NODE && node.tagName && !['SCRIPT', 'NOSCRIPT', 'STYLE'].includes(node.tagName) && !node.closest('#{overlay_id}')) {{
                            // 可視性チェック（簡易版：スタイルが none でないか）
                            let style = window.getComputedStyle(node);
                            let isVisible = style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                            let content = node.innerText?.trim(); // 要素内のテキスト内容を取得
                            if(isVisible && content){{
                                // XPathとHTMLを取得
                                const xpath = getXPathForElement(node);
                                const html = node.outerHTML;
                                
                                // タグ名、内容、XPath、HTMLをオブジェクトにして配列に追加
                                changes_detected.push({{
                                    type: 'added',
                                    tag: node.tagName,
                                    content: content,
                                    xpath: xpath,
                                    html: html
                                }});
                            }}
                        }}
                    }}
                }}
                // 2. 要素内のテキストデータ変更があった場合
                else if (mutation.type === 'characterData') {{
                    let node = mutation.target; // 変更があったテキストノード
                    let parentElement = node.parentElement;
                    // 親要素が存在し、スクリプトタグなどを除外、overlay_id も除外
                    if(parentElement && parentElement.tagName && !['SCRIPT', 'NOSCRIPT', 'STYLE'].includes(parentElement.tagName) && !parentElement.closest('#{overlay_id}')) {{
                        // 可視性チェック（簡易版）
                        let style = window.getComputedStyle(parentElement);
                        let isVisible = style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                        let content = node.data?.trim(); // 変更後のテキスト内容を取得
                        // 表示されていて内容があり、まだリストに追加されていない場合
                        if(isVisible && content){{
                            // 同じ内容がすでに追加されていないかチェック（characterDataは連続して発生することがあるため）
                            if(!changes_detected.some(change => change.tag === parentElement.tagName && change.content === content)) {{
                                // XPathとHTMLを取得
                                const xpath = getXPathForElement(parentElement);
                                const html = parentElement.outerHTML;
                                
                                // タグ名、内容、XPath、HTMLをオブジェクトにして配列に追加
                                changes_detected.push({{
                                    type: 'modified',
                                    tag: parentElement.tagName,
                                    content: content,
                                    xpath: xpath,
                                    html: html
                                }});
                            }}
                        }}
                    }}
                }}
            }}
            // 重複を除去（同じ要素が複数回追加/変更として検知される場合があるため）
            const unique_changes = changes_detected.filter((change, index, self) =>
                index === self.findIndex((c) => (
                    c.tag === change.tag && c.content === change.content
                ))
            );

            // 変更があった場合のみ、Python側の関数を呼び出す
            if(unique_changes.length > 0) {{
                // console.log("DOM changes detected:", unique_changes);
                // Python側の関数が存在するか確認してから呼び出す
                if (typeof window.dom_mutation_change_detected === 'function') {{
                    window.dom_mutation_change_detected(JSON.stringify(unique_changes));
                }} else {{
                    console.error("window.dom_mutation_change_detected is not defined.");
                }}
            }}
        }});

        // 監視を開始
        observer.observe(document.documentElement || document.body, {{subtree: true, childList: true, characterData: true}});
        window.mutationObserverAttached = true; // 監視が開始されたことを記録
        console.log("Mutation observer attached and observing.");

        // ページ離脱時に監視を停止する処理（オプション）
        // window.addEventListener('beforeunload', () => {{
        //     observer.disconnect();
        //     window.mutationObserverAttached = false;
        //     console.log("Mutation observer disconnected.");
        // }});
    }})();
    """
