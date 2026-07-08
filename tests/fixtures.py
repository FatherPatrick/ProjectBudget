"""Small anonymized CSV samples shaped like each bank's real export."""

CHASE_CREDIT_CSV = """\
Transaction Date,Post Date,Description,Category,Amount,Type,Memo
06/01/2026,06/02/2026,STARBUCKS STORE 123,Food & Drink,-5.75,Sale,
06/03/2026,06/04/2026,AMAZON.COM*AB12CD,Shopping,-42.10,Sale,
06/05/2026,06/05/2026,Payment Thank You-Mobile,,500.00,Payment,
"""

CHASE_DEBIT_CSV = """\
Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
CREDIT,06/05/2026,DEEL INC PAYROLL PPD ID: 123,2000.00,ACH_CREDIT,3000.00,
DEBIT,06/06/2026,NW NATURAL BILL PAY,-80.25,ACH_DEBIT,2919.75,
DEBIT,06/07/2026,ATM WITHDRAWAL 06/07,-100.00,ATM,2819.75,
"""

BOFA_CREDIT_CSV = """\
Posted Date,Reference Number,Payee,Address,Amount
06/07/2026,24001234567,NETFLIX.COM,CA,-15.49
06/08/2026,24001234568,TRADER JOE'S #42,PORTLAND OR,-63.20
"""

# Same shape as the Chase debit export but with the summary block some banks
# prepend before the real header row.
CHASE_DEBIT_WITH_PREAMBLE_CSV = """\
Account Summary
Beginning Balance,1000.00

Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
DEBIT,06/06/2026,NW NATURAL BILL PAY,-80.25,ACH_DEBIT,919.75,
"""

# Two identical purchases on the same day — must import as two transactions.
CHASE_CREDIT_DUPLICATE_ROWS_CSV = """\
Transaction Date,Post Date,Description,Category,Amount,Type,Memo
06/01/2026,06/02/2026,STARBUCKS STORE 123,Food & Drink,-5.75,Sale,
06/01/2026,06/02/2026,STARBUCKS STORE 123,Food & Drink,-5.75,Sale,
06/01/2026,06/02/2026,STARBUCKS STORE 123,Food & Drink,-5.75,Sale,
"""
