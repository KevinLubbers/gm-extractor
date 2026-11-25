import os
import sqlite3
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Load environment variables
load_dotenv()

BASE_URL = os.getenv("BASE_URL")
LOGIN_USER = os.getenv("LOGIN_USER")
LOGIN_PASS = os.getenv("LOGIN_PASS")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
DB_URL = os.getenv("DB_URL")

#start helper functions
def header_to_category(header):
    match header:
        case "OPTION PACKAGE":
            return "EQUIP"
        case "PRIMARY PAINT":
            return "EXT"
        case "SEAT TRIM":
            return "INT"
        case "PORT INSTALLED OPTIONS":
            return "IND"
        case _:
            return 

#automation will not crash if N/A or W/A is found in a location where a $ value is expected
def safe_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

# Connect to the database
conn = sqlite3.connect(DB_URL)
c = conn.cursor()

#create table if it doesn't exist
c.execute("""
        CREATE TABLE IF NOT EXISTS model_options(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_year INTEGER NOT NULL,
            division TEXT NOT NULL,
            model TEXT NOT NULL,
            model_code TEXT NOT NULL,
            option_code TEXT NOT NULL,
            option_name TEXT DEFAULT NULL,
            option_category TEXT DEFAULT NULL,
            invoice_price REAL NOT NULL,
            msrp_price REAL NOT NULL,
            scrape_date TEXT DEFAULT (datetime('now', 'localtime'))
        )""")

#SQL query used later to insert using executemany()
sql = """INSERT INTO model_options (model_year, division, model, model_code, option_code, option_name, option_category, invoice_price, msrp_price)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
#end helper functions

#main loop
def run():
    with sync_playwright() as p:
        #navigate and log in
        browser = p.chromium.launch(headless=HEADLESS, ignore_default_args=["--enable-automation"], channel="chrome")
        page = browser.new_page()
        page.goto(BASE_URL)
        page.fill("#username", LOGIN_USER)
        page.fill("#password", LOGIN_PASS)
        page.click("#login-button")

        #click on Build button and wait for popup
        page.locator(".framework-header-selector-button").first.click()
        page.wait_for_selector(".component-selector-model-input")

        #loop through hard-coded division list. no need to scrape all divisions
        division_list = ['Chevy Utility Vehicles']
        #division_list = ['Chevy Pickups']
        #division_list = ['Chevy Cars']
        model_list = ['Equinox', 'Traverse', 'Tahoe', 'Suburban', 'Trax']
        #model_list = ['Colorado', 'Silverado 1500', 'Silverado 2500HD', 'Silverado 3500HD']
        #model_list = ['Corvette']
        year_list = ['2027']
        data = []
        for each_year in year_list:
            page.select_option('.component-selector-year-input', label=each_year)
            time.sleep(3)
            divisions_of_year = page.locator('.component-selector-make-input option').all_text_contents()
            for each_division in division_list:
                if each_division not in divisions_of_year:
                    continue
                page.select_option('.component-selector-make-input', label=each_division)
                #get text of selected division
                division = page.eval_on_selector('select.component-selector-make-input','select => select.options[select.selectedIndex].textContent')
                #get text of selected year 
                year = page.eval_on_selector('select.component-selector-year-input','select => select.options[select.selectedIndex].textContent')
                time.sleep(1)
                page.wait_for_selector(".component-selector-model-input")
                #get text of all models (except the first one, which is a placeholder)
                models = page.eval_on_selector_all(".component-selector-model-input option", "options => options.slice(1).map(option=> option.textContent)")
                #loop through all models found
                #add models[:x] to only loop through to the xth model
                #for model in models:
                #use above line to loop through all models instead of a named list
                for model in model_list:
                    if model not in models:
                        continue
                    page.select_option('.component-selector-model-input', label=model)
                    time.sleep(2)
                    #get dynamically generated table data after selecting model
                    table = page.query_selector("table.style-cellTableWidget tbody")
                    rows = table.query_selector_all("tr")
                    #only select rows with national pricing for all Toyota models
                    if each_division == "Toyota":
                        for i in range(len(rows)):
                            cells = row.query_selector_all("td")
                            if any("(Natl)" in cell.inner_text() for cell in cells):
                                #extracts *MDL and DFRT pricing from each row
                                row_data = [cell.inner_text().strip() for cell in cells]
                                row_data = [x.replace("$", "").replace(",", "") for x in row_data]
                                #order of query is (year, division, model, model_code, option_code, option_name, invoice_price, msrp_price )
                                full_model_name = model + " " + row_data[1]
                                model_code = row_data[0]
                                option_name = None
                                insert_tuple = (year, division, full_model_name, model_code, "*MDL", option_name, float(row_data[2]), float(row_data[3]))
                                data.append(insert_tuple)
                                insert_tuple = (year, division, full_model_name, model_code, "DFRT", option_name, float(row_data[4]), float(row_data[4]))
                                data.append(insert_tuple)
                    #otherwise, select all rows
                    else:
                        #start Model loop
                        for i in range(len(rows)):
                            table = page.query_selector("table.style-cellTableWidget tbody")
                            rows = table.query_selector_all("tr")
                            row = rows[i]
                            #extracts *MDL and DFRT pricing from each row
                            cells = row.query_selector_all("td")
                            row_data = [cell.inner_text().strip() for cell in cells]
                            row_data = [x.replace("$", "").replace(",", "") for x in row_data]
                            #order of query is (year, division, model, model_code, option_code, option_name, option_category, invoice_price, msrp_price )
                            full_model_name = model + " " + row_data[1]
                            model_code = row_data[0]
                            option_name = None
                            #used to determine the value of each CPOS
                            model_invoice = safe_float(row_data[2])
                            model_msrp = safe_float(row_data[3])
                            model_dfrt = safe_float(row_data[4])
                            insert_tuple = (year, division, full_model_name, model_code, "*MDL", option_name, None, model_invoice, model_msrp)
                            data.append(insert_tuple)
                            insert_tuple = (year, division, full_model_name, model_code, "DFRT", option_name, None, model_dfrt, model_dfrt)
                            data.append(insert_tuple)
                            #end *MDL and DFRT
                            #used to detect and prevent duplicates from being added
                            seen_options = set()
                            #start enter model options
                            row.click()
                            time.sleep(3)
                            #need to add a check for the dynamic table popping up
                            #START NEW GM CPOS SELECTION LOGIC
                            def get_rows(row_name):
                                row = page.locator("tr").filter(has=page.locator(".peg-priceTitle", has_text=row_name))
                                return row.locator(".peg-priceValue").all_text_contents()
                            def get_CPOS_rows(row_name):
                                row = page.locator("tr").filter(has=page.locator(".peg-pegTitle", has_text=row_name))
                                return row.locator(".peg-pegValue").all_text_contents()

                            cpos_option_codes = get_CPOS_rows("Preferred Equipment Group")
                            cpos_option_names = get_CPOS_rows("Trim Level")
                            cpos_prices = get_rows("Base Model")
                            cpos_prices = [safe_float(x.replace("$", "").replace(",", "")) for x in cpos_prices]
                            select_buttons = page.locator(
                                "tr.peg-headerRow3 th.peg-pegButton div"
                            ).filter(has_text="Select")

                            count = select_buttons.count()

                            print(f"Found {count} Select buttons")

                            #start CPOS loop - One Model has Many CPOS
                            for j in range(count):
                                #adding CPOS option code with price before going to option list screen
                                adjusted_msrp = cpos_prices[j] - model_msrp
                                adjusted_invoice_rate = model_invoice / model_msrp
                                adjusted_invoice = adjusted_msrp * adjusted_invoice_rate
                                insert_tuple = (year, division, full_model_name, model_code, cpos_option_codes[j], cpos_option_names[j], "EQUIP", adjusted_invoice, adjusted_msrp)
                                data.append(insert_tuple)

                                #using a tuple of (option, invoice, msrp) to keep track of seen options
                                #here we are adding the CPOS option so it's not grabbed when going thru the main list
                                seen_options.add((cpos_option_codes[j], 0, 0))

                                button = select_buttons.nth(j)
                                print(adjusted_invoice)
                                print(adjusted_msrp)

                                print(f"Button #{j + 1}")
                                print("Text:", button.inner_text())

                                button.click()
                                time.sleep(3)
                                #add an enter key press maybe to account for random compatibility pop ups? shouldn't cause any issue if no pop up
                                #end dynamic menu selection, starting data extraction
                                option_table = page.query_selector_all("tr.subheader, tr.dataRow")
                                current_header = ""
                                try:
                                    page.locator("div.button-up >> text=OK").click(timeout=1000)
                                except:
                                    pass
                                for option in option_table:
                                    is_subheader = option.evaluate("el => el.classList.contains('subheader')")
                                    is_data = option.evaluate("el => el.classList.contains('dataRow')")
                                    #extract text from header and translate to a PCS category IF row is a header
                                    if is_subheader:
                                        current_header = header_to_category(option.inner_text().strip()) 
                                    elif is_data:
                                        cells = option.query_selector_all("td")
                                        row_data = [cell.inner_text().strip() for cell in cells]
                                        row_data = [x.replace("$", "").replace(",", "") for x in row_data]
                                        #order of query is (year, division, model, model_code, option_code, option_name, option_category, invoice_price, msrp_price )
                                        row_data[2] = row_data[2].split('\n')[0].rstrip()
                                        row_data[2] = (
                                            row_data[2][:-1].rstrip()
                                            if row_data[2].rstrip().count('(') < row_data[2].rstrip().count(')')
                                            else row_data[2].rstrip()
                                        )
                                        row_data[2] = row_data[2].replace('  ', ' ').replace('(PIO)', '(Port Installed)')
                                        #checking if this option has been added to this model already
                                        if (row_data[1], safe_float(row_data[4]), safe_float(row_data[5])) not in seen_options:
                                            #if new option, add it to seen_options and add the whole option to our data list
                                            seen_options.add((row_data[1], safe_float(row_data[4]), safe_float(row_data[5])))
                                            insert_tuple = (year, division, full_model_name, model_code, row_data[1], row_data[2], current_header, safe_float(row_data[4]), safe_float(row_data[5]))
                                            print(insert_tuple)
                                            data.append(insert_tuple)
                                #wait 25 seconds per model before moving to the next then reopen the dynamic menu and start the loop over again
                                time.sleep(25)
                                page.click(".framework-header-selector-button")
                                time.sleep(3)
                                #reselect last row if there are more CPOS to select
                                if j < count - 1:
                                    inner_table = page.query_selector("table.style-cellTableWidget tbody")
                                    inner_rows = inner_table.query_selector_all("tr")
                                    inner_row = inner_rows[i]
                                    inner_row.click()
                                    time.sleep(1)
                                #end CPOS loop
                            #END NEW GM LOGIC - sleep is for ui to close
                        #end Model loop
                    time.sleep(2)

        #insert data into database
        c.executemany(sql, data)

        conn.commit()
        c.close()
        conn.close()
        #close pop up
        page.click("img.gwt-Image[src*='close_window.gif']")
        #logout properly
        page.click("a.gwt-Anchor:has-text('Log Out')")

        time.sleep(5)
        browser.close()


if __name__ == "__main__":
    run()