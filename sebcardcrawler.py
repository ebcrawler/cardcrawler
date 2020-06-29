#!/usr/bin/env python3

import argparse
import csv
import sys
from datetime import date
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as cond

cardtypes = {
    'saseurobonus': 'sase',
    'nordicchoice': 'cose',
}


def get_transaction_id(t):
    tt = t.find_element_by_css_selector("a.list-item-link")
    id = tt.get_attribute('id')
    if id:
        return id
    return tt.get_attribute('href').split('/')[-1]


def get_transaction_row(t, year):
    r = [get_transaction_id(t), ] + [c.text for c in t.find_elements_by_css_selector('ul.container li')]

    # Inject the year into the dates. For uninvoiced we use the current year.
    chargedate = date(int(year), *[int(x) for x in r[1].split('-')])
    postdate = date(int(year), *[int(x) for x in r[2].split('-')])

    # We have to special case when the chargedate was previous year and postdate is this year,
    # which happens right around the new year. It's always postdate that controls which month the
    # entry appears on.
    if chargedate > postdate:
        if chargedate.month == 12 and postdate.month == 1:
            chargedate = chargedate.replace(year=chargedate.year - 1)
        else:
            raise Exception("Transaction with chargedate ({}) before postdate ({}) found!".format(chargedate, postdate))

    r[1] = str(chargedate)
    r[2] = str(postdate)

    return r


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SEB cards transaction crawler")
    parser.add_argument('personnr', type=str, help='Personnr')
    parser.add_argument('cardtype', choices=cardtypes.keys(), help='Type of card')
    parser.add_argument('--months', type=int, default=2, help='Number of months to fetch')
    parser.add_argument('--output', type=argparse.FileType('w', encoding='UTF-8'), default='-', help='Write output to file (- for stdout)')
    parser.add_argument('--debug', action='store_true', help='Enable debug = view the chrome window')
    parser.add_argument('--chrome', type=str, default='chrome', help='Path to chrome browser to use')
    parser.add_argument('--chromedriver', type=str, default='chromedriver', help='Path to chromedriver binary to use')
    parser.add_argument('--nosandbox', action='store_true', help='Disable chrome sandbox (used in docker)')

    args = parser.parse_args()

    def status(msg):
        print(msg, file=sys.stderr)

    cardtype = cardtypes[args.cardtype]
    status("Getting card of type {}".format(cardtype))

    chrome_options = Options()
    chrome_options.binary_location = args.chrome
    if not args.debug:
        chrome_options.add_argument('--headless')
    if args.nosandbox:
        chrome_options.add_argument('--no-sandbox')
    driver = webdriver.Chrome(executable_path=args.chromedriver, options=chrome_options)

    # NOTE! No more code here before we open the try/finally, or we may leak running
    # chrome processes!

    try:
        # This is not always very fast
        driver.implicitly_wait(3)

        status("Initiating login...")
        driver.get('https://secure.sebkort.com/nis/m/{}/external/t/login/index'.format(cardtype))

        # Click log in with bank-id on other device
        driver.find_element_by_id("eidbtn1").click()

        # Fill out personnr
        driver.find_element_by_css_selector("input.id-number-input").send_keys(args.personnr)

        # Wait for it to realize we've done so
        WebDriverWait(driver, 5).until(cond.element_to_be_clickable((By.CSS_SELECTOR, 'a.ok')))

        # Click through to the BankId wait page
        driver.find_element_by_css_selector("a.ok").click()
        status("Confirm login in with bank-id")

        WebDriverWait(driver, 30).until(cond.title_contains('Mitt'))

        status("Login complete, getting uninvoiced transactions")
        WebDriverWait(driver, 30).until(cond.visibility_of_element_located((By.CSS_SELECTOR, 'section.overview div.container ul li a[href*=uninvoice]')))

        # Navitate to new transactions
        driver.find_element_by_css_selector("a[href*=uninvoice] strong").click()

        transactions = []
        tlist = driver.find_elements_by_css_selector('ul#cardTransactionContentTable li.list-item')
        for t in tlist:
            transactions.append(get_transaction_row(t, date.today().year))

        for n in range(args.months):
            status("Getting transactions for month {}".format(n+1))
            # Navigate to kontoutdrag
            driver.get('https://secure.sebkort.com/nis/m/{}/external/t/login/index#invoice'.format(cardtype))
            WebDriverWait(driver, 30).until(cond.visibility_of_element_located((By.CSS_SELECTOR, 'section.page-content ul.listing li')))

            # Navigate to the invoice
            driver.find_elements_by_css_selector('ul.listing li a')[n].click()

            # Wait for the new page to appear
            WebDriverWait(driver, 30).until(cond.visibility_of_element_located((By.CSS_SELECTOR, 'section#transactionTableContent ul.table li')))

            # Fetch the year from the header, so we can store it correctly
            txtinfo = driver.find_element_by_css_selector('table.invoice-details tbody tr:nth-child(3) td:nth-child(2)').text
            year = txtinfo.split()[1]

            # Get the contents!
            tlist = driver.find_elements_by_css_selector('section#transactionTableContent ul.table li.list-item')
            for t in tlist:
                transactions.append(get_transaction_row(t, year))

        # We're done, log out because we're nice
        driver.find_element_by_id('logoutbtn').click()
        time.sleep(1)
    finally:
        # Make sure we always shut down the chrome
        driver.quit()

    csv = csv.writer(args.output)
    csv.writerow(['id', 'charge_date', 'post_date', 'description', 'location', 'currency', 'foreignamount', 'amount'])
    for t in transactions:
        csv.writerow(t)
