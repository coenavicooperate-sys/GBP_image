"""
GBP画像取得用のスタンドアロンスクリプト
Streamlitのイベントループと競合しないよう、別プロセスで実行する
"""
import json
import re
import sys
from pathlib import Path

# このスクリプトのディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from playwright.sync_api import sync_playwright

OUTPUT_MARKER = "<<<GBP_FETCH_RESULT>>>"


def _convert_to_high_res_url(url: str) -> str:
    if not url:
        return url
    if "googleusercontent.com" not in url and "ggpht.com" not in url:
        return url
    pattern = r"=[whs]\d+(-[whs]\d+)*(-[cp])*"
    return re.sub(pattern, "=s2048", url)


def fetch(maps_url: str, max_images: int = 30) -> list[str]:
    image_urls: list[str] = []
    seen_urls: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ja-JP",
        )
        page = context.new_page()
        page.set_default_timeout(60000)

        try:
            page.goto(maps_url.strip(), wait_until="domcontentloaded")
            page.wait_for_timeout(6000)

            photo_tab_selectors = [
                'button[aria-label*="写真"]',
                'button[aria-label*="Photos"]',
                'button[data-tab-index="1"]',
                '[role="tab"]:has-text("写真")',
                '[role="tab"]:has-text("Photos")',
                'button:has-text("写真")',
                'button:has-text("Photos")',
                '[data-tab-id="photos"]',
            ]
            for sel in photo_tab_selectors:
                try:
                    tab = page.locator(sel).first
                    if tab.count() > 0:
                        tab.click()
                        break
                except Exception:
                    continue

            page.wait_for_timeout(4000)

            # 「すべて見る」「See all」で写真ギャラリーを開く（全写真表示）
            gallery_keywords = ["すべて見る", "See all", "すべての写真", "View all", "写真をすべて見る"]
            for keyword in gallery_keywords:
                try:
                    link = page.get_by_role("link", name=keyword)
                    if link.count() > 0:
                        link.first.click(timeout=3000)
                        page.wait_for_timeout(3000)
                        break
                except Exception:
                    pass
                try:
                    btn = page.get_by_text(keyword, exact=False).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(timeout=3000)
                        page.wait_for_timeout(3000)
                        break
                except Exception:
                    pass

            # ページを下にスクロールしてオーナー提供セクションを表示（遅延読み込み対策）
            for _ in range(5):
                page.mouse.wheel(0, 400)
                page.wait_for_timeout(800)

            # オーナー提供セクションへスクロールしてからクリック（オーナー写真を優先）
            for keyword in ["オーナー提供", "Owner"]:
                try:
                    elem = page.get_by_text(keyword, exact=False).first
                    if elem.count() > 0:
                        elem.scroll_into_view_if_needed(timeout=5000)
                        page.wait_for_timeout(1500)
                        try:
                            elem.click(timeout=2000)
                            page.wait_for_timeout(2500)
                        except Exception:
                            pass
                        break
                except Exception:
                    continue

            page.wait_for_timeout(2000)

            scroll_count = 0
            max_scrolls = 30
            prev_count = 0
            no_change_count = 0

            def _collect_images():
                urls = []
                for selector in [
                    'img[src*="googleusercontent.com"]',
                    'img[src*="ggpht.com"]',
                    'img[data-src*="googleusercontent.com"]',
                    'img[data-src*="ggpht.com"]',
                ]:
                    try:
                        imgs = page.locator(selector)
                        for i in range(imgs.count()):
                            try:
                                el = imgs.nth(i)
                                src = el.get_attribute("src") or el.get_attribute("data-src")
                                if not src or src in seen_urls:
                                    continue
                                if "googleusercontent.com" in src or "ggpht.com" in src:
                                    seen_urls.add(src)
                                    high_res = _convert_to_high_res_url(src)
                                    if high_res not in urls:
                                        urls.append(high_res)
                            except Exception:
                                continue
                    except Exception:
                        continue
                return urls

            while len(image_urls) < max_images and scroll_count < max_scrolls:
                new_urls = _collect_images()
                for u in new_urls:
                    if u not in image_urls:
                        image_urls.append(u)
                    if len(image_urls) >= max_images:
                        break

                if len(image_urls) >= max_images:
                    break

                if len(image_urls) == prev_count:
                    no_change_count += 1
                    if no_change_count >= 8:
                        break
                else:
                    no_change_count = 0
                prev_count = len(image_urls)

                # 複数のスクロール方法を試す（縦・横・マウスホイール）
                try:
                    page.evaluate(
                        """
                        () => {
                            const selectors = [
                                '[role="main"]', '.m6QErb', '.section-scrollbox',
                                '[aria-label*="写真"]', '[aria-label*="Photos"]',
                                '.scrollable-show', '.m6QErb.DxyBCb', '[role="feed"]'
                            ];
                            for (const sel of selectors) {
                                const els = document.querySelectorAll(sel);
                                for (const el of els) {
                                    if (el.scrollHeight > el.clientHeight + 50) {
                                        el.scrollTop = el.scrollHeight;
                                    }
                                    if (el.scrollWidth > el.clientWidth + 50) {
                                        el.scrollLeft = el.scrollWidth;
                                    }
                                }
                            }
                            document.querySelector('[role="main"]')?.scrollBy(0, 500);
                            window.scrollBy(0, 500);
                        }
                        """
                    )
                except Exception:
                    pass
                page.mouse.wheel(0, 500)
                page.keyboard.press("PageDown")
                page.keyboard.press("PageDown")
                page.keyboard.press("End")
                page.wait_for_timeout(1500)
                scroll_count += 1

        finally:
            browser.close()

    return image_urls[:max_images]


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: gbp_fetcher.py <url> <max_images>"}), file=sys.stderr)
        sys.exit(1)

    maps_url = sys.argv[1]
    try:
        max_images = int(sys.argv[2])
    except ValueError:
        print(json.dumps({"error": "max_images must be an integer"}), file=sys.stderr)
        sys.exit(1)

    try:
        urls = fetch(maps_url, max_images)
        print(OUTPUT_MARKER + json.dumps(urls))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
