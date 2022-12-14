from time import sleep
import tkinter as tk
from tkinter import simpledialog
from datetime import datetime

from app.services import (
    google_sheets_client,
    google_client,
    IndeedClient,
    cuntry_name_to_country_code,
    generator_search_url,
    checking_internet_connection,
)
from app.logger import log
from config import config as conf

TK_ROOT = None
if not conf.TESTING:
    TK_ROOT = tk.Tk()
    TK_ROOT.withdraw()


def generate_clients():

    full_name_msg = "Enter Full name of client"
    batch = None
    while True:
        if not batch:
            if not conf.TESTING:
                batch = simpledialog.askstring(
                    title="Name of client",
                    prompt=full_name_msg,
                )
        checking_internet_connection()
        client_data = google_sheets_client.get_clients_list(full_name=batch)
        if len(client_data) > 1:
            log(
                log.INFO,
                f"The bot found several clients with this Full Name: {batch} .Bot will processing just first client. \n"
                "---------------------------------------------------------",
            )
        if client_data:
            client_data = client_data[0]
            break
        batch = ""
        full_name_msg = "Clients not found. Please use another client full name"

    log(
        log.INFO,
        f"Process Client: {client_data['Full Name']}",
    )
    log(log.INFO, f"Client data: {client_data}")

    REQUIRED_FIELDS = ["Full Name", "Email", "Password"]
    has_required_fields = True
    for field in REQUIRED_FIELDS:
        if not client_data.get(field):
            log(log.ERROR, f"Client has not data in '{field}' cell. Skip client")
            checking_internet_connection()
            google_client.send_email(
                conf.SEND_MAIL_TO,
                f"Error reading client data in indeed pending scripts. Time: {datetime.now()}, SEVERITY: MEDIUM",
                f"Client has not data in '{field}' cell. Skip client. \n"
                f"Check the spreadsheet of clients. One of the clients does not have a filled field: {field} \n"
                "The bot stop working ",
            )
            has_required_fields = False
            break
    if not has_required_fields:
        return
    spread_sheet_id = google_sheets_client.find_client_sheet(client_data["Full Name"])
    if not spread_sheet_id:
        log(
            log.ERROR,
            f"Client {client_data['Full Name']} spreadsheet file not found. Skip client",
        )
        checking_internet_connection()
        google_client.send_email(
            conf.SEND_MAIL_TO,
            f"Error in client data in indeed pending scripts.  Time: {datetime.now()}, SEVERITY: HIGH",
            f"Client {client_data['Full Name']}. Spreadsheet file not found. Skip client \n"
            f"The bot did not find spreadsheet file of {client_data['Full Name']}. \n"
            f"Please check whether the spreadsheet file exists and whether the client({client_data['Full Name']}) has this table \n"
            "The bot stop working",
        )
        return

    client = IndeedClient(
        email=client_data["Email"],
        password=client_data["Password"],
        user_name=client_data["Full Name"],
        country=client_data["Country"],
        sheet_row_index=client_data["row_index"],
    )
    if client.browser.browser is None:
        google_client.send_email(
            conf.SEND_MAIL_TO,
            f"Error getting from indeed pending scripts. Error with chromedriver.  Time: {datetime.now()}, SEVERITY: HIGH",
            f"Your chromedriver is old please replace chromedriver to new one in folder drivers \n"
            f"The bot stop working",
        )
        return

    return client


def run_script():
    client = generate_clients()
    if not client:
        log(
            log.CRITICAL,
            "Client data is bad or chromedriver is old. The bot cannot process client. The bot will stop",
        )
        return

    client.browser.create_screenshot()
    if not client.clients_inputs:
        log(log.ERROR, "Client inputs are empty, skip user")
        return
    if not client.spreadsheet_url:
        log(log.ERROR, f"User {client.email} has not own spreadsheet")
        return

    for client_inputs in client.clients_inputs:
        count_jobs = 0
        try:
            log(log.INFO, f"Process client inputs: {client_inputs}")

            client_inputs = {
                key.lower().replace(" ", "_"): client_inputs[key]
                for key in client_inputs
            }

            if not client_inputs["active"].lower() in ["true", "t"]:
                log(
                    log.ERROR,
                    "Client inputs in not Active. Skip inputs",
                )
                continue

            count_total_result = int(client_inputs.get("total_results", "5000"))
            country_code = ""
            if client.country != "United States":
                country_code = cuntry_name_to_country_code(client.country)
                if not country_code:
                    log(
                        log.ERROR,
                        f"Contry code for country {client.country} not found. Skip clien_inputs",
                    )
                    continue

            try:
                url = generator_search_url(country_code, client_inputs)
            except (AttributeError, KeyError, TypeError):
                log(
                    log.ERROR,
                    f"Client input is not correct."
                    f"Please follow the rules in trello,"
                    f"or check enter value in the client input. Bot skip the client input.",
                )
                continue

            log(log.INFO, f"Load Jobs [{url}]")

            jobs = client.browser.find_jobs(url, client_inputs, 0)

            if not jobs or not jobs.get("job_keys"):
                log(log.INFO, f"Jobs are not loaded. Skip client inputs")
                continue

            jobs_count = len(jobs.get("job_keys"))
            log(log.INFO, f"Loaded {jobs_count} jobs")

            while any(list(jobs.values())):
                log(log.INFO, f"Start process loaded jobs")

                # process loaded jobs
                if jobs.get("job_keys"):
                    for job_data in jobs.get("job_keys"):

                        try:
                            client.browser.process_job(
                                client_inputs=client_inputs,
                                job_data=job_data,
                                country_code=country_code,
                            )
                            count_jobs += 1
                            if count_jobs == count_total_result:
                                log(
                                    log.INFO,
                                    "-----Count jobs reached the client inputs display's, Skip client inputs-----",
                                )
                                break
                        except Exception as e:
                            log(
                                log.ERROR,
                                f"Process job sample {job_data.get('job_id')} error",
                            )
                            log(log.ERROR, e)
                            log(log.ERROR, "-------------------------")
                            checking_internet_connection()
                            google_client.send_email(
                                conf.SEND_MAIL_TO,
                                f"Process sample Job Error in pending scripts.  Time: {datetime.now()}, SEVERITY: LOW",
                                f"An unknown error occurred while getting data for job_id: {job_data.get('job_id')} for client: {client.user_name}. \n"
                                "Please check the log file. The bot continues working by getting data from another job",
                            )

                    log(log.INFO, "Save sample list of jobs")
                    google_sheets_client.save_sample_list_jobs(
                        spreadsheet_id=client.spreadsheet_url,
                        country=client.country,
                        add_to_main_spreadsheet=True,
                        client_name=client.user_name,
                    )

                log(log.INFO, f"Process loaded jobs ended")
                # load next page
                if jobs.get("next_page_url") and count_jobs != count_total_result:
                    log(log.INFO, f"Load Jobs(next page)")
                    jobs = client.browser.find_jobs(
                        jobs.get("next_page_url"),
                        client_inputs,
                        jobs.get("pagination"),
                    )
                    jobs_count = len(jobs.get("job_keys"))
                    log(log.INFO, f"Loaded {jobs_count} jobs")
                else:
                    # google_sheets_client.count_added_jobs = 0
                    break
        finally:
            checking_internet_connection()
    return True


def main():
    log(log.INFO, f"------- Start {datetime.now()} -------")
    if not conf.TESTING:
        try:
            while True:
                run_script_data = run_script()
                if run_script_data:
                    log(
                        log.INFO,
                        f"Process client was successful now you can see all sample jobs",
                    )
                    break
                elif run_script_data is None:
                    log(
                        log.INFO,
                        f"Process client was not successful, check the logs above",
                    )
                    break
        except Exception as e:
            google_client.send_email(
                conf.SEND_MAIL_TO,
                f"Run script error in pending scripts.  Time: {datetime.now()}, SEVERITY: HIGH",
                "The problem occurred while launching the Bot. \n"
                "Please check the log file \n"
                "The bot tries to restart in automatic mode",
            )
            log(
                log.EXCEPTION,
                f"Run script error {str(e.args[0]) if e.args else str(e)}",
            )
    else:
        while True:
            if run_script():
                break
            log(log.INFO, f"Loop Ended. Pause {conf.LOOP_PAUSE_MIN} sec")
            sleep(conf.LOOP_PAUSE_MIN)
    log(log.INFO, f"------- End Work {datetime.now()} -------")


main()
