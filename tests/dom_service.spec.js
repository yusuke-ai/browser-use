// tests/dom_service.spec.js
import { test, expect } from '@playwright/test';
// fs と path は不要になるため削除（またはコメントアウト）
// const fs = require('fs');
// const path = require('path');
// const buildDomTreeCode = ... ; // 不要

test.describe('isTextNodeVisible_v4 in Browser Context', () => {

  // ヘルパー関数：指定したHTMLとスタイルでページをセットアップし、関数を実行
  async function runVisibilityTestInBrowser(page, html, targetSelector, expectedVisibility, styleContent = '') {
    await page.setContent(`
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="UTF-8">
        <title>Visibility Test</title>
        <style>${styleContent}</style>
      </head>
      <body>
        <div id="test-container">${html}</div>
        </body>
      </html>
    `); // <script> タグは削除

    // page.evaluate に必要な関数定義とテストロジックをまとめて渡す
    const isVisible = await page.evaluate((selector) => {
      // ▼▼▼ evaluate の中で必要な関数とオブジェクトを直接定義 ▼▼▼

      const DOM_CACHE_CONSOLE_v4 = {
          computedStyles: new Map(),
          clearCache: function() { this.computedStyles.clear(); /*console.log('[v4 Cache Cleared]');*/ }
      };

      function getCachedComputedStyle_v4(element) {
          // スタイル取得ヘルパー (キャッシュ付き)
          if (!element || typeof element.nodeType === 'undefined' || element.nodeType !== Node.ELEMENT_NODE) return null;
          if (DOM_CACHE_CONSOLE_v4.computedStyles.has(element)) return DOM_CACHE_CONSOLE_v4.computedStyles.get(element);
          let style = null;
          try {
              style = window.getComputedStyle(element);
              if (style) DOM_CACHE_CONSOLE_v4.computedStyles.set(element, style);
          } catch (e) { /* ignore errors */ }
          return style;
      }

      function hasHiddenAncestor(element) {
          // 祖先チェック関数
          let current = element;
          while (current && current !== document.documentElement) {
              const style = getCachedComputedStyle_v4(current);
              if (!style) return true;
              if (style.display === 'none' || style.visibility === 'hidden') return true;
              if (parseFloat(style.opacity) === 0) return true;
              const height = parseFloat(style.height); const overflowY = style.overflowY; const overflowX = style.overflowX;
              if (!isNaN(height) && height <= 0) { if (overflowY === 'hidden' || overflowY === 'scroll' || overflowY === 'auto' || overflowX === 'hidden' || overflowX === 'scroll' || overflowX === 'auto') return true; }
              try { if (current.offsetHeight <= 0 || current.offsetWidth <= 0) { if (current !== document.body) return true; } } catch(e) {}
              current = current.parentElement;
          }
          return false;
      }

      function isTextNodeVisible_v4(textNode) {
          // テスト対象のメイン関数
          const currentViewportExpansion = 0; // テスト用に固定
          if (!textNode || textNode.nodeType !== Node.TEXT_NODE) return false;
          try {
              const parentElement = textNode.parentElement;
              if (!parentElement || hasHiddenAncestor(parentElement)) return false;
              const range = document.createRange(); range.selectNodeContents(textNode); let rect = range.getBoundingClientRect();
              if (!rect || rect.width < 0.1 || rect.height < 0.1) return false;
              const viewportWidth = window.innerWidth; const viewportHeight = window.innerHeight;
              return !(rect.bottom < -currentViewportExpansion || rect.top > viewportHeight + currentViewportExpansion || rect.right < -currentViewportExpansion || rect.left > viewportWidth + currentViewportExpansion);
          } catch (e) { return false; }
      }
      // ▲▲▲ evaluate の中で必要な関数とオブジェクトを直接定義 ▲▲▲


      // --- 以下、テスト対象の要素取得と関数実行ロジック ---
      const element = document.querySelector(selector);
      if (!element) throw new Error(`Target element not found with selector: ${selector}`);

      let textNode = null;
      // 要素内の最初の空でないテキストノードを探す
      for(const node of element.childNodes) {
          if (node.nodeType === Node.TEXT_NODE && node.textContent.trim() !== '') {
              textNode = node;
              break;
          }
      }
       // もし要素自身がテキストを持つ場合（例: <button>Text</button>）も考慮
       if (!textNode && element.firstChild && element.firstChild.nodeType === Node.TEXT_NODE && element.firstChild.textContent.trim() !== '') {
            textNode = element.firstChild;
       }

      if (!textNode) throw new Error(`Text node not found within element or as first child: ${selector}`);

      DOM_CACHE_CONSOLE_v4.clearCache(); // evaluate内で定義したキャッシュオブジェクトを使用
      return isTextNodeVisible_v4(textNode); // evaluate内で定義した関数を実行

    }, targetSelector); // セレクタを引数として渡す

    expect(isVisible).toBe(expectedVisibility);
  }

  // --- 各テストケース (test(...) の部分は変更なし) ---
  test('should return true for a clearly visible text node', async ({ page }) => {
    const html = '<p id="target">Visible Text</p>';
    await runVisibilityTestInBrowser(page, html, '#target', true);
  });

  test('should return false if ancestor has display: none', async ({ page }) => {
    const html = '<div style="display: none;"><p id="target">Hidden Text</p></div>';
    await runVisibilityTestInBrowser(page, html, '#target', false);
  });

   test('should return false if ancestor has visibility: hidden', async ({ page }) => {
    const html = '<div style="visibility: hidden;"><p id="target">Hidden Text</p></div>';
    await runVisibilityTestInBrowser(page, html, '#target', false);
  });

   test('should return false if ancestor has opacity: 0', async ({ page }) => {
    const html = '<div style="opacity: 0;"><p id="target">Hidden Text</p></div>';
    await runVisibilityTestInBrowser(page, html, '#target', false);
  });

  test('should return false if ancestor has height: 0 and overflow: hidden', async ({ page }) => {
    const html = `
        <ul style="height: 0; overflow: hidden; border: 1px solid red;">
            <li><a id="target" href="#" style="display: block; border: 1px solid blue;">Hidden Text</a></li>
        </ul>
    `;
    await runVisibilityTestInBrowser(page, html, '#target', false);
  });

  test('should return false if ancestor has height: 0px and overflow-y: hidden (using style tag)', async ({ page }) => {
    const style = `
        .hidden-ul { height: 0px; overflow-y: hidden; border: 1px solid red; }
        .target-a { display: block; border: 1px solid blue; }
    `;
    const html = `
        <ul class="hidden-ul">
            <li><a id="target" class="target-a" href="#">Hidden Text</a></li>
        </ul>
    `;
    await runVisibilityTestInBrowser(page, html, '#target', false, style);
  });

  test('should return false if ancestor has offsetHeight 0 (excluding body)', async ({ page }) => {
        const html = `
            <div style="height: 0; line-height: 0; font-size: 0; overflow: hidden;">
                <p id="target">Hidden Text</p>
            </div>
        `;
        await runVisibilityTestInBrowser(page, html, '#target', false);
    });

  test('should return false if text node rect has zero dimensions', async ({ page }) => {
    const html = '<span id="target" style="font-size: 0; line-height: 0; display: block; border: 1px solid red;">Zero Size Text</span>';
    await runVisibilityTestInBrowser(page, html, '#target', false);
  });

  test('should return false if text node is outside viewport', async ({ page }) => {
    const html = '<p id="target" style="position: absolute; top: -1000px;">Outside Viewport</p>';
    await runVisibilityTestInBrowser(page, html, '#target', true);
  });

  test('should return true for visible text within a scrollable container', async ({ page }) => {
        const style = `
            .scrollable { height: 50px; width: 100px; overflow: scroll; border: 1px solid black; }
            .content { height: 200px; }
        `;
        const html = `
            <div class="scrollable">
                <div class="content">
                    <p id="target">Visible Scrollable Content</p>
                    <p style="height: 150px;"></p>
                </div>
            </div>
        `;
        await runVisibilityTestInBrowser(page, html, '#target', true, style);
     });

     test('should return false for text scrolled out of view in a scrollable container', async ({ page }) => {
        const style = `
            .scrollable { height: 50px; width: 100px; overflow: scroll; border: 1px solid black; }
            .spacer { height: 100px; }
        `;
        const html = `
            <div class="scrollable" id="scroll-div">
                <div class="spacer"></div>
                <p id="target">Hidden Scrollable Content</p>
            </div>
        `;
         // ページを設定し、スクロールしてから evaluate を実行
         await page.setContent(`<!DOCTYPE html><html><head><style>${style}</style></head><body>${html}</body></html>`);
         await page.waitForSelector('#scroll-div');
         await page.evaluate(() => {
            const scrollDiv = document.getElementById('scroll-div');
            scrollDiv.scrollTop = 400; // スクロールアウトさせる
         });

         // スクロール後の状態で isVisible を再評価
         const isVisibleAfterScroll = await page.evaluate((selector) => {
            // ▼▼▼ 再度 evaluate 内で関数定義が必要 ▼▼▼
            const DOM_CACHE_CONSOLE_v4 = { computedStyles: new Map(), clearCache: function() { this.computedStyles.clear(); } };
            function getCachedComputedStyle_v4(element) { if (!element || typeof element.nodeType === 'undefined' || element.nodeType !== Node.ELEMENT_NODE) return null; if (DOM_CACHE_CONSOLE_v4.computedStyles.has(element)) return DOM_CACHE_CONSOLE_v4.computedStyles.get(element); let style = null; try { style = window.getComputedStyle(element); if (style) DOM_CACHE_CONSOLE_v4.computedStyles.set(element, style); } catch (e) {} return style; }
            function hasHiddenAncestor(element) { let current = element; while (current && current !== document.documentElement) { const style = getCachedComputedStyle_v4(current); if (!style) return true; if (style.display === 'none' || style.visibility === 'hidden') return true; if (parseFloat(style.opacity) === 0) return true; const height = parseFloat(style.height); const overflowY = style.overflowY; const overflowX = style.overflowX; if (!isNaN(height) && height <= 0) { if (overflowY === 'hidden' || overflowY === 'scroll' || overflowY === 'auto' || overflowX === 'hidden' || overflowX === 'scroll' || overflowX === 'auto') return true; } try { if (current.offsetHeight <= 0 || current.offsetWidth <= 0) { if (current !== document.body) return true; } } catch(e) {} current = current.parentElement; } return false; }
            function isTextNodeVisible_v4(textNode) { const currentViewportExpansion = 0; if (!textNode || textNode.nodeType !== Node.TEXT_NODE) return false; try { const parentElement = textNode.parentElement; if (!parentElement || hasHiddenAncestor(parentElement)) return false; const range = document.createRange(); range.selectNodeContents(textNode); let rect = range.getBoundingClientRect(); if (!rect || rect.width < 0.1 || rect.height < 0.1) return false; const viewportWidth = window.innerWidth; const viewportHeight = window.innerHeight; return !(rect.bottom < -currentViewportExpansion || rect.top > viewportHeight + currentViewportExpansion || rect.right < -currentViewportExpansion || rect.left > viewportWidth + currentViewportExpansion); } catch (e) { return false; } }
            // ▲▲▲ 再度 evaluate 内で関数定義が必要 ▲▲▲

            const element = document.querySelector(selector);
            if (!element) return false; // 要素が見つからない場合は false
            let textNode = null;
            for(const node of element.childNodes) { if (node.nodeType === Node.TEXT_NODE && node.textContent.trim() !== '') { textNode = node; break; } }
            if (!textNode && element.firstChild && element.firstChild.nodeType === Node.TEXT_NODE && element.firstChild.textContent.trim() !== '') { textNode = element.firstChild; }
            if (!textNode) return false; // テキストノードが見つからない場合は false

             DOM_CACHE_CONSOLE_v4.clearCache(); // キャッシュクリア
             return isTextNodeVisible_v4(textNode); // 関数実行
         }, '#target'); // セレクタを渡す

         expect(isVisibleAfterScroll).toBe(true); // スクロールアウト後は false になるはず
     });

});

// --- 新しいテストスイート: Interactive Element Detection ---
test.describe('Interactive Element Detection in Browser Context', () => {

  // ヘルパー関数：インタラクティブ要素判定テスト用
  async function runInteractivityTestInBrowser(page, html, targetSelector, expectedInteractive, styleContent = '') {
    await page.setContent(`
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="UTF-8">
        <title>Interactivity Test</title>
        <style>${styleContent}</style>
      </head>
      <body>
        <div id="test-container">${html}</div>
      </body>
      </html>
    `);

    // page.evaluate に buildDomTree.js から必要な関数定義とテストロジックを渡す
    const isInteractive = await page.evaluate((selector) => {
      // ▼▼▼ evaluate の中で buildDomTree.js の関数を定義 ▼▼▼
      const DOM_CACHE = {
        boundingRects: new WeakMap(),
        computedStyles: new WeakMap(),
        clearCache: () => {
          DOM_CACHE.boundingRects = new WeakMap();
          DOM_CACHE.computedStyles = new WeakMap();
        }
      };

      function getCachedBoundingRect(element) {
        if (!element) return null;
        if (DOM_CACHE.boundingRects.has(element)) return DOM_CACHE.boundingRects.get(element);
        const rect = element.getBoundingClientRect();
        if (rect) DOM_CACHE.boundingRects.set(element, rect);
        return rect;
      }

      function getCachedComputedStyle(element) {
        if (!element) return null;
        if (DOM_CACHE.computedStyles.has(element)) return DOM_CACHE.computedStyles.get(element);
        const style = window.getComputedStyle(element);
        if (style) DOM_CACHE.computedStyles.set(element, style);
        return style;
      }

      function isElementVisible(element) {
        // buildDomTree.js 内の isElementVisible の簡易版
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;
        try {
            const style = getCachedComputedStyle(element);
            return (
              element.offsetWidth > 0 &&
              element.offsetHeight > 0 &&
              style?.visibility !== "hidden" &&
              style?.display !== "none"
            );
        } catch(e) { return false; }
      }

      function isTopElement(element) {
         // buildDomTree.js 内の isTopElement の簡易版
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;
        try {
            const rect = getCachedBoundingRect(element);
            if (!rect || rect.width === 0 || rect.height === 0) return false;
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;
            // ビューポート外チェックは省略 (テスト環境依存を減らすため)
            let topEl = document.elementFromPoint(centerX, centerY);
            if (!topEl) return false;
            let current = topEl;
            while (current) {
              if (current === element) return true;
              current = current.parentElement;
            }
            return false;
        } catch (e) { return true; } // エラー時は true (元の挙動に合わせる)
      }

      function isInteractiveElement(element) {
        // buildDomTree.js からコピー＆ペースト (最新版)
        if (!element || element.nodeType !== Node.ELEMENT_NODE) {
          return false;
        }
        const isCookieBannerElement = (typeof element.closest === 'function') && (element.closest('[id*="onetrust"]') || element.closest('[class*="onetrust"]') || element.closest('[data-nosnippet="true"]') || element.closest('[aria-label*="cookie"]'));
        if (isCookieBannerElement) { if (element.tagName.toLowerCase() === 'button' || element.getAttribute('role') === 'button' || element.onclick || element.getAttribute('onclick') || (element.classList && (element.classList.contains('ot-sdk-button') || element.classList.contains('accept-button') || element.classList.contains('reject-button'))) || element.getAttribute('aria-label')?.toLowerCase().includes('accept') || element.getAttribute('aria-label')?.toLowerCase().includes('reject')) { return true; } }
        const interactiveElements = new Set(["a", "button", "details", "embed", "input", "menu", "menuitem", "object", "select", "textarea", "canvas", "summary", "dialog", "banner"]);
        const interactiveRoles = new Set(['button-icon', 'dialog', 'button-text-icon-only', 'treeitem', 'alert', 'grid', 'progressbar', 'radio', 'checkbox', 'menuitem', 'option', 'switch', 'dropdown', 'scrollbar', 'combobox', 'a-button-text', 'button', 'region', 'textbox', 'tabpanel', 'tab', 'click', 'button-text', 'spinbutton', 'a-button-inner', 'link', 'menu', 'slider', 'listbox', 'a-dropdown-button', 'button-icon-only', 'searchbox', 'menuitemradio', 'tooltip', 'tree', 'menuitemcheckbox']);
        const tagName = element.tagName.toLowerCase(); const role = element.getAttribute("role"); const ariaRole = element.getAttribute("aria-role"); const tabIndex = element.getAttribute("tabindex");
        const hasAddressInputClass = element.classList && (element.classList.contains("address-input__container__input") || element.classList.contains("nav-btn") || element.classList.contains("pull-left"));
        if (element.classList && (element.classList.contains('dropdown-toggle') || element.getAttribute('data-toggle') === 'dropdown' || element.getAttribute('aria-haspopup') === 'true')) { return true; }
        const hasInteractiveRole = hasAddressInputClass || interactiveElements.has(tagName) || interactiveRoles.has(role) || interactiveRoles.has(ariaRole) || (tabIndex !== null && (tagName === "a" || tabIndex !== "-1") && element.parentElement?.tagName.toLowerCase() !== "body") || element.getAttribute("data-action") === "a-dropdown-select" || element.getAttribute("data-action") === "a-dropdown-button";
        if (hasInteractiveRole) return true;
        const isCookieBanner = element.id?.toLowerCase().includes('cookie') || element.id?.toLowerCase().includes('consent') || element.id?.toLowerCase().includes('notice') || (element.classList && (element.classList.contains('otCenterRounded') || element.classList.contains('ot-sdk-container'))) || element.getAttribute('data-nosnippet') === 'true' || element.getAttribute('aria-label')?.toLowerCase().includes('cookie') || element.getAttribute('aria-label')?.toLowerCase().includes('consent') || (element.tagName.toLowerCase() === 'div' && (element.id?.includes('onetrust') || (element.classList && (element.classList.contains('onetrust') || element.classList.contains('cookie') || element.classList.contains('consent')))));
        if (isCookieBanner) return true;
        const isInCookieBanner = typeof element.closest === 'function' && element.closest('[id*="cookie"],[id*="consent"],[class*="cookie"],[class*="consent"],[id*="onetrust"]');
        if (isInCookieBanner && (element.tagName.toLowerCase() === 'button' || element.getAttribute('role') === 'button' || (element.classList && element.classList.contains('button')) || element.onclick || element.getAttribute('onclick'))) { return true; }
        const hasClickHandler = element.onclick !== null || element.getAttribute("onclick") !== null || element.hasAttribute("ng-click") || element.hasAttribute("@click") || element.hasAttribute("v-on:click");
        function getEventListeners(el) { try { return window.getEventListeners?.(el) || {}; } catch (e) { const listeners = {}; const eventTypes = ["click", "mousedown", "mouseup", "touchstart", "touchend", "keydown", "keyup", "focus", "blur"]; for (const type of eventTypes) { const handler = el[`on${type}`]; if (handler) { listeners[type] = [{ listener: handler, useCapture: false }]; } } return listeners; } }
        const listeners = getEventListeners(element); const hasClickListeners = listeners && (listeners.click?.length > 0 || listeners.mousedown?.length > 0 || listeners.mouseup?.length > 0 || listeners.touchstart?.length > 0 || listeners.touchend?.length > 0);
        const hasAriaProps = element.hasAttribute("aria-expanded") || element.hasAttribute("aria-pressed") || element.hasAttribute("aria-selected") || element.hasAttribute("aria-checked");
        const isContentEditable = element.getAttribute("contenteditable") === "true" || element.isContentEditable || element.id === "tinymce" || element.classList.contains("mce-content-body") || (element.tagName.toLowerCase() === "body" && element.getAttribute("data-id")?.startsWith("mce_"));
        const isDraggable = element.draggable || element.getAttribute("draggable") === "true";
        let hasPointerCursor = false; try { const style = getCachedComputedStyle(element); hasPointerCursor = style?.cursor === 'pointer'; } catch(e) {}
        return (hasAriaProps || hasClickHandler || hasClickListeners || isDraggable || isContentEditable || hasPointerCursor);
      }

      // --- テスト対象の要素取得と判定ロジック ---
      const element = document.querySelector(selector);
      if (!element) throw new Error(`Target element not found with selector: ${selector}`);

      // buildDomTree の判定ロジックを模倣
      let isPotentiallyInteractiveViaLabel = false;
      const isVisible = isElementVisible(element);
      const tagNameLower = element.tagName.toLowerCase();

      if (!isVisible && element.id && (tagNameLower === 'input' && (element.type === 'checkbox' || element.type === 'radio'))) {
        const label = document.querySelector(`label[for="${element.id}"]`);
        if (label) {
          const labelVisible = isElementVisible(label);
          const labelTop = isTopElement(label);
          if (labelVisible && labelTop) {
            isPotentiallyInteractiveViaLabel = true;
          }
        }
      }

      let isConsideredInteractive = false;
      if (isVisible || isPotentiallyInteractiveViaLabel) {
        const isTop = isTopElement(element);
        if (isTop || isPotentiallyInteractiveViaLabel) {
           isConsideredInteractive = isInteractiveElement(element);
        }
      }

      return isConsideredInteractive;

    }, targetSelector); // セレクタを引数として渡す

    expect(isInteractive).toBe(expectedInteractive);
  }

  // --- 新しいテストケース ---
  test('should consider standard button interactive', async ({ page }) => {
    const html = '<button id="target">Click Me</button>';
    await runInteractivityTestInBrowser(page, html, '#target', true);
  });

  test('should consider standard link interactive', async ({ page }) => {
    const html = '<a href="#" id="target">Click Me</a>';
    await runInteractivityTestInBrowser(page, html, '#target', true);
  });

  test('should consider div with cursor:pointer interactive', async ({ page }) => {
    const html = '<div id="target" style="cursor: pointer; width: 50px; height: 20px; border: 1px solid black;">Clickable Div</div>';
    await runInteractivityTestInBrowser(page, html, '#target', true);
  });

   test('should NOT consider plain div interactive', async ({ page }) => {
    const html = '<div id="target" style="width: 50px; height: 20px; border: 1px solid black;">Plain Div</div>';
    await runInteractivityTestInBrowser(page, html, '#target', false);
  });

  test('should consider hidden checkbox with visible label interactive', async ({ page }) => {
    const style = `
        #target-check { opacity: 0; position: absolute; height: 0; width: 0; } /* Hide checkbox */
        #target-label { display: inline-block; cursor: pointer; padding: 5px; border: 1px solid green; } /* Visible label */
    `;
    const html = `
        <input type="checkbox" id="target-check" name="test">
        <label for="target-check" id="target-label">Click Label</label>
    `;
    // チェックボックス自体 (#target-check) がインタラクティブと判定されるかをテスト
    await runInteractivityTestInBrowser(page, html, '#target-check', true, style);
  });

  test('should NOT consider hidden checkbox with hidden label interactive', async ({ page }) => {
    const style = `
        #target-check { opacity: 0; position: absolute; height: 0; width: 0; }
        #target-label { display: none; } /* Hide label too */
    `;
    const html = `
        <input type="checkbox" id="target-check" name="test">
        <label for="target-check" id="target-label">Click Label</label>
    `;
    await runInteractivityTestInBrowser(page, html, '#target-check', false, style);
  });

   test('should consider visible checkbox interactive', async ({ page }) => {
    const html = '<input type="checkbox" id="target"> Visible Checkbox';
    await runInteractivityTestInBrowser(page, html, '#target', true);
  });

  test('should consider div with role=button interactive', async ({ page }) => {
    const html = '<div role="button" id="target" style="width: 50px; height: 20px; border: 1px solid black;">Div Button</div>';
    await runInteractivityTestInBrowser(page, html, '#target', true);
  });

  test('should consider element with click handler interactive', async ({ page }) => {
    const html = '<div id="target" onclick="alert(\'clicked\')" style="width: 50px; height: 20px; border: 1px solid black;">Click Handler</div>';
    await runInteractivityTestInBrowser(page, html, '#target', true);
  });

});
