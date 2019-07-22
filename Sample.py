from datetime import date
from zerobouncesdk import zerobouncesdk, ZBApiException, \
    ZBMissingApiKeyException


def test_validate():
    try:
        response = zerobouncesdk.validate(email="<EMAIL_TO_TEST>")
        print("validate success response: " + str(response))
    except ZBApiException as e:
        print("validate error message: " + str(e))
    except ZBMissingApiKeyException as e:
        print("get_credits error message: " + str(e))


def test_get_credits():
    try:
        response = zerobouncesdk.get_credits()
        print("get_credits success response: " + str(response))
    except ZBApiException as e:
        print("get_credits error message: " + str(e))
    except ZBMissingApiKeyException as e:
        print("get_credits error message: " + str(e))


def test_send_file():
    try:
        response = zerobouncesdk.send_file(
            file_path='./email_file.csv',
            email_address_column=1,
            return_url=None,
            first_name_column=2,
            last_name_column=3,
            has_header_row=True)
        print("sendfile success response: " + str(response))
    except ZBApiException as e:
        print("sendfile error message: " + str(e))
    except ZBMissingApiKeyException as e:
        print("get_credits error message: " + str(e))


def test_file_status():

    try:
        response = zerobouncesdk.file_status("<YOUR_FILE_ID>")
        print("file_status success response: " + str(response))
    except ZBApiException as e:
        print("file_status error message: " + str(e))
    except ZBMissingApiKeyException as e:
        print("file_status error message: " + str(e))


def test_delete_file():
    try:
        response = zerobouncesdk.delete_file("<YOUR_FILE_ID>")
        print("delete_file success response: " + str(response))
    except ZBApiException as e:
        print("delete_file error message: " + str(e))
    except ZBMissingApiKeyException as e:
        print("delete_file error message: " + str(e))


def test_get_api_usage():
    try:
        start_date = date(2019, 7, 5)
        end_date = date(2019, 7, 15)
        response = zerobouncesdk.get_api_usage(start_date, end_date)
        print("get_api_usage success response: " + str(response))
    except ZBApiException as e:
        print("get_api_usage error message: " + str(e))
    except ZBMissingApiKeyException as e:
        print("get_api_usage error message: " + str(e))


def test_get_file():
    try:
        response = zerobouncesdk.get_file("<YOUR_FILE_ID>", "./downloads/emails.csv")
        print("get_file success response: " + str(response))
    except ZBApiException as e:
        print("get_file error message: " + str(e))
    except ZBMissingApiKeyException as e:
        print("get_file error message: " + str(e))


def test():
    zerobouncesdk.initialize("<YOUR_API_KEY>")

    # test_validate()

    # test_send_file()

    # test_get_credits()

    # test_file_status()

    # test_delete_file()

    # test_get_api_usage()

    test_get_file()


test()
