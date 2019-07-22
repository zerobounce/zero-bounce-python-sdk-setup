import json
import ntpath
import urllib.parse
import urllib.request
from datetime import date
import os
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder

from zerobouncesdk import \
    ZBValidateResponse, ZBApiException, ZBMissingApiKeyException, \
    ZBSendFileResponse, ZBGetCreditsResponse, ZBFileStatusResponse, \
    ZBDeleteFileResponse, ZBGetApiUsageResponse, ZBGetFileResponse


__apiBaseUrl = "https://api.zerobounce.net/v2"
__bulkApiBaseUrl = "https://bulkapi.zerobounce.net/v2"
__api_key = None


def initialize(api_key):
    global __api_key
    __api_key = api_key


def validate(email: str, ip_address: str = None) -> ZBValidateResponse:
    """
    Parameters
    ----------
    email: str
        The email address you want to validate
    ip_address: str on None
        The IP Address the email signed up from (Can be blank)

    Raises
    ------
    ZBApiException
    ZBMissingApiKeyException

    Returns
    -------
    response: ZBValidateResponse
        Returns a ZBValidateResponse object if the request was successful
    """

    __check_api_key()

    return __request(
        __apiBaseUrl + "/validate?api_key=" + __api_key
        + "&email=" + email
        + "&ip_address=" + ("" if ip_address is None else ip_address),
        ZBValidateResponse)


def get_credits() -> ZBGetCreditsResponse:
    """This API will tell you how many credits you have left on your account. It's simple, fast and easy to use.

    Raises
    ------
    ZBApiException
    ZBMissingApiKeyException

    Returns
    -------
    response: ZBGetCreditsResponse
        Returns a ZBGetCreditsResponse object if the request was successful
    """

    __check_api_key()

    return __request(
        __apiBaseUrl + "/getcredits?api_key=" + __api_key,
        ZBGetCreditsResponse)


def send_file(
        file_path: str, email_address_column: int,
        return_url: str = None,
        first_name_column: int = None, last_name_column: int = None,
        gender_column: int = None, ip_address_column: int = None,
        has_header_row: bool = False) -> ZBSendFileResponse:
    """
    The sendfile API allows user to send a file for bulk email validation

    Raises
    ------
    ZBApiException
    ZBMissingApiKeyException

    Returns
    -------
    response: ZBSendFileResponse
        Returns a ZBSendFileResponse object if the request was successful
    """

    __check_api_key()

    fields = {
        # a file upload field
        'file': (ntpath.basename(file_path), open(file_path, 'rb')),
        # plain text fields
        'api_key': __api_key,
        'email_address_column': repr(email_address_column),
    }

    if return_url is not None:
        fields.update({'return_url': return_url})
    if first_name_column is not None:
        fields.update({'first_name_column': repr(first_name_column)})
    if last_name_column is not None:
        fields.update({'last_name_column': repr(last_name_column)})
    if gender_column is not None:
        fields.update({'gender_column': repr(gender_column)})
    if ip_address_column is not None:
        fields.update({'ip_address_column': repr(ip_address_column)})
    if has_header_row is not None:
        fields.update({'has_header_row': "true" if has_header_row else "false"})

    multipart_data = MultipartEncoder(fields=fields)

    response = requests.post(
        url=__bulkApiBaseUrl + "/sendfile",
        data=multipart_data,
        # files=files,
        headers={"Content-Type": multipart_data.content_type}
    )

    response_json = json.dumps(response.json())

    print("")
    print("response json: " + response_json)
    print("")

    response.raise_for_status()

    response_object = ZBSendFileResponse(response_json)
    return response_object


def file_status(file_id: str):
    """

    Parameters
    ----------
    file_id: str
        The returned file ID when calling sendFile API.

    Raises
    ------
    ZBApiException
    ZBMissingApiKeyException

    Returns
    -------
    response: ZBSendFileResponse
        Returns a ZBSendFileResponse object if the request was successful
    """

    __check_api_key()

    return __request(
        __bulkApiBaseUrl + "/filestatus?api_key=" + __api_key + "&file_id=" + file_id,
        ZBFileStatusResponse)


def delete_file(file_id: str) -> ZBDeleteFileResponse:
    """
    Parameters
    ----------
    file_id: str
        The returned file ID when calling sendFile API.

    Raises
    ------
    ZBApiException
    ZBMissingApiKeyException

    Returns
    -------
    response: ZBDeleteFileResponse
        Returns a ZBDeleteFileResponse object if the request was successful
    """
    __check_api_key()

    return __request(
        __bulkApiBaseUrl + "/deletefile?api_key=" + __api_key + "&file_id=" + file_id,
        ZBDeleteFileResponse)


def get_api_usage(start_date: date, end_date: date) -> ZBGetApiUsageResponse:
    """
    Parameters
    ----------
    start_date: date
        The start date of when you want to view API usage
    end_date: date
        The end date of when you want to view API usage

    Raises
    ------
    ZBApiException
    ZBMissingApiKeyException

    Returns
    -------
    response: ZBGetApiUsageResponse
        Returns a ZBGetApiUsageResponse object if the request was successful
    """
    __check_api_key()

    return __request(
        __apiBaseUrl + "/getapiusage?api_key=" + __api_key +
        "&start_date=" + start_date.strftime('%Y-%m-%d') +
        "&end_date=" + end_date.strftime('%Y-%m-%d'),
        ZBGetApiUsageResponse)


def get_file(file_id: str, local_download_path: str) -> ZBGetFileResponse:
    """
    The getfile API allows users to get the validation results file for the file been submitted using sendfile API

    Parameters
    ----------
    file_id: str
        The returned file ID when calling sendFile API.
    local_download_path: str
        The local path where the file will be downloaded.

    Returns
    -------
    response: ZBGetFileResponse
        Returns a ZBGetFileResponse object if the request was successful
    """
    __check_api_key()

    try:
        os.makedirs(ntpath.dirname(local_download_path), exist_ok=True)
        url = __bulkApiBaseUrl + "/getFile?api_key=" + __api_key + "&file_id=" + file_id
        print("request url=" + url)
        urllib.request.urlretrieve(url, local_download_path)

        response = ZBGetFileResponse()
        response.localFilePath = local_download_path
        return response
    except Exception as e:
        raise ZBApiException(str(e))


def __check_api_key():
    if __api_key is None:
        raise ZBMissingApiKeyException(
            "ZeroBounce SDK is not initialized. "
            "Please call zerobouncesdk.instance.initialize(apiKey) first")


def __request(url, response_class):
    try:
        print("request url=" + url)
        connection = urllib.request.urlopen(url)
        response = connection.read().decode('utf-8')
        print("response string: " + response)
        response_object = response_class(response)
        return response_object
    except TypeError as e:
        raise ZBApiException(str(e))
    except Exception as e:
        raise ZBApiException(str(e))


def __pretty_print_post(req):
    print('{}\n{}\n{}\n\n{}'.format(
        '-----------START-----------',
        req.method + ' ' + req.url,
        '\n'.join('{}: {}'.format(k, v) for k, v in req.headers.items()),
        str(req.body).replace("\\r\\n", "\n"),
    ))
