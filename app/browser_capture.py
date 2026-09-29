"""浏览器错误收集模块 - 使用 Playwright 捕获 Console/Network 错误与可交互元素"""
import base64
import os
import re
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# 采集页面结构摘要(标题/标题层级/表单概览),供 DOM 文本感知模式替代截图
_COLLECT_PAGE_DIGEST_JS = r"""
() => {
    const headings = Array.from(document.querySelectorAll('h1, h2, h3'))
        .map(h => h.tagName.toLowerCase() + ': ' + (h.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60))
        .filter(t => t.length > 4)
        .slice(0, 10);
    const forms = Array.from(document.querySelectorAll('form')).map((form, i) => {
        const fields = Array.from(form.querySelectorAll('input, select, textarea'))
            .map(el => {
                const tag = el.tagName.toLowerCase();
                const type = (el.getAttribute('type') || '').toLowerCase();
                const name = el.getAttribute('name') || el.getAttribute('placeholder') || el.getAttribute('aria-label') || '';
                return tag + (type ? '[' + type + ']' : '') + (name ? ' ' + name : '');
            })
            .slice(0, 8);
        return '表单' + (i + 1) + ': ' + (fields.join(', ') || '无字段');
    });
    return {
        title: (document.title || '').slice(0, 80),
        headings: headings,
        forms: forms
    };
}
"""

# 采集页面可交互元素并注入 data-agent-id 标记(每步决策前重新采集)
# 视口内元素优先排序,降低长页面下的信息噪音
_COLLECT_ELEMENTS_JS = r"""
() => {
    const selector = [
        'a[href]', 'button', 'input', 'select', 'textarea',
        '[role="button"]', '[role="link"]', '[role="checkbox"]', '[role="radio"]',
        '[role="tab"]', '[role="menuitem"]', '[role="switch"]', '[role="combobox"]',
        '[onclick]', '[contenteditable="true"]'
    ].join(', ');
    const nodes = Array.from(document.querySelectorAll(selector));
    const candidates = [];
    for (const el of nodes) {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) continue;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) continue;
        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute('type') || '').toLowerCase();
        if (tag === 'input' && type === 'hidden') continue;
        candidates.push({
            el: el, tag: tag, type: type,
            inViewport: rect.top < window.innerHeight && rect.bottom > 0 && rect.left < window.innerWidth && rect.right > 0
        });
    }
    candidates.sort((a, b) => (b.inViewport ? 1 : 0) - (a.inViewport ? 1 : 0));
    const elements = [];
    let index = 0;
    for (const c of candidates) {
        if (index >= 60) break;
        c.el.setAttribute('data-agent-id', String(index));
        const text = (c.el.innerText || c.el.value || '').trim().replace(/\s+/g, ' ').slice(0, 60);
        const placeholder = (c.el.getAttribute('placeholder') || '').trim().slice(0, 40);
        const label = (c.el.getAttribute('aria-label') || c.el.getAttribute('title') || '').trim().slice(0, 40);
        elements.push({index: index, tag: c.tag, type: c.type, text: text, placeholder: placeholder, label: label, inViewport: c.inViewport});
        index += 1;
    }
    return elements;
}
"""


class BrowserCapture:
    """浏览器错误收集器"""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.console_errors: List[str] = []
        self.network_errors: List[str] = []
        self.storage_state_path = ""

    async def start(self, storage_state_path: str = ""):
        """启动浏览器（提供已存在的 storage_state 文件时加载登录态）"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        context_kwargs: Dict = {"viewport": {"width": 1280, "height": 800}}
        if storage_state_path and os.path.exists(storage_state_path):
            context_kwargs["storage_state"] = storage_state_path
        self.context = await self.browser.new_context(**context_kwargs)
        self.page = await self.context.new_page()
        self.storage_state_path = storage_state_path or ""
        self._setup_listeners()

    def _setup_listeners(self):
        """设置错误监听器"""
        # 监听 Console 错误
        async def on_console(msg):
            if msg.type in ["error", "warning"]:
                error_text = f"[{msg.type.upper()}] {msg.text}"
                if msg.location and msg.location.get("url"):
                    loc = msg.location
                    error_text += f"\n  at {loc.get('url', '')}:{loc.get('lineNumber', 0)}:{loc.get('columnNumber', 0)}"
                self.console_errors.append(error_text)

        self.page.on("console", on_console)

        # 监听页面错误
        async def on_page_error(error):
            self.console_errors.append(f"[PAGE_ERROR] {str(error)}")

        self.page.on("pageerror", on_page_error)

        # 监听 HTTP 响应失败
        async def on_response(response):
            if response.status >= 400:
                error_text = f"[HTTP {response.status}] {response.url}"
                try:
                    body = await response.text()
                    if body:
                        error_text += f"\n  Response: {body[:500]}"
                except Exception:
                    pass
                self.network_errors.append(error_text)

        self.page.on("response", on_response)

    async def navigate(self, url: str):
        """导航到指定URL"""
        self.console_errors = []
        self.network_errors = []
        try:
            await self.page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            self.console_errors.append(f"[NAVIGATION_ERROR] {str(e)}")

    async def screenshot(self) -> Optional[str]:
        """截取当前屏幕, 返回 base64(JPEG 压缩,控制视觉模式 token 成本)"""
        try:
            screenshot_bytes = await self.page.screenshot(full_page=True, type="jpeg", quality=75)
            img_base64 = base64.b64encode(screenshot_bytes).decode()
            return f"data:image/jpeg;base64,{img_base64}"
        except Exception:
            return None

    async def click(self, selector: str):
        """点击元素(支持元素编号或CSS选择器)"""
        await self.page.click(self._resolve_selector(selector), timeout=5000)

    async def fill(self, selector: str, text: str):
        """填写输入框(支持元素编号或CSS选择器)"""
        await self.page.fill(self._resolve_selector(selector), text, timeout=5000)

    async def press_key(self, key: str):
        """按键"""
        await self.page.keyboard.press(key)

    async def wait(self, ms: int = 1000):
        """等待"""
        await self.page.wait_for_timeout(ms)

    async def get_text(self, selector: str) -> str:
        """获取元素文本"""
        element = await self.page.query_selector(self._resolve_selector(selector))
        if element:
            return await element.inner_text()
        return ""

    async def is_visible(self, selector: str) -> bool:
        """检查元素是否可见(支持元素编号或CSS选择器)"""
        try:
            await self.page.wait_for_selector(
                self._resolve_selector(selector), state="visible", timeout=3000
            )
            return True
        except Exception:
            return False

    def _resolve_selector(self, selector: str) -> str:
        """把纯数字形式的元素编号解析为注入标记选择器,其它形式原样返回"""
        match = re.fullmatch(r"\[?(\d+)\]?", (selector or "").strip())
        if match:
            return f'[data-agent-id="{match.group(1)}"]'
        return selector

    async def get_interactive_elements(self) -> List[dict]:
        """采集页面可交互元素并注入 data-agent-id 标记,供 AI 按编号定位"""
        try:
            return await self.page.evaluate(_COLLECT_ELEMENTS_JS)
        except Exception:
            return []

    async def get_page_digest(self) -> dict:
        """采集页面结构摘要(标题/标题层级/表单概览),供纯文本感知模式使用"""
        try:
            digest = await self.page.evaluate(_COLLECT_PAGE_DIGEST_JS)
            return digest if isinstance(digest, dict) else {}
        except Exception:
            return []

    async def describe_element(self, selector: str) -> dict:
        """返回元素的稳定定位属性描述(id/name/placeholder/text等),用于生成可回放脚本"""
        try:
            desc = await self.page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    return {
                        tag: el.tagName.toLowerCase(),
                        id: el.id || '',
                        testid: el.getAttribute('data-testid') || '',
                        name: el.getAttribute('name') || '',
                        type: (el.getAttribute('type') || '').toLowerCase(),
                        placeholder: el.getAttribute('placeholder') || '',
                        aria_label: el.getAttribute('aria-label') || '',
                        text: (el.innerText || el.value || '').trim().replace(/\\s+/g, ' ').slice(0, 40)
                    };
                }""",
                self._resolve_selector(selector),
            )
            return desc if isinstance(desc, dict) else {}
        except Exception:
            return {}

    async def get_url(self) -> str:
        """获取当前URL"""
        return self.page.url

    def get_errors(self) -> Dict[str, List[str]]:
        """获取收集到的错误"""
        return {
            "console": self.console_errors.copy(),
            "network": self.network_errors.copy(),
        }

    def clear_errors(self):
        """清空错误缓存"""
        self.console_errors = []
        self.network_errors = []

    async def execute_script(self, script: str):
        """执行 JavaScript"""
        return await self.page.evaluate(script)

    async def save_storage_state(self):
        """保存登录态(cookies/localStorage)到 storage_state 文件,供下次测试复用"""
        if self.context and self.storage_state_path:
            try:
                await self.context.storage_state(path=self.storage_state_path)
            except Exception as e:
                print(f"[登录态] 保存失败: {e}")

    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
