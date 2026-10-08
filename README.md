# Your ERP — Phase 1

An online system for invoices, payments, customer balances, statements and month-end, with WhatsApp sending built in. Staff log in from any computer or phone with a browser.

## What's in Phase 1

- **Customers**: WhatsApp number, sales rep, payment terms, credit limit, and opening balance (for moving from QuickBooks)
- **Items**: products with default prices
- **Invoices**: by sales rep, with discount and sales tax. They can be sent on WhatsApp automatically when saved, or with one click.
- **Payments received**: FIFO or bill-wise, with cash, cheque, bank and so on. A receipt showing the new balance can go on WhatsApp automatically.
- **Balances**: payments are applied to the oldest invoices first, so each invoice shows Open, Part paid, Paid or Overdue
- **Statements**: any date range, with balance brought forward and a running balance. View as PDF or send on WhatsApp.
- **Month-end**: pick a month, see every customer with a balance, and send all statements in one go. Customers already sent that month are skipped.
- **Reports**: sales by rep, customer or item; payments received; customer balances; aging (who is overdue and by how long). All can be downloaded for Excel.
- **Users and control**:
  - *Admin* can do everything.
  - *Accounts* can do everything except users and settings.
  - *Sales rep* sees only their own customers and can create invoices and receive payments, but can't edit or void.
- **Safety**: nothing is ever deleted. Invoices and payments are *voided* with a reason, and the record stays. Every WhatsApp message is logged.

---

## 1. Try it on your own PC (5 minutes)

1. Install **Python 3.12** from python.org and tick **"Add python.exe to PATH"** during install.
2. Unzip this folder and double-click **start-windows.bat**. Answer **y** to load demo data.
3. Open <http://localhost:8000> and log in as **admin / admin12345**. To see the sales-rep view, log in as **rizwan / rizwan123**.

WhatsApp is in **test mode**, so PDFs are made but nothing is sent. Try creating an invoice, receiving a payment, opening a customer's statement, and running Month-end.

To start fresh with your own company, close the window, delete the `data` folder, and run start-windows.bat again (answer **n**). You'll be asked to create your admin login.

---

## 2. Put it online

**What you need:**
- A small cloud server (VPS) with **Ubuntu 24.04**, 2 GB RAM. DigitalOcean, Hetzner, Vultr or a local Pakistani host all work. Expect roughly US$10–20 a month.
- A domain name, for example `erp.yourcompany.com`.

**Steps** (a local IT person can do this in under an hour):

1. In your domain's DNS settings, add an **A record** pointing `erp.yourcompany.com` to the server's IP address.
2. Connect to the server with SSH and run:
   ```bash
   curl -fsSL https://get.docker.com | sh
   mkdir -p /opt/erp && cd /opt/erp
   # upload the contents of this folder here (e.g. with WinSCP or scp)
   echo "DOMAIN=erp.yourcompany.com" > .env
   docker compose up -d --build
   ```
3. Open `https://erp.yourcompany.com` and create your admin login. The HTTPS certificate is set up automatically.
4. Go to **Settings** and fill in your company details, currency, tax, and **next invoice number** (use the number after your last QuickBooks invoice).
5. Add **Sales reps**, then **Users** for each staff member.

**Daily backups:** run `crontab -e` on the server and add:
```
0 2 * * * cd /opt/erp && docker compose exec -T erp python manage.py backup
```
Backups are saved in `/opt/erp/data/backups/`. Also copy them off the server regularly, for example to Google Drive or your PC.

**Updates:** when I send you a new version, upload the files (keeping the `data` folder) and run `docker compose up -d --build`.

---

## 3. Connect WhatsApp

1. **Number**: get a mobile number that is **not** already on WhatsApp or WhatsApp Business. It becomes your official sending number, with your company name shown.
2. **Meta setup**: in <https://business.facebook.com> create or choose your business. Then at <https://developers.facebook.com>: **My Apps → Create app → Business**, add **WhatsApp**, go to **API Setup**, then add and verify your number. Copy the **Phone number ID**.
3. **Permanent token**: go to Business Settings → Users → **System users** → Add (Admin). Assign your app with full control, then **Generate token** with the `whatsapp_business_messaging` and `whatsapp_business_management` permissions. Don't use the 24-hour test token.
4. **Payment method**: add one in WhatsApp Manager. Meta charges a small fee per message conversation.
5. **Templates**: in WhatsApp Manager go to **Message templates → Create**, category **Utility**, language **English**, header type **Document**:

   | Template name | Body text (keep the `{{ }}` numbers in this order) |
   |---|---|
   | `invoice_notification` | Dear {{1}}, please find attached invoice {{2}} for {{3}}, due by {{4}}. Thank you for your business. |
   | `quotation_notification` | Dear {{1}}, please find attached quotation {{2}} for {{3}}, valid until {{4}}. We look forward to hearing from you. |
   | `payment_receipt` | Dear {{1}}, we have received your payment of {{2}} on {{3}}. Your balance is now {{4}}. Receipt attached. |
   | `statement_notification` | Dear {{1}}, please find attached your account statement. Balance due: {{2}} as of {{3}}. |
   | `balance_reminder` (header: **None**, text only) | Dear {{1}}, your current balance with us is {{2}} as of {{3}}. Please contact us for any query. |

   You can reword them, or add Urdu versions. If you do, change the names or language code in Settings.
**Sending documents as a picture instead of a PDF (optional).** A picture is saved in the customer's phone gallery and is easier to find in WhatsApp than a PDF. In Meta, make a second copy of each template above with the header type set to **Image** and the same body text, and name it like the original plus `_img` (for example `invoice_notification_img`, `payment_receipt_img`, `statement_notification_img`, `quotation_notification_img`). Then in **Settings → WhatsApp** set *Send documents on WhatsApp as* to **Picture (JPEG)**. One-page documents go as a picture; longer ones (for example a long statement) still go as a PDF with the normal template. Keep the PDF setting if you also want the customer to be able to print or search the document.

6. In the ERP go to **Settings → WhatsApp**. Paste the Phone number ID and token, and untick **Test mode**. Send an invoice to your own number first.
7. Optional: tick **Send invoice automatically** and **Send payment receipt automatically**.

---

## 4. Moving from QuickBooks 2024

Use **Import from QuickBooks** (Admin menu). Export these three reports from QuickBooks to Excel, all dated your cut-over day, and import them in this order:

1. **Items**: Reports → List → *Item Price List*
2. **Customers**: Reports → List → *Customer Contact List*. Use *Customize Report* to add Mobile, Rep and Terms.
3. **Open invoices**: Reports → Customers & Receivables → *Open Invoices*

Each unpaid QuickBooks bill comes across as its own invoice, with its number, date and open amount, so **bill-wise payments work from day one**. Unapplied QuickBooks payments or credits come across as advances. Every import shows a preview first, and importing the same file twice skips what's already there.

Your QuickBooks backup file (.QBB) can't be read directly. It is QuickBooks' own locked format, so the Excel exports above are the way in.

---

## Sending balance and statements any time

On each customer's page, the **Statement & balance** box lets you pick:
- **Type**: All activity, Unpaid bills only, or Balance only.
- **Options**: aging boxes, and item details of each invoice.

Then press **📄 PDF**, **📊 Excel** or **✆ Send on WhatsApp**. Month-end has the same choices, plus one combined PDF of all statements for printing.

Every list and report (customers, invoices, payments, aging, sales and so on) has **📊 Excel** and **📄 PDF** buttons.

The Customers list also has quick **✆ Balance** and **✆ Statement** buttons for each customer:
- **Balance**: a short message with the current balance.
- **Statement**: a PDF. Its type is set per customer (Edit customer → *Statements show*):
  - *All activity*: invoices and payments from the 1st of last month to today.
  - *Unpaid bills only (corporate)*: only the invoices that are still unpaid, with the aging boxes.

Month-end uses each customer's statement type automatically.

---

## Payments: FIFO or bill-wise

Each customer has a default, set on the customer's page: **Oldest bills first (FIFO)** or **Bill-wise**. On the Receive Payments screen you can switch for any single payment:
- **Auto apply**: the payment pays the oldest bills first.
- **Bill-wise**: tick the bills, or type the amount against each bill. Anything left over is kept as an advance.

Each payment shows *Where this payment went*, and each invoice lists the payments made on it. Admin and Accounts users can edit a payment to change which bills it pays.

---

## Help

| Problem | Fix |
|---|---|
| Forgot admin password | On the server: `docker compose exec erp python manage.py reset-password admin NEWPASSWORD` |
| "WhatsApp refused: template name does not exist" | The template isn't approved yet, or its name or language doesn't match Settings |
| "Recipient phone number not in allowed list" | You're still using Meta's test number. Finish step 3.2 with your real number |
| Message sent but the customer didn't get it | The customer's WhatsApp number may be wrong. Check the WhatsApp log |

## Phase 3 (now included)

- **Suppliers** with what we owe them, **purchase bills**, and **supplier payments** (oldest bills first).
- **Returns (credit notes)**: they reduce the customer's balance (statements, aging, FIFO) (the goods are counted back in the warehouse with a Goods receipt).
- **Expenses** by category.
- **Reports**: Profit & loss, payables aging, purchases by supplier or item, expenses by category, and inventory valuation. All export to Excel and PDF.

## Warehouse (separate from invoices, like LoMag)

Invoices, purchase bills and returns **do not move stock**. Stock only moves through warehouse documents:

| Document | What it does |
|---|---|
| Goods receipt (GRN) | Stock in from a supplier, with cost |
| Delivery challan (DC) | Stock out to a customer (vehicle / transport, signatures on print) |
| Transfer (TRF) | Moves stock between warehouses |
| Adjustment (ADJ) | Damaged, lost or found (+/−) |
| Stock count (CNT) | Type the counted qty; the system corrects the difference |
| Opening stock (OPN) | Starting quantities per warehouse |

- Multiple warehouses (Warehouse → Warehouses). Stock levels are shown per warehouse, with a stock card per item and a Movements report (opening/in/out/closing). Everything exports to Excel and PDF.
- Barcode scan mode: scan the same item repeatedly and its qty goes up by 1 each time. Items have Barcode, Location/shelf and Minimum stock fields.
- Optional links: **Dispatch goods** on an invoice pre-fills a challan, and **Receive into warehouse** on a purchase bill pre-fills a GRN.
- **Storekeeper** role: sees only the warehouse, with no prices or costs.
- Settings → Warehouse → "Allow negative stock" (off by default: a challan can't send out more than is on the shelf).

## Dashboard

- **Period buttons:** Today, 7 days, This month, Last month, This FY (July–June), or any from–to dates.
- **Summary:** sales, collected, net profit, purchases, expenses (including salaries), cash in − cash out, receivable and payable.
- **Needs attention:** overdue customers, customers over their credit limit, invoices not yet dispatched, low stock, supplier bills past due, and salaries not finalised or not paid. Click any box to open the list.
- **Quick actions:** one click to invoice, payment, delivery challan, goods receipt, purchase bill, pay supplier, expense, return, salary, month-end and reports.
- Reps see only their own sales, collections and receivable. They don't see profit or purchases.

## Salary (payroll)

1. **Employees:** code, name, father name, CNIC, WhatsApp, designation, department, joining/leaving date, basic salary + allowances, and paid by cash or bank (with account/IBAN).
2. **Advances & loans:** record the amount given and a monthly deduction (leave it blank to deduct it all from the next salary). It is recovered automatically in the salary sheet.
3. **Monthly salary sheet:** one row per employee. Type absent days, overtime hours, bonus and other deductions, and the totals update as you type. People who joined or left mid-month get their absent days filled in automatically. Save as a draft, then **Finalise**.
4. **Pay:** tick the employees and mark them paid (date + cash/bank). The **Bank transfer list** exports to Excel.
5. **Payslips:** PDF per employee or all in one file, with amount in words and signature lines. Send on WhatsApp one by one or to everyone (WhatsApp template `salary_slip` with parameters: name, month, net salary).
6. **Reports:** the salary sheet in Excel/PDF, a salary register for any range of months, and advances outstanding.
7. Finalised salaries appear in **Profit & loss** as "Salaries & wages". Don't also enter salaries under Expenses.
8. **Who can see salaries:** admin only by default. Tick "Accounts users can see and run salaries" in Settings → Salary to give access to accounts users. Settings → Salary also has the per-day basis (actual days in month or 30), hours per day and the overtime rate (1×, 1.5×, 2×).

## Update: invoice, report and salary improvements

- **Invoice toolbar:**
  - **Print DC:** a separate A4 delivery challan with no prices. It is not linked to the warehouse; print it only when a customer needs it.
  - **Delivered / Not delivered:** click to mark the invoice. The invoice list has a Delivery column and filter.
  - **Statement menu:** all activity or unpaid bills only, as PDF or Excel.
- **Import lines from Excel** on the invoice screen. Use an .xlsx or .csv file with columns Item code, Qty and Price (optional: Description, U/M, CTN qty). The screen has a sample file to download.
- **Aging:**
  - pick the range from 30 to 180 days, in steps of 30
  - count days from the due date or the invoice date
  - show only bills older than a number of days
  - the detail report shows exact days (days since the bill and days overdue)
- **Unpaid bills – all customers:** every customer's unpaid bills, with a subtotal per customer, as PDF or Excel. Open it from the Invoices and Customers pages.
- **New receipt PDF:**
  - your logo, with the amount in large type and in words
  - which bills the payment paid
  - the balance before and after the payment
  - signature lines
- **Salary sheet:**
  - a **Loan instalment** column for big loans recovered monthly
  - an **Advance** column for small advances
  - an editable **Allowance** column for each month

## Three companies

- **Company selector** at the top of every page: a searchable dropdown with **All companies** (everything together, live) and each company with its logo. The dashboard, lists, reports and Profit & loss follow the company you pick.
- **Settings → Companies:** each company's printed name, short code and colour, whether it is GST registered (with default tax %), NTN, GST/STRN number, address, phone, logo, invoice note and next invoice number.
- **Customers** belong to one company. Their invoices, payments and returns go under that company:
  - invoice numbering is separate for each company
  - GST is charged only by GST-registered companies (forced to 0% for a non-GST company)
  - the PDF prints that company's logo, NTN and GST number, titled "Sales Tax Invoice" when tax is charged
  - once a customer has invoices or payments, their company can't be changed
- **Suppliers and warehouse stock are shared.**
  - Purchase bills have **Bought under** (default: the purchase company in Settings → Companies).
  - Supplier payments have **Paid from**, so any company can pay any bill. The supplier's balance is one combined figure.
  - Expenses have **Paid by company**.
- **Salaries** belong to the salary company (default: the first company, e.g. Three Flowers).
- **Upgrading an existing database** keeps everything under one company made from your old settings. Add the other companies in Settings → Companies.

## Printing and the print designer

- Invoices, delivery challans and receipts print in a **modern design** that matches the ERP:
  - the company's logo and colour
  - clean tables and totals cards
  - signature lines
  - a footer band
- **Delivery challan:** no item codes and no prices. It shows description, quantity, U/M and cartons.
- **Admin → Print designer:** drag, resize and restyle anything on the page for each document and each company, or for all companies at once:
  - logo, company details, fields like {customer_name} or {number}, custom text, boxes and lines
  - the items table: columns, headings, widths, colours, lines
  - totals, with a highlighted row
  - fonts: Helvetica, Times, Courier, Poppins and DejaVu Sans; add your own .ttf files to `data/fonts/`

  You can start from the Modern, Classic or Minimal layout. **Preview PDF** shows it with your latest real document, **Save & use** switches it on, and "Use the standard print" switches it off.
- Long invoices continue onto extra pages automatically. Everything above the items table repeats on each page, and the totals print on the last page.
- To go back to the old QuickBooks-style print, tick the option in Settings → Invoices.
- The `your_logos/` folder contains the logos you sent. Upload them in Settings → Companies.

## Email (from your Gmail)

- Customers have an **Email** and a **Send by** choice: WhatsApp, Email, or both. Invoices, receipts, statements, balance messages and month-end follow this choice.
- Invoices, receipts and customer pages have an **Email** button. New invoices have **Save & Email**.
- **Setting up Gmail:**
  1. Turn on 2-Step Verification on the Google account.
  2. Create an **App Password** (Google Account → Security → App passwords).
  3. Enter the Gmail address and the App Password in **Settings → Email**. Never send the password in a chat or message.
  4. Untick **test mode** to start sending.
- Every email is recorded in the **Messages log**, which has a Channel column.

## Invoice and print improvements

- **PO no.** and **Reference** fields on invoices. They print only when filled in.
- New invoices have **Save & WhatsApp** and **Save & DC** buttons.
- The left menu stays where you scrolled it when you open a page.
- Every print has the company logo: invoice, DC, receipt, statement, credit note, payslip, warehouse documents and report PDFs.
- The customer statement uses the same modern design as the ERP.

## Users & roles (like QuickBooks)

- **Admin → Roles & permissions** lists the roles on the left. Click one to see its description, the users who have it, and a tick/cross list of what it can do. Use **New role**, **Edit**, **Duplicate** or **Delete**.
- **Tick boxes** for each area:
  - customers, invoices, payments, returns, statements, items
  - purchases, supplier payments, expenses
  - warehouse, salary
  - reports (sales, finance, costs)
  - admin (users, settings, import)
  - a **Limits** tick that restricts a rep to their own customers
- **Ready-made roles:** Admin, Full Access, Accountant, Accounts Receivable, Accounts Payable, Sales, Sales rep (own customers), Payments only, Purchasing, Inventory / Storekeeper, Warehouse manager, Payroll, Finance and View-Only. You can change any of them, or duplicate one and adjust it.
- **Admin → Users:** choose one role per user. A role with the "own customers" limit needs a linked sales rep.
- The menu shows only what the user is allowed to use, and blocked pages are refused even if typed into the address bar.
- Users without sales access start on their own area instead of the dashboard (warehouse, salary or purchases).
- **Existing users keep their access:**
  - admin → Admin
  - accounts → Full Access (without salary, unless salary access was switched on before)
  - rep → Sales rep
  - store → Inventory / Storekeeper
- **Safety checks:**
  - The Admin role can't be deleted and always keeps Users & roles.
  - You can't remove your own access.
  - A role still given to someone can't be deleted.

## PO batch billing (one PO, many branches)

1. **Add the branches.** On the head-office customer's page, open the **Branches** tab. Each branch has a name, code, address, contact, phone and email.
   - You can add branches one at a time or import them from Excel/CSV. Use the columns Branch name, Code, Address, Contact, Phone, Email.
   - Tick **Closed** when a branch shuts down.
2. **Sales → PO batch billing → New PO.** Choose the customer and enter their PO number and date.
3. **Make an invoice for each branch.** On the PO screen, click **Make invoice** next to each branch.
   - The invoice is billed to head office and shipped to that branch, with the PO number already filled in.
   - Its **DC** prints the branch's name and address.
   - You can pick a branch on any invoice with **Ship to (branch)**.
   - Invoices you made earlier can be added with **Add existing invoices…**.
4. **Track each delivery.** Enter the courier (TCS, LCS…) and the tracking number. **Track ↗** opens the courier's tracking page. Click **Mark delivered** when the branch has the goods.
5. **Make the combined invoice.** When the deliveries are done, click **Make combined invoice**.
   - Page 1 lists every branch: its invoice, courier, tracking number, delivery date and amount, with the tax and the total.
   - Page 2 is an item summary with the quantities of all branches together.
   - Send it to head office by WhatsApp or email.
6. **Receive the PO payment.** Head office pays once. **Receive PO payment** fills in the amount and ticks every branch invoice on the PO.

The branch invoices hold the amounts in the customer's account, and the combined invoice is a summary of them, so the PO total is counted only once.

Couriers and their tracking links are listed in **Settings → Invoices → Couriers**, one per line as `Name | link with {no}`. Please check the TCS and LCS links with a real tracking number once. If a link doesn't open the right page, paste the correct one there.

## Update: notes pages 4 and 5

**Invoices**
- **Transaction history** on every invoice, opened with the **History** button. It lists every part payment with its date, receipt no., cash or cheque, who entered it and the balance left after it.
- **Deliver to:** an optional delivery address, for example a bank branch.
  - Pick a branch and it fills itself in, or type any address.
  - When it is filled, the invoice prints two boxes, Bill to and Deliver to. When it is empty, nothing extra prints.
  - The delivery challan prints the delivery address.
- **Customer code / ID** (C-0001…) on every customer. It prints on the invoice and the DC. Existing customers got codes automatically.

**Customers**
- **City** on every customer. Existing cities were read from the addresses where possible.
- Filters:
  - **Rep** and **City** with tick boxes, so you can pick several (e.g. Rizwan + Ali)
  - **Sort** A→Z, Z→A, balance high or low, code, city
  - a **✕ Clear filter** button whenever a filter is on
- The balance report has the same sort and clear filter.

**Payments and approvals**
- "Receive payment" is now called **Collection** everywhere.
- **All transactions** shows invoices, collections and returns in one list.
  - Search by customer, code, number, PO or cheque.
  - Filter by date, exact amount, minimum or maximum amount, and void or active.
  - Sort and export to Excel or PDF.
- The **search box at the top** now searches everything: customers, invoice and receipt nos., cheque nos., amounts, POs and items.
- **Void / delete needs admin approval.**
  - When staff press Void on an invoice, collection, return or supplier payment, a request goes to the admin and nothing changes yet.
  - The admin sees **Void approvals** with a red count in the menu and an alert on the dashboard. Approve voids the document (it stays in the history). Reject changes nothing.
  - Only roles with the **Approve void / delete requests** tick (the Admin role) void directly.
- **PO collection:** on the Collection screen a billed PO shows as **one line**, "Combined inv. 1 · PO-7788 (3 branch bills)". Ticking it pays all its branch invoices.

**Warehouse**
- "Delivery challan" in the warehouse is now **Goods Issue Note (GIN)**. It is **not linked to invoices**. The **Print DC** button on invoices stays for customers who want a DC.
- Entries are **cartons × pieces per carton + loose pieces**.
  - Each item has a usual carton size, which you can change on any line.
  - The same item can be entered twice with different carton sizes, e.g. 10 ctn × 24 and 5 ctn × 12.
- Stock is shown as cartons by size plus loose, e.g. "228 ctn × 12 + 17 loose", along with the total pieces.
- Each item shows **cost value** and **sale value**; the sale value uses the item's sale price per piece.
- A stock count can also have several lines per item.

**Other**
- **Aging** now counts days from the **invoice date** (you can still switch to the due date). The dashboard age chart and statements do the same. Only overdue bills show under **Needs attention**.
- **Salary rule (month = 30 days):** basic is paid for the days present, from the first absent day. The allowance is paid in full up to 10 absent days; from 11 absent days it is also paid for the days present only. Example: basic 50,000 + allowance 10,000 with 10 absents = 33,333 + 10,000 = 43,333; with 11 absents = 31,667 + 6,333 = 38,000. Change the 10 days in Settings → Salary.
- **Payslips print on A5**, showing the loan and advance balances still to recover separately.
- **Print templates** (Admin → Print templates): 7 styles: Modern, Bold header, Elegant, Corporate, Compact, Classic and Minimal. Pick one per company with one click; it sets the invoice, DC and receipt together. Fine-tune it in the Print designer, which can also start from any template.

## Suppliers: PDF, print and WhatsApp

- **Every supplier** has a **Statement / print** menu with three choices: all activity, this year, or unpaid bills only. Each one opens a PDF you can print or save.
- **WhatsApp** sends the statement PDF to the supplier's WhatsApp number. You can also send it from the supplier list.
- **Purchase bills** have a **Print / PDF** button.
- **Supplier payments** have a **payment advice PDF** and a **WhatsApp** button. The advice shows the amount paid, the cheque or transfer details, the balance still owed and the unpaid bills.
- Supplier messages appear in the Messages log. You can set a WhatsApp template for suppliers in Settings → WhatsApp.

## Reports: filters and item groups

- **Item groups:** every item can belong to a group (Staplers, Glue sticks, Files…).
  - Set it on the item, or on the **Items** page tick many items and use **Set group**.
  - The Items page can filter and sort by group.
- **Filter boxes on reports:**
  - **Customer** (type part of a name or code)
  - **Item** (code or name)
  - **Item group** (tick one or more)
  - **Rep** and **City** (tick several)
  - **✕ Clear filter** whenever a filter is on

  They are on sales summary and detail, collections, balances, aging, unpaid bills, transactions, payments and purchases.
- Pick one customer and one item on **Sales detail** to see every line they bought, with a subtotal for each customer, item, group or rep.
- **Group by item group:** sales summary and detail, and purchases (by supplier, item, item group, or every line).
- On the sales summary, an item or group filter shows quantity, invoices, customers and amount for just that item or group.

## Coming next

AI reading of bill and cheque photos, Shopify (online store), sales orders / purchase orders, purchase returns, automatic month-end statements on the 1st, overdue reminders on WhatsApp, sales orders, cash & bank book, a full chart of accounts and balance sheet, and a rep mobile view.
