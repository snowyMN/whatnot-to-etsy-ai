from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

def build_driver():
    options = Options()
    options.add_argument("--window-size=1400,1200")
    # Uncomment the next line to run headless
    # options.add_argument("--headless=new")
    return webdriver.Chrome(options=options)

def extract_listing_links(driver):
    links = set()
    elements = driver.find_elements(By.TAG_NAME, "a")
    for el in elements:
        href = el.get_attribute("href")
        if href and "/listing/" in href:
            links.add(href)
    return links

def get_listing_links(shop_url: str):
    driver = build_driver()
    try:
        driver.get(shop_url)
        time.sleep(6)

        links = set()
        stable_rounds = 0
        max_rounds = 40

        for round_num in range(max_rounds):
            old_links = extract_listing_links(driver)
            links.update(old_links)
            old_count = len(links)

            old_height = driver.execute_script("return document.body.scrollHeight")

            # Scroll to bottom
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # Wait up to 10 seconds for either:
            # 1. page height to increase
            # 2. number of listing links to increase
            changed = False
            for _ in range(20):
                time.sleep(0.5)

                new_height = driver.execute_script("return document.body.scrollHeight")
                new_links = extract_listing_links(driver)
                links.update(new_links)
                new_count = len(links)

                if new_height > old_height or new_count > old_count:
                    changed = True
                    break

            print(f"Round {round_num + 1}: {len(links)} links")

            if not changed:
                stable_rounds += 1
            else:
                stable_rounds = 0

            # Stop only after several rounds with no growth
            if stable_rounds >= 5:
                break

        return list(links)

    finally:
        driver.quit()

def parse_listing(url: str):
    driver = build_driver()

    try:
        driver.get(url)
        time.sleep(5)

        body_text = driver.find_element(By.TAG_NAME, "body").text
        lines = [line.strip() for line in body_text.split("\n") if line.strip()]

        title = ""
        price = ""
        size = ""
        condition = ""
        description = ""

        # Find price line first
        price_index = -1
        for i, line in enumerate(lines):
            if "$" in line and "shipping" in line:
                price = line
                price_index = i
                break

        # Title is usually 2 lines above the price line:
        # [title]
        # [availability/category/size]
        # [price]
        if price_index >= 2:
            title = lines[price_index - 2]

        # Extract size, condition, description
        for i, line in enumerate(lines):
            if line.startswith("Size "):
                size = line
            elif line.startswith("Condition "):
                condition = line
            elif line == "Product Details":
                description_lines = []
                for next_line in lines[i + 1:]:
                    if next_line.startswith("Type ") or next_line == "About the Seller":
                        break
                    description_lines.append(next_line)
                description = " ".join(description_lines)

        images = driver.find_elements(By.TAG_NAME, "img")
        image_urls = []

        for img in images:
            src = img.get_attribute("src")
            if src and "listings" in src and src not in image_urls:
                image_urls.append(src)

        return {
            "source_url": url,
            "title": title,
            "price": price,
            "size": size,
            "condition": condition,
            "description_notes": description,
            "image_urls": image_urls,
        }

    finally:
        driver.quit()
