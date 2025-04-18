#!/usr/bin/env python3
import sys
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

# Get the prompt from CLI args
prompt = " ".join(sys.argv[1:]).strip()
if not prompt:
    print("❌ Please pass a prompt as an argument.")
    sys.exit(1)

# Set up headless Chrome
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")

# Launch browser
driver = webdriver.Chrome(options=chrome_options)

try:
    driver.get("https://chat.openai.com/")

    print("🕐 Waiting for login...")
    # Wait up to 2 minutes for user to log in manually
    for i in range(120):
        if "chat.openai.com/chat" in driver.current_url:
            break
        time.sleep(1)
    else:
        print("❌ Login timeout.")
        driver.quit()
        sys.exit(1)

    # Find input field
    textarea = driver.find_element(By.TAG_NAME, "textarea")
    textarea.send_keys(prompt)
    textarea.send_keys(Keys.ENTER)

    print("📡 Waiting for response...")
    time.sleep(5)  # wait for it to start responding

    # Wait until a response appears
    last_output = ""
    for _ in range(30):
        elems = driver.find_elements(By.CLASS_NAME, "markdown")
        if elems:
            current_output = elems[-1].text.strip()
            if current_output != last_output:
                last_output = current_output
                time.sleep(1)
            else:
                break
        else:
            time.sleep(1)

    print("✅ Response:\n")
    print(last_output)

finally:
    driver.quit()
