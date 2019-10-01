## Zero Bounce Python SDK
This SDK contains methods for interacting easily with ZeroBounce API.
More information about ZeroBounce you can find in the [official documentation](https://www.zerobounce.net/docs/).

## INSTALLATION
```bash
pip install zerobouncesdk
```

## USAGE
* import the sdk in your file:

  ```python
  from zerobouncesdk import zerobouncesdk
  ``` 

* initialize the sdk with your api key:
    
  ```python 
  zerobouncesdk.initialize("<YOUR_API_KEY>")
  ```
    
* then you can use any of the APIs:

  ```python
  zerobouncesdk.validate(email="<EMAIL_TO_TEST>")
  zerobouncesdk.get_credits()
  zerobouncesdk.send_file(
            file_path='./email_file.csv',
            email_address_column=1,
            return_url=None,
            first_name_column=2,
            last_name_column=3,
            has_header_row=True)
  zerobouncesdk.file_status("<YOUR_FILE_ID>")
  zerobouncesdk.delete_file("<YOUR_FILE_ID>")
  zerobouncesdk.get_api_usage(start_date, end_date)
  zerobouncesdk.get_file("<YOUR_FILE_ID>", "./downloads/email_file.csv")
  ```  

## Examples

* ##### Validate an email address
    ```python
    from zerobouncesdk import zerobouncesdk, ZBException
    
    zerobouncesdk.initialize("<YOUR_API_KEY>")
    
    try:
        response = zerobouncesdk.validate(
            email="<EMAIL_ADDRESS>",   // The email address you want to validate
            ip_address="127.0.0.1"     // The IP Address the email signed up from (Optional)
        )
    
        status = response.status       // one of [valid, invalid, catch-all, unknown, spamtrap, abuse, do_not_mail]
        print("ZeroBounce validate: "+status)
    except ZBException as e:
        print("ZeroBounce error message: " + str(e))
    ```

* ##### Check how many credits you have left on your account
    ```python
    from zerobouncesdk import zerobouncesdk, ZBException
    
    zerobouncesdk.initialize("<YOUR_API_KEY>")
    
    try:
        response = zerobouncesdk.get_credits()
        print("ZeroBounce get_credits: "+response.credits)
    except ZBException as e:
        print("ZeroBounce error message: " + str(e))
    ```

* ##### Check your API usage for a given period of time
    ```python
    import datetime
    from zerobouncesdk import zerobouncesdk, ZBException
    
    zerobouncesdk.initialize("<YOUR_API_KEY>")
    
    try:
        response = zerobouncesdk.get_api_usage(
            start_date=datetime.datetime(2019, 8, 1);    // The start date of when you want to view API usage
            end_date=datetime.datetime(2019, 9, 1);      // The start date of when you want to view API usage
        )
        print("ZeroBounce get_api_usage: "+response.total)
    except ZBException as e:
        print("ZeroBounce error message: " + str(e))
    ```

* ##### The sendfile API allows user to send a file for bulk email validation
    ```python
    from zerobouncesdk import zerobouncesdk, ZBException
    
    zerobouncesdk.initialize("<YOUR_API_KEY>")
    
    try:
        response = zerobouncesdk.send_file(
            file_path='./email_file.csv',   // The csv or txt file
            email_address_column=1,         // The index of "email" column in the file. Index starts at 1
            return_url=None,                // e.g "https://domain.com/called/after/processing/request"
            first_name_column=2,            // The index of "first name" column in the file
            last_name_column=3,             // The index of "last name" column in the file
            gender_column=4,                // The index of "gender" column in the file
            ip_address_column=5,            // The index of "IP address" column in the file
            has_header_row=True             // If this is `true` the first row is considered as table headers
        )
        print("ZeroBounce send_file: "+response.fileId)
    except ZBException as e:
        print("ZeroBounce error message: " + str(e))
    ```

* ##### The getfile API allows users to get the validation results file for the file been submitted using sendfile API
    ```python
    from zerobouncesdk import zerobouncesdk, ZBException
    
    zerobouncesdk.initialize("<YOUR_API_KEY>")
    
    try:
        response = zerobouncesdk.get_file(
            file_id="<FILE_ID>",                        // The returned file ID when calling sendfile API
            local_download_path="./dwnld_file.csv"      // The start date of when you want to view API usage
        )
        print("ZeroBounce get_file: "+response.localFilePath)
    except ZBException as e:
        print("ZeroBounce error message: " + str(e))
    ```

* ##### Check the status of a file uploaded via "sendFile" method
    ```python
    from zerobouncesdk import zerobouncesdk, ZBException
    
    zerobouncesdk.initialize("<YOUR_API_KEY>")
    
    try:
        response = zerobouncesdk.file_status(
            file_id="<FILE_ID>",           // The returned file ID when calling sendfile API
        )
        print("ZeroBounce file_status: "+response.file_status)
    except ZBException as e:
        print("ZeroBounce error message: " + str(e))
    ```

* ##### Deletes the file that was submitted using scoring sendfile API. File can be deleted only when its status is _`Complete`_
    ```python
    from zerobouncesdk import zerobouncesdk, ZBException
    
    zerobouncesdk.initialize("<YOUR_API_KEY>")
    
    try:
        response = zerobouncesdk.delete_file(
            file_id="<FILE_ID>",           // The returned file ID when calling sendfile API
        )
        print("ZeroBounce delete_file: "+response.fileId)
    except ZBException as e:
        print("ZeroBounce error message: " + str(e))
    ```
