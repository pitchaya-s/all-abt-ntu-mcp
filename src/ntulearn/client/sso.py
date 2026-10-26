"""Microsoft/NTU browser sign-in used only when no validated session is found."""

import re
import time
from urllib.parse import urlsplit

from shared.credentials import Credentials

from ..models import LearnError
from .browser_cookies import BASE_URL, SessionCookie, playwright_cookies

TIMEOUT_MS = 30_000
_CHALLENGE = re.compile(
    r"captcha|approve (?:the )?sign.in|verify your identity|verification code|authenticator|multi.factor|security info",
    re.I,
)


def _allowed_login_host(host: str | None) -> bool:
    return bool(
        host
        and (
            host == "login.microsoftonline.com"
            or host == "ntu.edu.sg"
            or host.endswith(".ntu.edu.sg")
        )
    )


async def login(credentials: Credentials, *, headless: bool) -> tuple[SessionCookie, ...]:
    """Run the regular NTU SSO flow; interactive challenges are never bypassed."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise LearnError("Automatic NTULearn sign-in needs the optional personal dependencies and Chromium.") from None

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=headless)
            try:
                context = await browser.new_context(locale="en-US")
                page = await context.new_page()
                await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
                deadline = time.monotonic() + (60 if headless else 180)
                username_sent = password_sent = False
                while time.monotonic() < deadline:
                    current = urlsplit(page.url)
                    if current.scheme != "https" or not _allowed_login_host(current.hostname):
                        raise LearnError("The login reached an unexpected host; no further credentials were submitted.")
                    if current.hostname == "ntulearn.ntu.edu.sg" and current.path.startswith("/ultra/"):
                        cookies = playwright_cookies(await context.cookies(BASE_URL))
                        if cookies:
                            return cookies
                        raise LearnError("NTULearn did not provide a usable authenticated browser session.")

                    body = await page.locator("body").inner_text(timeout=5000)
                    if _CHALLENGE.search(body):
                        if headless:
                            raise LearnError(
                                "NTULearn requires MFA or CAPTCHA. Set NTULEARN_HEADLESS=false and complete it in the local browser; no security checks were bypassed."
                            )
                        await page.wait_for_timeout(500)
                        continue
                    if password_sent and re.search(
                        r"password (?:is )?incorrect|incorrect password|account.*locked|too many.*attempts|sign.in.*blocked",
                        body,
                        re.I,
                    ):
                        raise LearnError(
                            "Microsoft rejected the login or account access. Check your NTULearn credentials; no automatic password retry was made."
                        )

                    email = page.locator('input[name="loginfmt"]:visible')
                    password = page.locator('input[type="password"]:visible')
                    if await email.count() and not username_sent:
                        await email.first.fill(credentials.email)
                        username_sent = True
                        await page.get_by_role("button", name="Next", exact=True).click()
                    elif await password.count() and not password_sent:
                        submit = page.get_by_role("button", name="Sign in", exact=True)
                        await submit.wait_for(state="visible", timeout=TIMEOUT_MS)
                        await password.first.fill(credentials.password)
                        password_sent = True
                        await submit.click()
                    elif "Stay signed in?" in body and await page.locator("#idBtn_Back:visible").count():
                        await page.locator("#idBtn_Back").click()
                    await page.wait_for_timeout(500)
                raise LearnError(
                    "NTULearn login did not finish. Check the account and complete any required interaction in a visible browser."
                )
            finally:
                await browser.close()
    except LearnError:
        raise
    except Exception:  # noqa: BLE001 - browser exceptions can include credentials, URLs, or page contents.
        raise LearnError("NTULearn login failed or timed out; no automatic password retry was made.") from None
