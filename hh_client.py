import asyncio
import json
import re
from urllib.parse import urlencode
from playwright.async_api import async_playwright
from config import HH_LOGIN, COOKIES_PATH, EXCLUDE_TITLE_PARTS

BASE = "https://hh.ru"
LOGIN = f"{BASE}/account/login"
SEARCH = f"{BASE}/search/vacancy"

class HHClient:
    def __init__(self):
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        self.page = await self.context.new_page()
        self.context.set_default_navigation_timeout(60000)
        if COOKIES_PATH.exists():
            try:
                cookies = json.loads(COOKIES_PATH.read_text(encoding="utf-8"))
                await self.context.add_cookies(cookies)
            except Exception:
                COOKIES_PATH.unlink(missing_ok=True)

    async def stop(self):
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()

    async def is_logged_in(self):
        try:
            cookies = await self.context.cookies()
            return any(c.get("name") == "hhtoken" for c in cookies)
        except Exception:
            return False

    async def save_cookies(self):
        cookies = await self.context.cookies()
        COOKIES_PATH.write_text(
            json.dumps(cookies, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    async def login_step1_send_phone(self):
        if not HH_LOGIN:
            return "error:HH_LOGIN_empty"

        await self.page.goto(LOGIN, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Applicant radio if HH shows account type chooser
        radio = await self.page.query_selector('input[data-qa*="APPLICANT"]')
        if radio:
            await radio.click()
            await asyncio.sleep(0.7)
            btn = await self.page.query_selector('button[data-qa="submit-button"]')
            if btn:
                await btn.click()
                await asyncio.sleep(2)

        phone_input = await self.page.query_selector(
            'input[data-qa="magritte-phone-input-national-number-input"],'
            'input[inputmode="tel"],input[type="tel"],'
            'input[data-qa="login-input-username"]'
        )
        if not phone_input:
            return "error:phone_input_not_found"

        phone = HH_LOGIN.strip()
        if phone.startswith("+7"):
            phone = phone[2:]
        elif phone.startswith("8") and len(phone) == 11:
            phone = phone[1:]

        await phone_input.fill(phone)
        btn = await self.page.query_selector('button[data-qa="submit-button"]')
        if btn:
            await btn.click()
        else:
            await phone_input.press("Enter")

        await asyncio.sleep(3)

        code_input = await self.page.query_selector(
            'input[data-qa="magritte-pincode-input-field"],'
            'input[autocomplete="one-time-code"],input[inputmode="numeric"]'
        )
        if code_input:
            return "code_sent"

        # Some sessions may already be authorized
        if await self.is_logged_in():
            await self.save_cookies()
            return "already_logged_in"

        body = (await self.page.locator("body").inner_text()).lower()
        if "капч" in body or "captcha" in body:
            return "error:captcha"
        return "error:code_input_not_found"

    async def login_step2_enter_code(self, code):
        code_input = await self.page.query_selector(
            'input[data-qa="magritte-pincode-input-field"],'
            'input[autocomplete="one-time-code"],input[inputmode="numeric"]'
        )
        if not code_input:
            return "error:code_input_not_found"

        try:
            await code_input.click()
            await code_input.type(code.strip(), delay=130)
        except Exception:
            pass

        await asyncio.sleep(5)
        try:
            await self.page.goto(BASE, wait_until="domcontentloaded")
            await asyncio.sleep(2)
        except Exception:
            pass

        if await self.is_logged_in():
            await self.save_cookies()
            return "success"

        body = (await self.page.locator("body").inner_text()).lower()
        if "невер" in body and "код" in body:
            return "wrong_code"
        if "капч" in body or "captcha" in body:
            return "error:captcha"
        return "error:login_not_confirmed"

    @staticmethod
    def vacancy_id(url):
        m = re.search(r"/vacancy/(\d+)", url or "")
        return m.group(1) if m else None

    async def get_vacancy(self, url):
        vid = self.vacancy_id(url)
        if not vid:
            return None
        await self.page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        body = await self.page.locator("body").inner_text()
        low = body.lower()
        if "captcha" in low or "капча" in low:
            return {"error": "captcha"}

        title = ""
        company = ""
        desc = ""

        for sel in ['h1[data-qa="vacancy-title"]', 'h1']:
            el = await self.page.query_selector(sel)
            if el:
                title = (await el.inner_text()).strip()
                if title:
                    break

        for sel in ['a[data-qa="vacancy-company-name"]', '[data-qa="vacancy-company-name"]']:
            el = await self.page.query_selector(sel)
            if el:
                company = (await el.inner_text()).strip()
                if company:
                    break

        for sel in ['[data-qa="vacancy-description"]', '.vacancy-description']:
            el = await self.page.query_selector(sel)
            if el:
                desc = (await el.inner_text()).strip()
                if desc:
                    break

        return {
            "id": vid,
            "url": url,
            "title": title or f"Вакансия {vid}",
            "company": company or "Компания не распознана",
            "description": desc,
        }

    def is_target_title(self, title):
        t = (title or "").lower()
        if any(x in t for x in EXCLUDE_TITLE_PARTS):
            # allow "руководитель отдела продаж", despite containing "продаж"
            if "руководитель отдела продаж" not in t:
                return False
        positive = [
            "директор", "руководитель отдела продаж", "head of sales",
            "региональный", "операционный", "коммерческий"
        ]
        return any(x in t for x in positive)

    async def search(self, query, area="1", limit=30):
        params = {
            "text": query,
            "area": area,
            "order_by": "publication_time",
            "search_field": "name",
            "per_page": min(limit, 50),
        }
        await self.page.goto(f"{SEARCH}?{urlencode(params)}", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        body = (await self.page.locator("body").inner_text()).lower()
        if "captcha" in body or "капча" in body:
            return [{"error": "captcha"}]

        cards = await self.page.query_selector_all('[data-qa="vacancy-serp__vacancy"]')
        out = []
        for card in cards[:limit]:
            link = await card.query_selector('a[href*="/vacancy/"]')
            if not link:
                continue
            href = await link.get_attribute("href")
            title = (await link.inner_text()).strip()
            if not self.is_target_title(title):
                continue
            vid = self.vacancy_id(href)
            if not vid:
                continue
            company = ""
            comp = await card.query_selector('[data-qa="vacancy-serp__vacancy-employer-text"]')
            if comp:
                company = (await comp.inner_text()).strip()
            out.append({
                "id": vid,
                "url": href.split("?")[0],
                "title": title,
                "company": company,
            })
        return out

    async def apply(self, vacancy, cover_letter):
        if not await self.is_logged_in():
            return "not_logged_in"

        await self.page.goto(vacancy["url"], wait_until="domcontentloaded")
        await asyncio.sleep(2)

        body = (await self.page.locator("body").inner_text()).lower()
        if "captcha" in body or "капча" in body:
            return "captcha"

        # HH frequently exposes a response button with data-qa containing vacancy-response
        candidates = [
            '[data-qa="vacancy-response-link-top"]',
            '[data-qa="vacancy-response-link-bottom"]',
            'a[data-qa*="vacancy-response"]',
            'button[data-qa*="vacancy-response"]',
        ]
        btn = None
        for sel in candidates:
            btn = await self.page.query_selector(sel)
            if btn:
                break
        if not btn:
            # Might already be responded
            if "вы откликнулись" in body or "отклик отправлен" in body:
                return "already_applied"
            return "apply_button_not_found"

        await btn.click()
        await asyncio.sleep(2)

        # Cover letter can appear as textarea in an overlay/form.
        textarea = await self.page.query_selector(
            'textarea[data-qa*="vacancy-response"],'
            'textarea[name="message"],textarea'
        )
        if textarea and cover_letter:
            try:
                await textarea.fill(cover_letter)
            except Exception:
                pass

        # Final submit button.
        submit = None
        for sel in [
            'button[data-qa="vacancy-response-submit-popup"]',
            'button[data-qa*="vacancy-response-submit"]',
            'button[type="submit"]'
        ]:
            submit = await self.page.query_selector(sel)
            if submit:
                txt = (await submit.inner_text()).strip().lower()
                if not txt or "отклик" in txt or "отправ" in txt:
                    break
                submit = None

        if submit:
            await submit.click()
            await asyncio.sleep(3)

        body2 = (await self.page.locator("body").inner_text()).lower()
        if "captcha" in body2 or "капча" in body2:
            return "captcha"
        if any(x in body2 for x in ["вы откликнулись", "отклик отправлен", "откликнуться повторно"]):
            return "sent"

        # Sometimes the click itself sends immediately and closes overlay.
        # We do not pretend success without a visible confirmation.
        return "not_confirmed"
