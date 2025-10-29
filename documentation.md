#### INSTALLATION
```bash
pip install zerobouncesdk
```

#### USAGE
Import the sdk in your file:

```python
from zerobouncesdk import ZeroBounce
```

Initialize the sdk with your api key:

```python
zero_bounce = ZeroBounce("<YOUR_API_KEY>")
```

#### Examples
Then you can use any of the SDK methods, for example:

* ####### Check how many credits you have left on your account
```python
from zerobouncesdk import ZeroBounce

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

response = zero_bounce.get_credits()
print("ZeroBounce get_credits response: " + str(response))
```

* ####### Check your API usage for a given period of time
```python
from datetime import datetime
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

start_date = datetime(2019, 8, 1);  # The start date of when you want to view API usage
end_date = datetime(2019, 9, 1);    # The end date of when you want to view API usage

try:
    response = zero_bounce.get_api_usage(start_date, end_date)
    print("ZeroBounce get_api_usage response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_api_usage error: " + str(e))
```

* ####### Gather insights into your subscribers' overall email engagement
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

email = "valid@example.com";    # Subscriber email address

try:
    response = zero_bounce.get_activity(email)
    print("ZeroBounce get_activity response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_activity error: " + str(e))
```

* ####### Find the correct email format when you provide a name and email domain or company name

```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

# Option 1: Use find_email_format with domain
domain = "example.com"  # The email domain for which to find the email format
first_name = "John"      # The first name of the person whose email format is being searched
middle_name = "Quill"    # Optional: The middle name of the person
last_name = "Doe"        # Optional: The last name of the person

try:
    response = zero_bounce.find_email_format(
        first_name=first_name,
        domain=domain,
        middle_name=middle_name,
        last_name=last_name
    )
    print("Email: " + str(response.email))
    print("Email Confidence: " + str(response.email_confidence))
except ZBException as e:
    print("ZeroBounce find_email_format error: " + str(e))
```

```python
# Option 2: Use find_email_format with company_name
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

company_name = "Acme Corp"  # The company name for which to find the email format
first_name = "Jane"          # The first name of the person

try:
    response = zero_bounce.find_email_format(
        first_name=first_name,
        company_name=company_name
    )
    print("Email: " + str(response.email))
    print("Domain: " + str(response.domain))
    print("Company: " + str(response.company_name))
except ZBException as e:
    print("ZeroBounce find_email_format error: " + str(e))
```

```python
# Option 3: Use find_domain to discover email formats for a domain
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

domain = "example.com"  # The email domain to analyze

try:
    response = zero_bounce.find_domain(domain=domain)
    print("Domain: " + str(response.domain))
    print("Format: " + str(response.format))
    print("Confidence: " + str(response.confidence))
    print("Other formats: " + str(len(response.other_domain_formats)))
except ZBException as e:
    print("ZeroBounce find_domain error: " + str(e))
```

```python
# Option 4: Use find_domain with company_name
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

company_name = "Acme Corp"  # The company name to analyze

try:
    response = zero_bounce.find_domain(company_name=company_name)
    print("Domain: " + str(response.domain))
    print("Company: " + str(response.company_name))
    print("Format: " + str(response.format))
    print("Confidence: " + str(response.confidence))
    for fmt in response.other_domain_formats:
        print(f"  Alternative: {fmt.format} (confidence: {fmt.confidence})")
except ZBException as e:
    print("ZeroBounce find_domain error: " + str(e))
```

* ####### Validate an email address
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

email = "<EMAIL_ADDRESS>"   # The email address you want to validate
ip_address = "127.0.0.1"    # The IP Address the email signed up from (Optional)

try:
    response = zero_bounce.validate(email, ip_address)
    print("ZeroBounce validate response: " + str(response))
except ZBException as e:
    print("ZeroBounce validate error: " + str(e))
```

* ####### Validate a batch of up to 100 emails at a time
```python
from zerobouncesdk import ZeroBounce, ZBException, ZBValidateBatchElement

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

email_batch = [
    ZBValidateBatchElement("valid@example.com", "127.0.0.1"),
    ZBValidateBatchElement("invalid@example.com"),
]                   # The batch of emails you want to validate

try:
    response = zero_bounce.validate_batch(email_batch)
    print("ZeroBounce validate_batch response: " + str(response))
except ZBException as e:
    print("ZeroBounce validate_batch error: " + str(e))
```

* ####### The _sendFile_ API allows user to send a file for bulk email validation
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_path = './email_file.csv'  # The csv or txt file
email_address_column = 1        # The index of "email" column in the file. Index starts at 1
return_url = "https://domain.com/called/after/processing/request"
first_name_column = None        # The index of "first name" column in the file
last_name_column = None         # The index of "last name" column in the file
gender_column = None            # The index of "gender" column in the file
ip_address_column = None        # The index of "IP address" column in the file
has_header_row = False          # If the first row from the submitted file is a header row
remove_duplicate = True         # If you want the system to remove duplicate emails

try:
    response = zero_bounce.send_file(
        file_path,
        email_address_column,
        return_url,
        first_name_column,
        last_name_column,
        gender_column,
        ip_address_column,
        has_header_row,
        remove_duplicate,
    )
    print("ZeroBounce send_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce send_file error: " + str(e))
```

* ####### Check the status of a file uploaded via _sendFile_ method
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id = "<FILE_ID>"       # The returned file ID when calling sendFile API

try:
    response = zero_bounce.file_status(file_id)
    print("ZeroBounce file_status response: " + str(response))
except ZBException as e:
    print("ZeroBounce file_status error: " + str(e))
```

* ####### The _getfile_ API allows users to get the validation results file for the file been submitted using _sendFile_ API
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id="<FILE_ID>"                         # The returned file ID when calling sendFile API
local_download_path = "./dwnld_file.csv"    # The path where the file will be downloaded

try:
    response = zero_bounce.get_file(file_id, local_download_path)
    print("ZeroBounce get_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_file error: " + str(e))
```

* ####### Delete the file that was submitted using _sendFile_ API. File can be deleted only when its status is `Complete`
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id="<FILE_ID>"     # The returned file ID when calling sendFile API

try:
    response = zero_bounce.delete_file(file_id)
    print("ZeroBounce delete_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce delete_file error: " + str(e))
```

##### AI Scoring API

* ####### The _scoringSendFile_ API allows user to send a file for bulk email scoring
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_path = './email_file.csv'  # The csv or txt file
email_address_column = 1        # The index of "email" column in the file. Index starts at 1
return_url = "https://domain.com/called/after/processing/request"
has_header_row = False          # If the first row from the submitted file is a header row
remove_duplicate = True         # If you want the system to remove duplicate emails

try:
    response = zero_bounce.scoring_send_file(
        file_path,
        email_address_column,
        return_url,
        has_header_row,
        remove_duplicate,
    )
    print("ZeroBounce send_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce send_file error: " + str(e))
```

* ####### Check the status of a file uploaded via _scoringSendFile_ method
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id = "<FILE_ID>"       # The returned file ID when calling scoringSendFile API

try:
    response = zero_bounce.scoring_file_status(file_id)
    print("ZeroBounce file_status response: " + str(response))
except ZBException as e:
    print("ZeroBounce file_status error: " + str(e))
```

* ####### The scoring _scoringGetFile_ API allows users to get the validation results file for the file been submitted using scoring _scoringSendFile_ API
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id="<FILE_ID>"                         # The returned file ID when calling scoringSendFile API
local_download_path = "./dwnld_file.csv"    # The path where the file will be downloaded

try:
    response = zero_bounce.scoring_get_file(file_id, local_download_path)
    print("ZeroBounce get_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_file error: " + str(e))
```

* ####### Delete the file that was submitted using _scoringSendFile_ API. File can be deleted only when its status is `Complete`
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

file_id="<FILE_ID>"     # The returned file ID when calling scoringSendFile API

try:
    response = zero_bounce.scoring_delete_file(file_id)
    print("ZeroBounce delete_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce delete_file error: " + str(e))
```
