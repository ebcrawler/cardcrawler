#!/usr/bin/env python3

import sys
import requests
import argparse
import getpass
import json
import csv
import functools
import re
from datetime import date

csvcolumns = [
    'charge_date',
    'post_date',
    'reference_id',
    'description',
    'amount',
    'type',
    'extended_details.additional_attributes.point_of_service_data_code',
    'extended_details.merchant.display_name',
    'extended_details.merchant.name',
    'extended_details.merchant.address.country_name',
    'extended_details.merchant.address.iso_numeric_country_code',
    'foreign_details.amount',
    'foreign_details.commission_amount',
    'foreign_details.iso_alpha_currency_code',
    'foreign_details.exchange_rate',
]


def list_tokens_from_dashboard(txt):
    # Fetch the react initial state, where we can find our tokens
    istate = re.search(r'__INITIAL_STATE__ = "([^<]*)";\s+</script>', txt).group(1).replace('\\"', '"').strip()

    j = json.loads(istate)

    numcards = 0
    for i in range(len(j)):
        if j[i] == 'core':
            jj = j[i+1][2]
            for ii in range(len(jj)):
                if jj[ii] == 'products':
                    jjj = jj[ii+1][1]
                    # selectedProduct holds the current one. but productList has the details
                    for iii in range(len(jjj)):
                        if jjj[iii] == 'productsList':
                            pl = jjj[iii+1][1:]
                            for n in range((int(len(pl)/2))):
                                for k in range(len(pl[n+1])):
                                    if pl[n+1][k] == 'account':
                                        for kk in range(len(pl[n+1][k+1])):
                                            if pl[n+1][k+1][kk] == 'display_account_number':
                                                if numcards == 0:
                                                    print("")
                                                print("Card ending in -{}: token {}".format(pl[n+1][k+1][kk+1], pl[n]))
                                                numcards += 1
    print("")
    if numcards:
        print("{} cards found.".format(numcards))
    else:
        print("No cards were found.")
    sys.exit(1)


def get_parsed_field(transaction, colspec):
    return functools.reduce(lambda o, k: (o and k in o) and o[k] or None, colspec.split('.'), transaction)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Amex transaction crawler")
    parser.add_argument('username', type=str, help='Amex web username')
    parser.add_argument('--password', type=str, help='Amex web password')
    parser.add_argument('--token', type=str, help='Amex token number')
    parser.add_argument('--months', type=int, default=2, help='Number of months to fetch')
    parser.add_argument('--format', choices=('csv', 'json'), default='csv', help='Output format')
    parser.add_argument('--jsonpretty', action='store_true', help='Pretty-print json output')
    parser.add_argument('--output', type=argparse.FileType('w', encoding='UTF-8'), default='-', help='Write output to file (- for stdout)')

    parser.add_argument('--listtokens', action='store_true', help='List available accounts/tokens')

    args = parser.parse_args()

    if not (args.token or args.listtokens):
        print("Must specify token or listtokens", file=sys.stderr)
        sys.exit(1)

    def status(msg):
        print(msg, file=sys.stderr)

    if args.password:
        password = args.password
    else:
        password = getpass.getpass('Amex password for {0}: '.format(args.username))
    if not password:
        status("No password given.")
        sys.exit(1)

    sess = requests.session()
    status("Logging in...")
    r = sess.post('https://global.americanexpress.com/myca/logon/emea/action/login', {
        'request_type': 'login',
        'Face': 'sv_SE',
        'UserID': args.username,
        'Password': password,
        'Logon': 'logon',
        'version': 4,
        'DestsPage': 'https://global.americanexpress.com/dashboard',
        'REMEMBERME': 'off',
    })
    r.raise_for_status()

    if args.listtokens:
        status("Fetching dashboard...")
        r = sess.get('https://global.americanexpress.com/dashboard')
        r.raise_for_status()

        list_tokens_from_dashboard(r.text)
        sys.exit(0)

    # Else fetch the transactions. We start by getting the statement periods.
    status('Getting list of statements')
    r = sess.get(
        'https://global.americanexpress.com/api/servicing/v1/financials/statement_periods',
        headers={'account_token': args.token}
    )
    r.raise_for_status()
    statements = r.json()

    # We start by getting the first one, which will tell us the breakpoint
    # in the month, and then we can loop back from there.
    statementend = None
    all_transactions = []
    for i in range(args.months):
        statementend = statements[i]['statement_end_date']
        params = {
            'status': 'posted',
            'limit': 1000,
            'statement_end_date': statementend,
        }
        status("Fetching statement that ends in {}".format(statementend))

        r = sess.get(
            'https://global.americanexpress.com/api/servicing/v1/financials/transactions',
            params=params,
            headers={'account_token': args.token}
        )
        r.raise_for_status()

        j = r.json()
        status("Loaded {} transactions from statement ending on {}".format(len(j['transactions']), statementend))
        all_transactions.extend(j['transactions'])

    # All is loaded, so time to generate the output
    if args.format == 'json':
        # In json we just dump the whole thing out
        print(json.dumps(all_transactions, indent=args.jsonpretty and 2 or None), file=args.output)
    elif args.format == 'csv':
        csv = csv.writer(args.output)
        csv.writerow(csvcolumns)
        for t in all_transactions:
            csv.writerow([get_parsed_field(t, c) for c in csvcolumns])
    else:
        print("Unknown output format", file=sys.stderr)
        sys.exit(1)
