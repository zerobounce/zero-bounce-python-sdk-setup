# Zero Bounce Python SDK

### INSTALLATION

```pip install zerobouncesdk```

### USAGE
* import the sdk in your file:

  ```python
  from zerobouncesdk import zerobouncesdk
  ``` 

* initialize the sdk with your api key:
    
  ```python 
  zerobouncesdk.initialize(<YOUR_API_KEY>)
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
### Examples
* get_credits:
    
    ```python
    from zerobouncesdk import zerobouncesdk, ZBException

    zerobouncesdk.initialize(<YOUR_API_KEY>)

    try:
        response = zerobouncesdk.get_credits()
        print("ZeroBounce my credits: "+response.credits)
    except ZBException as e:
        print("ZeroBounce error message: " + str(e))
    ```
