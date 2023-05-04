from datetime import date
import os
from typing import List

import requests

from . import (
    ZBApiException,
    ZBClientException,
    ZBGetCreditsResponse,
    ZBGetApiUsageResponse,
    ZBGetActivityResponse,
    ZBValidateResponse,
    ZBValidateBatchElement,
    ZBValidateBatchResponse, 
    ZBSendFileResponse,
    ZBFileStatusResponse,
    ZBGetFileResponse,
    ZBDeleteFileResponse,
)


class ZeroBounce:
    """The ZeroBounce main class. All the requests are implemented here."""

    BASE_URL = "https://api.zerobounce.in/v2"
    BULK_BASE_URL = "https://bulkapi.zerobounce.in/v2"
    SCORING_BASE_URL = "https://bulkapi.zerobounce.in/v2/scoring"

    def __init__(self, api_key: str):
        if not api_key.strip():
            raise ZBClientException("Empty parameter: api_key")
        self._api_key = api_key

    def _request(self, url, response_class, params=None):
        if not params:
            params = {}
        params["api_key"] = self._api_key
        response = requests.get(url, params=params)

        try:
            json_response = response.json()
        except ValueError as e:
            raise ZBApiException from e

        error = json_response.pop("error", None)
        if error:
            raise ZBApiException(error)
        return response_class(json_response)

    def get_credits(self):
        """Tells you how many credits you have left on your account.
        It's simple, fast and easy to use.

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBGetCreditsResponse
            Returns a ZBGetCreditsResponse object if the request was successful
        """

        return self._request(
            f"{self.BASE_URL}/getcredits",
            ZBGetCreditsResponse
        )

    def get_api_usage(self, start_date: date, end_date: date):
        """Returns the API usage between the given dates.

        Parameters
        ----------
        start_date: date
            The start date of when you want to view API usage
        end_date: date
            The end date of when you want to view API usage

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBGetApiUsageResponse
            Returns a ZBGetApiUsageResponse object if the request was successful
        """

        return self._request(
            f"{self.BASE_URL}/getapiusage",
            ZBGetApiUsageResponse,
            params={
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
            }
        )

    def get_activity(self, email: str):
        """Allows you to gather insights into your subscribers' overall email engagement

        Parameters
        ----------
        email: str
            The email whose activity you want to check

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBGetActivityResponse
            Returns a ZBGetActivityResponse object if the request was successful
        """

        return self._request(
            f"{self.BASE_URL}/activity",
            ZBGetActivityResponse,
            params={"email": email}
        )

    def validate(self, email: str, ip_address: str = None):
        """Validates the given email address.

        Parameters
        ----------
        email: str
            The email address you want to validate
        ip_address: str or None
            The IP Address the email signed up from (Can be blank)

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBValidateResponse
            Returns a ZBValidateResponse object if the request was successful
        """

        return self._request(
            f"{self.BASE_URL}/validate",
            ZBValidateResponse,
            params={
                "email": email,
                "ip_address": ip_address,
            }
        )

    def validate_batch(self, email_batch: List[ZBValidateBatchElement]):
        """Allows you to send us batches up to 100 emails at a time.

        Parameters
        ----------
        email_batch: List[ZBValidateBatchElement]
            Array of ZBValidateBatchElement

        Raises
        ------
        ZBApiException
        ZBClientException

        Returns
        -------
        response: ZBValidateBatchResponse
            Returns a ZBValidateBatchResponse object if the request was successful
        """
        if not email_batch:
            raise ZBClientException("Empty parameter: email_batch")

        response = requests.post(
            f"{self.BULK_BASE_URL}/validatebatch",
            json={
                "api_key": self._api_key,
                "email_batch": [
                    batch_element.to_json() for batch_element in email_batch
                ],
            }
        )
        json_response = response.json()
        try:
            return ZBValidateBatchResponse(json_response)
        except KeyError:
            error = list(json_response.values())[0]
            raise ZBApiException(error)

    def _send_file(
        self,
        scoring: bool,
        file_path: str,
        email_address_column: int,
        data: dict,
    ):
        data.update({
            "api_key": self._api_key,
            "email_address_column": email_address_column,
        })

        with open(file_path, "rb") as file:
            response = requests.post(
                f"{self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL}/sendfile",
                data=data,
                files={
                    "file": (os.path.basename(file_path), file, "text/csv")
                },
            )
        try:
            json_response = response.json()
        except ValueError as e:
            raise ZBApiException from e
        
        return ZBSendFileResponse(json_response)

    def send_file(
        self,
        file_path: str, 
        email_address_column: int,
        return_url: str = None,
        first_name_column: int = None,
        last_name_column: int = None,
        gender_column: int = None,
        ip_address_column: int = None,
        has_header_row: bool = False,
        remove_duplicate: bool = True,
    ):
        """Allows user to send a file for bulk email validation

        Parameters
        ----------
        file_path: str
            The path of the csv or txt file to be submitted.
        email_address_column: int
            The column index of the email address in the file. Index starts from 1.
        return_url: str or None
            The URL will be used to call back when the validation is completed.
        first_name_column: int or None
            The column index of the first name column.
        last_name_column: int or None
            The column index of the last name column.
        gender_column: int or None
            The column index of the gender column.
        ip_address_column: int or None
            The IP Address the email signed up from.
        has_header_row: bool
            If the first row from the submitted file is a header row.
        remove_duplicate: bool
            If you want the system to remove duplicate emails.

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBSendFileResponse
            Returns a ZBSendFileResponse object if the request was successful
        """

        data = {}
        if return_url is not None:
            data["return_url"] = return_url
        if first_name_column is not None:
            data["first_name_column"] = first_name_column
        if last_name_column is not None:
            data["last_name_column"] = last_name_column
        if gender_column is not None:
            data["gender_column"] = gender_column
        if ip_address_column is not None:
            data["ip_address_column"] = ip_address_column
        if has_header_row is not None:
            data["has_header_row"] = has_header_row
        if remove_duplicate is not None:
            data["remove_duplicate"] = remove_duplicate

        return self._send_file(False, file_path, email_address_column, data)

    def scoring_send_file(
        self,
        file_path: str, 
        email_address_column: int,
        return_url: str = None,
        has_header_row: bool = False,
        remove_duplicate: bool = True,
    ):
        """Allows user to send a file for bulk email scoring

        Parameters
        ----------
        file_path: str
            The path of the csv or txt file to be submitted.
        email_address_column: int
            The column index of the email address in the file. Index starts from 1.
        return_url: str or None
            The URL will be used to call back when the validation is completed.
        has_header_row: bool
            If the first row from the submitted file is a header row.
        remove_duplicate: bool
            If you want the system to remove duplicate emails.

        Raises
        ------
        ZBApiException

        Returns
        -------
        response: ZBSendFileResponse
            Returns a ZBSendFileResponse object if the request was successful
        """

        data = {}
        if return_url is not None:
            data["return_url"] = return_url
        if has_header_row is not None:
            data["has_header_row"] = has_header_row
        if remove_duplicate is not None:
            data["remove_duplicate"] = remove_duplicate

        return self._send_file(True, file_path, email_address_column, data)

    def _file_status(self, scoring: bool, file_id: str):
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._request(
            f"{self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL}/filestatus",
            ZBFileStatusResponse,
            params={"file_id": file_id}
        )

    def file_status(self, file_id: str):
        """Returns the file processing status for the file that has been submitted

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.

        Raises
        ------
        ZBClientException

        Returns
        -------
        response: ZBSendFileResponse
            Returns a ZBSendFileResponse object if the request was successful
        """

        return self._file_status(False, file_id)

    def scoring_file_status(self, file_id: str):
        """Returns the file processing status for the file that has been submitted

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.

        Raises
        ------
        ZBClientException

        Returns
        -------
        response: ZBSendFileResponse
            Returns a ZBSendFileResponse object if the request was successful
        """

        return self._file_status(True, file_id)

    def _get_file(self, scoring: bool, file_id: str, download_path: str):
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        response = requests.get(
            f"{self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL}/getfile",
            params={
                "api_key": self._api_key,
                "file_id": file_id,
            }
        )
        if response.headers['Content-Type'] == "application/json":
            json_response = response.json()
            return ZBGetFileResponse(json_response)

        dirname = os.path.dirname(download_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(download_path, "wb") as f:
            f.write(response.content)

        return ZBGetFileResponse({"local_file_path": download_path})

    def get_file(self, file_id: str, download_path: str):
        """Allows you to get the validation results for the file you submitted

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.
        download_path: str
            The local path where the file will be downloaded.

        Raises
        ------
        ZBClientException

        Returns
        -------
        response: ZBGetFileResponse
            Returns a ZBGetFileResponse object if the request was successful
        """

        return self._get_file(False, file_id, download_path)

    def scoring_get_file(self, file_id: str, download_path: str):
        """Allows you to get the validation results for the file you submitted

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.
        download_path: str
            The local path where the file will be downloaded.

        Raises
        ------
        ZBClientException

        Returns
        -------
        response: ZBGetFileResponse
            Returns a ZBGetFileResponse object if the request was successful
        """

        return self._get_file(True, file_id, download_path)

    def _delete_file(self, scoring: bool, file_id: str):
        if not file_id.strip():
            raise ZBClientException("Empty parameter: file_id")
        return self._request(
            f"{self.SCORING_BASE_URL if scoring else self.BULK_BASE_URL}/deletefile",
            ZBDeleteFileResponse,
            params={"file_id": file_id}
        )

    def delete_file(self, file_id: str):
        """Deletes the file that you submitted
        Please note that the file can be deleted only when its status is Complete

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.

        Raises
        ------
        ZBApiException
        ZBClientException

        Returns
        -------
        response: ZBDeleteFileResponse
            Returns a ZBDeleteFileResponse object if the request was successful
        """

        return self._delete_file(False, file_id)

    def scoring_delete_file(self, file_id: str):
        """Deletes the file that you submitted
        Please note that the file can be deleted only when its status is Complete

        Parameters
        ----------
        file_id: str
            The returned file ID when calling sendfile API.

        Raises
        ------
        ZBApiException
        ZBClientException

        Returns
        -------
        response: ZBDeleteFileResponse
            Returns a ZBDeleteFileResponse object if the request was successful
        """

        return self._delete_file(True, file_id)
