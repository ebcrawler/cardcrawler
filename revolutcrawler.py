#!/usr/bin/env python3

import argparse
import csv
import sys
import datetime
import re
import time
from decimal import Decimal
import getpass

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as cond
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

def send_slow_string(driver, s):
    for c in s:
        actions = ActionChains(driver)
        actions.send_keys(c)
        actions.perform()
        time.sleep(0.5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Revolutcard transaction crawler")
    parser.add_argument('phone', type=str, help='Revolut account phonenumber')
    parser.add_argument('--password', type=str, help='Revolut web password')
    parser.add_argument('--output', type=argparse.FileType('w', encoding='UTF-8'), default='-', help='Write output to file (- for stdout)')
    parser.add_argument('--debug', action='store_true', help='Enable debug = view the chrome window')
    parser.add_argument('--chrome', type=str, default='chrome', help='Path to chrome browser to use')
    parser.add_argument('--chromedriver', type=str, default='chromedriver', help='Path to chromedriver binary to use')
    parser.add_argument('--nosandbox', action='store_true', help='Disable chrome sandbox (used in docker)')

    args = parser.parse_args()

    def status(msg):
        print(msg, file=sys.stderr)

    if args.password:
        password = args.password
    else:
        password = getpass.getpass('Revolut password for {0}: '.format(args.phone))
    if not password:
        status("No password given.")
        sys.exit(1)

    chrome_options = Options()
    chrome_options.binary_location = args.chrome
#    if not args.debug:
#        chrome_options.add_argument('--headless')
    if args.nosandbox:
        chrome_options.add_argument('--no-sandbox')
    driver = webdriver.Chrome(executable_path=args.chromedriver, options=chrome_options)

    # NOTE! No more code here before we open the try/finally, or we may leak running
    # chrome processes!

    try:
        # This is not always very fast
        driver.implicitly_wait(3)

        status("Initiating login...")
        driver.get('https://app.revolut.com/start')

        WebDriverWait(driver, 5).until(cond.visibility_of_element_located((By.CSS_SELECTOR, 'input[aria-label="Country"]')))
        # This defaults right, so ignore it for now
        #driver.find_element_by_css_selector('input[aria-label="Country"]').send_keys("+46")

        driver.find_element_by_css_selector("input[name=phoneNumber]").send_keys(args.phone.lstrip("0"))
        driver.find_element_by_xpath("//button//span[contains(.,'Continue')]/..").click()

        WebDriverWait(driver, 5).until(cond.visibility_of_element_located((By.XPATH, "//span[contains(text(),'Enter passcode')]")))
        send_slow_string(driver, password)

        # SMS code flow, do we need both?
#        WebDriverWait(driver, 5).until(cond.visibility_of_element_located((By.XPATH, "//span[contains(text(),'6-digit code')]")))
#        code = getpass.getpass('One time password (from SMS): ')
#        send_slow_string(driver, code)

        # New flow using app
        WebDriverWait(driver, 5).until(cond.visibility_of_element_located((By.XPATH, "//span[contains(text(),'Revolut app')]")))
        status("Approve the sign-in request in the revolut app, please")

        # Wait for and get rid of cookie popup
        WebDriverWait(driver, 20).until(cond.visibility_of_element_located((By.XPATH, "//button//span[contains(.,'Allow all cookies')]/..")))
        status("Thank you, login completed.")
        driver.find_element_by_xpath("//button//span[contains(.,'Allow all cookies')]/..").click()

        # Wait for really stupid  "click here for an into" popup
        time.sleep(10)

        WebDriverWait(driver, 5).until(cond.element_to_be_clickable((By.CSS_SELECTOR, "a[href^='/transactions']")))
        driver.find_element_by_css_selector("a[href^='/transactions']").click()

        WebDriverWait(driver, 5).until(cond.visibility_of_element_located((By.CSS_SELECTOR, "button[data-transactionid]")))

        transactions = []

        previous_top = None
        while True:
            pagetop = driver.execute_script('return(document.querySelector("main div").offsetTop);')
            if previous_top is None:
                previous_top = pagetop
            elif pagetop == previous_top:
                status("No movement of page, we're done!")
                break
            else:
                previous_top = pagetop
            for g in driver.find_elements_by_css_selector('div[role="transactions-group"]'):
                date = datetime.date.fromtimestamp(int(g.get_attribute("data-group"))/1000)
                if date < datetime.date.today() - datetime.timedelta(days=60):
                    break
                for t in g.find_elements_by_css_selector('button[data-transactionid]'):
                    transid = t.get_attribute("data-transactionid")
                    # Get the two spans using xpath since it otherwise traverses
                    (titlespan, amountspan)= t.find_elements_by_xpath('./child::span')
                    title = titlespan.find_element_by_tag_name('span').text
                    timeval = titlespan.find_elements_by_tag_name('span')[1].text
                    try:
                        fulltime = datetime.datetime.combine(date, datetime.datetime.strptime(timeval, "%H:%M %p").time())
                    except:
                        fulltime = datetime.datetime.combine(date, datetime.time(0, 0, 0))
                    if timeval.startswith('Pending') or timeval.startswith('Failed') or timeval.startswith('Insufficient balance'):
                        continue
                    if re.match(r'(Sold|Bought) \w+ (to|with) \w+', title):
                        continue
                    (what, currency, amount) = amountspan.text.split()
                    if currency != 'SEK':
                        raise Exception("Somehow found currency {}".format(currency))
                    # Turn amount into a decimal *and* turn it negative (to match the kind of
                    # input we have from the other crawlers)
                    amount = -Decimal(amount.replace(',', ''))
                    if what.strip() == "-":
                        amount = -amount
                    transactions.append((transid, fulltime, title, amount))
            else:
                # We ran to the end so hit page down and check the next page
                ActionChains(driver).send_keys(Keys.PAGE_DOWN).perform()
                time.sleep(2)
                continue
            # Get here if we break:ed out of the inner loop, so break out again
            break
    finally:
        # Make sure we always shut down the chrome
        driver.quit()

    csv = csv.writer(args.output)
    csv.writerow(['id', 'charge_date', 'description', 'amount'])
    for t in sorted(set(transactions), key=lambda x: (x[1], x[2])):
        csv.writerow(t)
