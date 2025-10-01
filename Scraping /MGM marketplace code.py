import pandas as pd
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from webdriver_manager.firefox import GeckoDriverManager
import random
import subprocess

def check_tor():
    """Ensure Tor is running before starting"""
    try:
        result = subprocess.run(["systemctl", "is-active", "tor"], capture_output=True, text=True)
        if result.stdout.strip() != "active":
            print("❌ Tor is not running! Starting Tor...")
            subprocess.run(["sudo", "systemctl", "start", "tor"], check=True)
            time.sleep(5)
        return True
    except Exception as e:
        print(f"❌ Tor check failed: {e}")
        return False

def start_driver():
    """Initialize Firefox with Tor proxy settings"""
    options = Options()
    
    # Configure Firefox to use Tor proxy
    options.set_preference("network.proxy.type", 1)
    options.set_preference("network.proxy.socks", "127.0.0.1")
    options.set_preference("network.proxy.socks_port", 9050)
    options.set_preference("network.proxy.socks_remote_dns", True)
    
    # Additional privacy settings
    options.set_preference("privacy.trackingprotection.enabled", True)
    options.set_preference("privacy.resistFingerprinting", True)
    # options.set_preference("javascript.enabled", False)  # Disable if site works without JS
    
    try:
        service = Service(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=options)
        print("✅ Firefox Driver started via Tor")
        return driver
    except Exception as e:
        print(f"❌ WebDriver start failed: {e}")
        raise

def get_new_tor_circuit(driver):
    """Request new Tor circuit through Firefox"""
    try:
        driver.get("about:tor")
        time.sleep(2)
        driver.find_element(By.ID, "new-identity").click()
        time.sleep(5)
        print("✅ New Tor circuit obtained")
        return True
    except Exception as e:
        print(f"❌ New circuit failed: {e}")
        return False

def scrape_page(driver):
    """Scrape data from the current page with improved element selection"""
    soup = BeautifulSoup(driver.page_source, "html.parser")
    data = []
    products = soup.find_all("div", class_="product-item hover-shadow")

    if not products:
        print("⚠ No products found! Saving error page...")
        with open("error_page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        return []

    for product in products:
        try:
            # Vendor Info (if available)
            vendor_tag = product.find("a", class_="vendor-name")
            vendor_name = vendor_tag.get_text(strip=True).replace("Sold By ", "") if vendor_tag else "N/A"
            vendor_profile_link = vendor_tag["href"] if vendor_tag else "N/A"

            # Product Image
            image_tag = product.select_one(".product-image a.thumb img")
            image_url = image_tag["src"] if image_tag else "N/A"

            # Product Link
            product_link_tag = product.select_one(".product-image a.thumb")
            product_link = product_link_tag["href"] if product_link_tag else "N/A"

            # Product Title - try multiple selectors
            title_tag = (product.select_one(".product-title") or 
                        product.select_one(".product-name") or
                        product.select_one("h4") or
                        product.select_one("h3"))
            product_title = title_tag.get_text(strip=True) if title_tag else "N/A"

            # Product Description - look in common description containers
            desc_tag = (product.select_one(".product-description") or
                       product.select_one(".description") or
                       product.select_one(".text-justify") or
                       product.select_one(".details"))
            product_description = desc_tag.get_text(strip=True) if desc_tag else "N/A"

            # Product Price - check multiple price element classes
            price_tag = (product.select_one(".product-price") or
                        product.select_one(".price") or
                        product.select_one(".amount") or
                        product.find("span", class_=lambda x: x and "price" in x.lower()))
            product_price = price_tag.get_text(strip=True) if price_tag else "N/A"

            data.append([
                vendor_name, vendor_profile_link, product_title,
                product_description, product_price, product_link, image_url
            ])
            
        except Exception as e:
            print(f"❌ Error scraping a product: {e}")
            print("Problematic product HTML:")
            print(product.prettify()[:500])  # Print first 500 chars of problematic HTML
            continue

    return data

def handle_pagination(driver):
    """Handles pagination by clicking Next button until no more pages"""
    all_data = []
    page_number = 1
    max_retries = 3
    consecutive_failures = 0
    max_consecutive_failures = 2  # Stop after this many failed attempts
    
    while True:
        retries = 0
        while retries < max_retries:
            try:
                print(f"🔄 Scraping page {page_number}...")
                page_data = scrape_page(driver)
                all_data.extend(page_data)
                print(f"✅ Page {page_number} done! Total items: {len(all_data)}")
                break
            except Exception as e:
                print(f"⚠ Retry due to error: {e}")
                retries += 1
                time.sleep(10)
                driver.refresh()

        # Try to find and click the Next button
        try:
            # More robust way to find Next button - tries multiple approaches
            next_button = None
            next_button_selectors = [
                (By.XPATH, "//a[contains(text(), 'Next')]"),
                (By.XPATH, "//a[contains(., 'Next')]"),
                (By.CSS_SELECTOR, "a.page-link:contains('Next')"),
                (By.CSS_SELECTOR, "li.next a"),
                (By.CSS_SELECTOR, "a[rel='next']"),
                (By.CSS_SELECTOR, "a[aria-label='Next']")
            ]
            
            for by, selector in next_button_selectors:
                try:
                    next_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((by, selector)))
                    break
                except:
                    continue
            
            if next_button:
                # Scroll into view and click using JavaScript
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", next_button)
                
                # Wait for page to load
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "product-item")))
                
                # Random delay to appear more human-like
                time.sleep(random.uniform(3, 7))
                page_number += 1
                consecutive_failures = 0
            else:
                print("🚫 No more pages (Next button not found).")
                break
                
        except Exception as e:
            print(f"⚠ Pagination error: {e}")
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                print(f"⚠ Stopping after {max_consecutive_failures} consecutive pagination failures")
                break
            
            # Try to recover by refreshing or getting new Tor circuit
            if "blocked" in driver.page_source.lower():
                print("🔒 Block detected! Getting new Tor circuit...")
                if not get_new_tor_circuit(driver):
                    break
                driver.refresh()
            else:
                driver.refresh()
            time.sleep(5)

    return all_data

def main():
    if not check_tor():
        print("❌ Tor is not active, exiting.")
        return

    try:
        driver = start_driver()
        driver.delete_all_cookies()
        
        base_url = "http://pu2rsoo3kw6palhiod6zkilf46oms5xw2jfsirubgz2x7owmboylbsyd.onion"
        
        # Initial page load
        print(f"🌐 Loading initial page: {base_url}")
        driver.get(base_url)
        time.sleep(5)

        # Check for blocking
        if any(word in driver.page_source.lower() for word in ["blocked", "access denied"]):
            print("🔒 Blocked! Trying new circuit...")
            if not get_new_tor_circuit(driver):
                return
            driver.get(base_url)
            time.sleep(5)

        print("🔐 If there's a CAPTCHA, solve it manually in the browser.")
        time.sleep(120)  # Give time to solve CAPTCHA if needed

        # Handle pagination and scraping
        all_data = handle_pagination(driver)

        if all_data:
            df = pd.DataFrame(all_data, columns=[
                "Vendor Name", "Vendor Profile Link", "Product Title",
                "Product Description", "Product Price", "Product Link", "Image URL"
            ])
            filename = f"darkmarket_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            df.to_csv(filename, index=False)
            print(f"💾 Data saved to: {filename}")
        else:
            print("❌ No data found.")

    except KeyboardInterrupt:
        print("🛑 Script manually interrupted.")
    except Exception as e:
        print(f"❌ Critical Error: {e}")
    finally:
        if 'driver' in locals():
            driver.quit()
        print("🏁 Done.")

if name == "main":
    main()
