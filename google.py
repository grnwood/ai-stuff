
#!/usr/bin/python3
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# 👇 Replace this with the full path to your downloaded chromedriver
CHROMEDRIVER_PATH = "/home/jgreenwood/chromedriver"

chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")

# ✅ This is what prevents Selenium from trying to use Selenium Manager
service = Service(executable_path=CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=chrome_options)

driver.get("https://www.google.com")
print("✅ Page title:", driver.title)

driver.quit()

