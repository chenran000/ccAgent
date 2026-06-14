"""浏览器错误收集模块 - 使用 Playwright 捕获 Console/Network 错误"""
import base64
import io
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


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

    async def start(self):
        """启动浏览器"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 800}
        )
        self.page = await self.context.new_page()
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

        # 监听 Network 请求失败
        async def on_request_failed(request):
            pass  # Playwright 没有直接的 request_failed 事件

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
        """截取当前屏幕, 返回 base64"""
        try:
            screenshot_bytes = await self.page.screenshot(full_page=True)
            img_base64 = base64.b64encode(screenshot_bytes).decode()
            return f"data:image/png;base64,{img_base64}"
        except Exception:
            return None

    async def click(self, selector: str):
        """点击元素"""
        await self.page.click(selector, timeout=5000)

    async def fill(self, selector: str, text: str):
        """填写输入框"""
        await self.page.fill(selector, text, timeout=5000)

    async def type_text(self, selector: str, text: str):
        """模拟打字输入"""
        await self.page.type(selector, text, delay=50)

    async def press_key(self, key: str):
        """按键"""
        await self.page.keyboard.press(key)

    async def wait(self, ms: int = 1000):
        """等待"""
        await self.page.wait_for_timeout(ms)

    async def get_text(self, selector: str) -> str:
        """获取元素文本"""
        element = await self.page.query_selector(selector)
        if element:
            return await element.inner_text()
        return ""

    async def is_visible(self, selector: str) -> bool:
        """检查元素是否可见"""
        try:
            await self.page.wait_for_selector(selector, state="visible", timeout=3000)
            return True
        except Exception:
            return False

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

    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
