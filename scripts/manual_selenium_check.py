"""Manual Selenium smoke script for Whatnot scraping behavior.

This script is for local debugging only and is not part of an automated test suite.
"""

import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

options = Options()
# Start with visible browser first for debugging.
# options.add_argument("--headless=new")

driver = webdriver.Chrome(options=options)

try:
    shop_url = "https://www.whatnot.com/user/snowymn"
    driver.get(shop_url)
    time.sleep(5)

    # Scroll to load more listings.
    for _ in range(5):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

    links = []
    elements = driver.find_elements(By.TAG_NAME, "a")

    for el in elements:
        href = el.get_attribute("href")
        if href and "/listing/" in href and href not in links:
            links.append(href)

    print(f"Found {len(links)} listings:\n")
    for link in links[:10]:
        print(link)

    if not links:
        raise RuntimeError("No listing links found.")

    first_link = links[0]
    print("\nTesting first listing:")
    print(first_link)

    driver.get(first_link)
    time.sleep(5)

    body_text = driver.find_element(By.TAG_NAME, "body").text
    print("\n--- LISTING PAGE TEXT PREVIEW ---\n")
    print(body_text[:2000])

    images = driver.find_elements(By.TAG_NAME, "img")
    image_urls = []
    for img in images:
        src = img.get_attribute("src")
        if src and src not in image_urls:
            image_urls.append(src)

    print("\n--- IMAGE URL PREVIEW ---\n")
    for url in image_urls[:10]:
        print(url)

finally:
    driver.quit()