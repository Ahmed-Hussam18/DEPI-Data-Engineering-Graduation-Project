
# Data Sources

This file documents every data source of the Egypt Economic Intelligence Platform: what it is, how it is collected, which rules apply, and what its known limits are.

# 1. FX and Gold: fawazahmed0 Currency API (R1)

| Item | Value |
|---|---|
| Type | REST API, JSON, no API key |
| URL | `https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/usd.json` (`{date}` = `latest` or `YYYY-MM-DD`) |
| Fallback | `https://{date}.currency-api.pages.dev/v1/currencies/usd.json` |
| Data | 200+ currencies and metals, daily, USD as base |
| EGP support | VERIFIED 2026-11-26: `usd.json` for `latest` has `egp` (54.21) and `xau`, 340 codes in total. The connector still refuses a response without `egp` |
| Gold | `xau` = troy ounces per 1 USD. We derive EGP per gram: `egp / xau / 31.1035`, then multiply by karat/24 for 24K, 21K and 18K |
| Rate limits | VERIFIED 2026-11-26: the repository README says "No Rate limits". We call it once a day |
| Terms | VERIFIED 2026-11-26: the GitHub repository `fawazahmed0/exchange-api` carries the CC0 1.0 licence (public domain) |
| History | VERIFIED 2026-11-26 on the jsDelivr URL: the first date available is **2024-03-02** (2024-03-01 and earlier answer 404). Backfill range for task 3.13: 2024-03-02 to today |
| Limitation | Gold is the international spot price converted to EGP. It is NOT the jeweller's price in Egypt |
| Sample | `tests/samples/fx_gold_usd_latest.json` |
| Fallback plan | If EGP/XAU is missing or the API disappears, switch to another API with the same output shape. Only `fx_gold.py` changes |

# 2. World Bank API (R1)

| Item | Value |
|---|---|
| Type | REST API, JSON, no API key |
| URL | `https://api.worldbank.org/v2/country/EGY/indicator/FP.CPI.TOTL.ZG?format=json&per_page=500` |
| Data | Egypt, Inflation, consumer prices (annual %), one value per year |
| Gaps | Some years have `value: null`. Kept as NULL; staging decides (task 4.10) |
| Frequency | Annual, so we collect it monthly or less |
| Rate limits | No key; we make one call per run |
| Terms | World Bank open data terms, commonly CC BY 4.0: VERIFY and cite the World Bank in the demo |
| Sample | `tests/samples/world_bank_egy_inflation.json` |

# 3. Official File: CBE Consumer Price Index (R1)

**Status: CHOSEN (task 1.16)**

| Item | Value |
|---|---|
| Publisher | Central Bank of Egypt (CBE), Economic Research, Time Series. The index itself is calculated by CAPMAS and republished by the CBE |
| Page | `https://www.cbe.org.eg/en/economic-research/time-series/downloadlist?category=706A9057F8454F7284BE8143070D88C4` (Inflation, CPI, Monthly) |
| Direct link | `https://www.cbe.org.eg/-/media/project/cbe/listing/time-series/inflation/cpi/cpi--monthly_.xls` ("All Years") |
| Per-year files | `.../cpi/cpi-monthly-2025-2026.xlsx` (same layout, one fiscal year) |
| Format | Excel. One sheet per fiscal year (July to June), 21 sheets from 2005/06 to 2025/26 |
| Content | CPI and weights for the main groups, urban Egypt, base 2018/2019 = 100. We use the "All Items" row (Arabic: الرقم العام) |
| Headers | Row with month labels in English ("July 2025", "Aug. 2025", "Sept. 2025"); row labels in Arabic and English; column C = relative weights |
| Update frequency | Monthly (CBE page showed "Last Updated 09 Nov 2026" for the October 2026 figure). The xls we downloaded was last saved May 2026 and ended at April 2026, so the file can lag the page |
| Size | About 350 KB (xls, all years) |
| Terms | No licence text on the page. Public statistical data from a public institution. VERIFY the CBE "terms of use" before the demo and cite CBE / CAPMAS as the source |
| Our indicator codes | `CPI_URBAN_INDEX` (index as published) and `CPI_URBAN_YOY` (year-over-year %, computed in staging) |
| Parser | `parse_cbe_cpi_workbook()` in `src/connectors/official_file.py`. 230 monthly values from 2005-07 to 2026-04 |
| Sample | `tests/samples/cbe_cpi_monthly_2025_2026.xlsx` (real file, fiscal year 2025/26) |

Known limits (be honest in the demo):

- The file lags the CBE web page by a few months.
- Months not published yet are empty cells. We skip them, we do not store NULL.
- Gaps inside the source file: 2007-09 to 2008-06 and 2009-09 to 2010-06 (those two sheets only hold the first months in the "All Items" row layout we read).
- The 2006/07 sheet labels August 2006 as "Aug.2007" (typo in the source). The parser takes the year from the fiscal year, not from each label.
- The CBE firewall can answer 403 ("Request Rejected") to scripts. The connector sends a browser User-Agent and checks the download really is an Excel file. If it is still blocked, download the file by hand and set `OFFICIAL_FILE_PATH` (the connector then saves and registers that copy in `raw.files`).
- Headline inflation (the annual %) is not in this file. It is the YOY we compute from the index.

Other candidates we did not choose: CAPMAS monthly bulletin (PDF, harder to parse), CBE core inflation (published as PDF press releases).

# 4. Static Shopping Site: Metro Markets (R2)

| Item | Value |
|---|---|
| Site | https://www.metro-markets.com |
| Technique | `requests` + `BeautifulSoup` (server-rendered HTML, no JavaScript needed) |
| Data | Public shelf prices of a fixed basket of 15 staple products |
| Schedule | Daily, 06:00 Africa/Cairo |
| Currency | EGP, VAT inclusive (stated in the site's terms) |

## Why This Site

- Pages are server-rendered: names, prices and links are present in the raw HTML.
- Every product page exposes price, currency, availability and a stable numeric item ID in `<meta property="product:*">` tags.
- On 2026-10-22, the price matched in three places for all 15 basket products: the category-page card, the product-page price element, and the product meta tag.

## Responsible Scraping

- robots.txt (checked 2026-10-22): `User-agent: *` with an empty `Disallow:`, so nothing is disallowed.
- Terms and Conditions (https://www.metro-markets.com/terms-and-conditions, checked 2026-10-22): no clause about robots, crawling, scraping or automated access was found. The terms do not grant explicit permission either, and no written permission has been requested yet.
- Because robots.txt is fully open, the politeness rules come from us:
  - Identify the bot: `User-Agent: EcoPlatformBot/1.0 (student project)`.
  - At least 2 seconds between requests.
  - Production reads only the 15 basket product pages, once per day (about 15 requests).
  - No search, login, cart, checkout or pagination requests in production. Public prices only, no personal data.
  - Stop on 403, 429 or a captcha; never evade a block.
- Only code and small excerpts are published (see `tests/samples/`). Full pages are not republished.

## Page Structure Used by the Parser

| Field | Where it is found |
|---|---|
| Product ID | `<meta property="product:retailer_item_id">`, and the number at the end of the URL `/product/<slug>/<id>` |
| Current price | `<meta property="product:price:amount">`, cross-checked against `div.price p.after` |
| Old price (discount) | `div.price p.before` (empty when there is no discount) |
| Currency | `<meta property="product:price:currency">` (EGP) |
| Availability | `<meta property="product:availability">` |
| Name | `og:title`, first `<h5>`, last breadcrumb item |
| Category path | `nav[aria-label="breadcrumb"]` |
| Brand | `product:brand` (unreliable: private-label items show "Private Label", the whole chicken shows "Fresh") |
| Size / unit | Only inside the product name; product pages have no separate unit field |

Planned rule: the price is read from the meta tag; if it differs from the visible price element, the record is a structural validation failure.

## Fixed Basket (15 Products)

| # | Item (our label) | Product ID | Product name on site | Size | Price on 2026-10-22 (EGP) | Notes |
|---|---|---|---|---|---|---|
| 1 | Rice | 4613 | Al Doha Egyptian White Rice | 1 kg | 41.99 | |
| 2 | Sugar | 6896 | Rehana White Sugar | 1 kg | 39.99 | Only white sugar in its category; the other products are powdered or icing sugar |
| 3 | Flour | 6565 | Al Doha Fine Flour | 1 kg | 32.50 | Discount that day (old price 37.50) |
| 4 | Pasta | 4408 | Regina Spaghetti Pasta 1.6mm | 400 g | 25.99 | Discount that day (old price 30.99); the name differs on category cards |
| 5 | Lentils | 27685 | Metro Yellow Lentil | 500 g | 39.99 | |
| 6 | White beans | 27687 | Metro White Beans | 500 g | 64.99 | |
| 7 | Fava beans (canned) | 3513 | Harvest Plain Fava Beans | 400 g | 18.99 | Discount that day (old price 22.45) |
| 8 | Eggs | 9478 | Metro Eggs White | 30 pcs | 148.95 | Egg size is not stated on the page |
| 9 | Tea | 5522 | El-Arosa Dust Tea | 250 g | 53.95 | |
| 10 | Salt | 6563 | Cooks Iodized Table Salt | 700 g | 15.99 | |
| 11 | Milk | 25799 | Labanita Full Cream Milk Tetra | 1 L | 54.00 | |
| 12 | Tuna | 4226 | California Garden Solid Tuna | 185 g | 82.99 | The page description says it is packed in sunflower oil |
| 13 | White cheese | 1671 | Domty Feta Cheese Tetra Pack | 500 g | 54.99 | |
| 14 | Chicken | 33084 | Whole Chicken | 1 kg | 164.99 | Listed as a fixed 1 kg pack |
| 15 | Ghee | 41062 | Alexandria Ghee | 450 g | 291.99 | Tracked instead of cooking oil (see limits) |

This table fixes only which products are tracked. Index weights are decided separately (index view). A product is replaced only by team agreement, because the index compares the same product over time.

## Known Limits

1. Branch not selected: the site header shows "Choose Branch" and we do not select one, so prices are the default list. The site's terms say the range and prices may differ by delivery location.
2. Discounts: three basket products (6565, 4408, 3513) had a struck-through old price on the verification day. The current price is the price that is stored. The old price is not stored for now, because `staging.prices_clean` has no column for it; adding one is a shared-schema change that needs the team's agreement (R3).
3. No cooking oil: no bottled edible oil was found in the English catalogue (searches for oil, sunflower and corn, and no oil category in the category tree). The Arabic catalogue was not searched. Ghee is tracked instead. IDSC publishes daily prices of basic commodities including sunflower oil, which could serve as a reference outside the basket (to be decided by the team).
4. Names are not stable across page types (category card vs product page), so identity relies on `product_id` only.
5. Category names on the site are unreliable (for example, the "Balady Ghee" category contains cheese-labelled items and "Fresh Milk" contains cream), so our own category labels are used.
6. Descriptions are empty for 7 of the 15 products, and brand metadata is unreliable.
7. Weighed goods: the terms say weighed goods are charged by unit price and the delivered quantity may differ. We record only the listed shelf price.
8. Short verification window: prices were checked within a single day, so stability over time is unknown until daily collection runs.

## Sources Evaluated and Rejected

| Site | Result | Reason |
|---|---|---|
| Carrefour Egypt | Rejected | Its terms forbid using robots or spiders to navigate the site and restrict copying or storing content beyond personal non-commercial use (read from an archived 2021 copy, because the live terms page is script-rendered). Automated requests from our test machine also received no response (bot protection). |
| Spinneys Egypt | Rejected | Client-rendered app: category pages return no products in the HTML, and the terms page is unreadable without JavaScript. |
| Awlad Ragab | Rejected | Brochure site: offers are published as images, with no online shop prices. |
| Seoudi | Rejected | Corporate website only, no online shop. |
| Gourmet Egypt | Backup | Server-rendered Magento shop; terms (revised 2022-11-15) have no scraping clause. Its robots.txt is ambiguous: the `*` group is open, but a long disallow list (checkout, customer, catalog and others) follows another bot's group, so we would treat it as applying to us. Prices are premium, so it is less representative of basic goods. |

