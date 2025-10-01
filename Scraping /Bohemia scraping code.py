import time
import random
import re
import json
import os
import pandas as pd
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.firefox.service import Service

# ============ CONFIG =============
TEMP_FILE = "scraped_products_temp.jsonl"
FINAL_FILE = "scraped_products.json"
EXCEL_FILE = "bohemia_market_products_final.csv"   # Input file
MAX_PRODUCTS = 1000      # <- Max scrape limit
START_INDEX = 10190        # <- Start scraping from this row (0 = first row)
# =================================

def init_driver():
    options = Options()
    # options.headless = True  # Disable headless mode for debugging
    options.set_preference("network.proxy.type", 1)
    options.set_preference("network.proxy.socks", "127.0.0.1")
    options.set_preference("network.proxy.socks_port", 9050)
    options.set_preference("network.proxy.socks_remote_dns", True)

    service = Service(executable_path="/snap/bin/geckodriver")
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_page_load_timeout(60)
    return driver

def append_temp_data(entry):
    with open(TEMP_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def read_temp_data():
    if not os.path.exists(TEMP_FILE):
        return []
    with open(TEMP_FILE, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f.readlines()]

def scrape_products(excel_file_path, start_index=0):
    base_url = "http://bohemiabmgo5arzb6so564wzdsf76u6rm4dpukfcbf7jyjqgclu2beyd.onion/"
    if not base_url.endswith("/"):
        base_url += "/"

    df = pd.read_csv(excel_file_path)
    products = df.to_dict(orient="records")
    print(f"🔍 Found {len(products)} products in file.")

    if start_index >= len(products):
        print(f"⚠️ START_INDEX ({start_index}) is beyond total products ({len(products)}). Exiting.")
        return

    scraped_urls = {entry["URL"] for entry in read_temp_data() if "URL" in entry}
    driver = init_driver()
    scraped_count = 0

    try:
        for index in range(start_index, len(products)):
            product = products[index]
            if scraped_count >= MAX_PRODUCTS:
                print(f"✅ Reached max scrape limit: {MAX_PRODUCTS}")
                break

            rel_url_raw = product.get("Product Link", "")
            rel_url = str(rel_url_raw).strip() if pd.notna(rel_url_raw) else ""
            if not rel_url:
                continue

            full_url = base_url + rel_url
            if full_url in scraped_urls:
                print(f"[{index+1}/{len(products)}] Skipping already scraped: {full_url}")
                continue

            print(f"[{index+1}/{len(products)}] Scraping: {product.get('Product Name', 'Unnamed')} — {full_url}")

            try:
                for attempt in range(3):
                    try:
                        driver.get(full_url)
                        break
                    except TimeoutException:
                        print(f"⚠️ Timeout, retrying ({attempt+1}/3)...")
                        if attempt < 2:
                            time.sleep(5)
                        else:
                            raise

                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.XPATH, "//h1[text()='Description']"))
                )

                scraped_entry = product.copy()
                scraped_entry.update({
                    "Serial Number": index + 1,  # 1-based serial number
                    "Description": "",
                    "Product Rating": "",
                    "Rating Count": "",
                    "Vendor Feedback (%)": "",
                    "Vendor Sales": "",
                    "Sales Policy": "",
                    "URL": full_url
                })

                # Description
                try:
                    desc_elem = driver.find_element(By.XPATH, "//h1[text()='Description']/following-sibling::p")
                    scraped_entry["Description"] = desc_elem.text.strip()
                except NoSuchElementException:
                    pass

                # Image URL (if missing)
                if not scraped_entry.get("Image URL"):
                    try:
                        img_elem = driver.find_element(By.CSS_SELECTOR, "div.panel-body img")
                        scraped_entry["Image URL"] = img_elem.get_attribute("src")
                    except NoSuchElementException:
                        scraped_entry["Image URL"] = ""

                # Vendor Feedback and Sales
                try:
                    vendor_block = driver.find_element(By.CSS_SELECTOR, "div.user-details")
                    feedback_text = vendor_block.find_element(By.CSS_SELECTOR, "span.smalltext").text
                    match = re.search(r"(\d+)%.*?(\d+)", feedback_text)
                    if match:
                        scraped_entry["Vendor Feedback (%)"] = match.group(1)
                        scraped_entry["Vendor Sales"] = match.group(2)
                except NoSuchElementException:
                    pass

                # Product Rating
                try:
                    rating_elem = driver.find_element(By.XPATH, "//strong[text()='Rating:']")
                    rating_text = rating_elem.find_element(By.XPATH, "./..").text
                    match_rating = re.search(r"Rating:\s*([0-9.]+)\s*\(Based on\s*(\d+)\s*ratings\)", rating_text)
                    if match_rating:
                        scraped_entry["Product Rating"] = match_rating.group(1)
                        scraped_entry["Rating Count"] = match_rating.group(2)
                except NoSuchElementException:
                    pass

                # Sales Policy
                try:
                    sales_header = driver.find_element(By.XPATH, "//h1[text()='Sales Policy']")
                    sales_policy_elem = sales_header.find_element(By.XPATH, "./following-sibling::*[1]")
                    scraped_entry["Sales Policy"] = sales_policy_elem.text.strip()
                except NoSuchElementException:
                    pass

                append_temp_data(scraped_entry)
                scraped_count += 1
                print(f"✅ Scraped: {scraped_entry.get('Product Name', 'Unnamed')} (Serial {scraped_entry['Serial Number']})")

                time.sleep(random.uniform(5, 10))

            except Exception as e:
                print(f"❌ Error scraping {product.get('Product Name', 'Unknown')} — {full_url}\n   ↪ {e}")

    finally:
        driver.quit()

    # Save Excel (optional)
    updated_df = pd.DataFrame(products)
    updated_df.to_csv(excel_file_path, index=False)
    print(f"\n✅ Excel updated: {excel_file_path}")

    # Final JSON conversion
    print("📦 Converting temporary data to final JSON file...")
    all_data = read_temp_data()
    with open(FINAL_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)
    print(f"✅ Final JSON saved: {FINAL_FILE}")

    if os.path.exists(TEMP_FILE):
        os.remove(TEMP_FILE)
        print("🧹 Temporary file cleaned up.")

if __name__ == "__main__":
    scrape_products(EXCEL_FILE, start_index=START_INDEX)
