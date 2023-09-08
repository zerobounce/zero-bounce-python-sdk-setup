#### INSTALACIÓN
```bash
pip install zerobouncesdk
```

#### USO
Importa el SDK en tu archivo:

```python
from zerobouncesdk import ZeroBounce
```

Inicializa el SDK con tu clave de API:

```python
zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")
```

#### Ejemplos
Luego puedes utilizar cualquiera de los métodos del SDK, por ejemplo:

* ####### Verificar cuántos créditos te quedan en tu cuenta
```python
from zerobouncesdk import ZeroBounce

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

response = zero_bounce.get_credits()
print("ZeroBounce get_credits response: " + str(response))
```

* ####### Verificar el uso de tu API durante un período de tiempo específico
```python
from datetime import datetime
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

fecha_inicio = datetime(2019, 8, 1)  ### Fecha de inicio para ver el uso de la API
fecha_fin = datetime(2019, 9, 1)    ### Fecha de fin para ver el uso de la API

try:
    response = zero_bounce.get_api_usage(fecha_inicio, fecha_fin)
    print("ZeroBounce get_api_usage response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_api_usage error: " + str(e))
```

* ####### Obtener información sobre la participación general por correo electrónico de tus suscriptores
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

email = "valid@example.com"  ### Dirección de correo electrónico del suscriptor

try:
    response = zero_bounce.get_activity(email)
    print("ZeroBounce get_activity response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_activity error: " + str(e))
```


* ####### Identify the correct email format when you provide a name and email domain

```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<YOUR_API_KEY>")

domain = "example.com" # The email domain for which to find the email format
first_name = "John" # The first name of the person whose email format is being searched
middle_name = "Quill" # The middle name of the person whose email format is being searched
last_name = "Doe" # The last name of the person whose email format is being searched

try:
    response = zero_bounce.find_email(domain, first_name, middle_name, last_name)
    print("ZeroBounce guess format response: " + response)
except ZBException as e:
    print("ZeroBounce guess format error: " + str(e))
```

* ####### Validar una dirección de correo electrónico
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

email = "<DIRECCIÓN_DE_CORREO_ELECTRÓNICO>"   ### La dirección de correo electrónico que deseas validar
ip_address = "127.0.0.1"    ### La dirección IP desde la que se registró el correo electrónico (opcional)

try:
    response = zero_bounce.validate(email, ip_address)
    print("ZeroBounce validate response: " + str(response))
except ZBException as e:
    print("ZeroBounce validate error: " + str(e))
```

* ####### Validar un lote de hasta 100 correos electrónicos a la vez
```python
from zerobouncesdk import ZeroBounce, ZBException, ZBValidateBatchElement

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

lote_correos = [
    ZBValidateBatchElement("valid@example.com", "127.0.0.1"),
    ZBValidateBatchElement("invalid@example.com"),
]  ### El lote de correos electrónicos que deseas validar

try

:
    response = zero_bounce.validate_batch(lote_correos)
    print("ZeroBounce validate_batch response: " + str(response))
except ZBException as e:
    print("ZeroBounce validate_batch error: " + str(e))
```

* ####### El API _sendFile_ permite enviar un archivo para validar correos electrónicos en masa
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

ruta_archivo = './archivo_correos.csv'  ### Ruta del archivo CSV o TXT
columna_direccion_correo = 1  ### Índice de la columna "email" en el archivo (el índice comienza en 1)
url_retorno = "https://dominio.com/llamada/despues/procesar/solicitud"
columna_nombre = None  ### Índice de la columna "nombre" en el archivo
columna_apellido = None  ### Índice de la columna "apellido" en el archivo
columna_genero = None  ### Índice de la columna "género" en el archivo
columna_direccion_ip = None  ### Índice de la columna "dirección IP" en el archivo
tiene_encabezado = False  ### Si la primera fila del archivo es una fila de encabezado
eliminar_duplicados = True  ### Si deseas que el sistema elimine correos electrónicos duplicados

try:
    response = zero_bounce.send_file(
        ruta_archivo,
        columna_direccion_correo,
        url_retorno,
        columna_nombre,
        columna_apellido,
        columna_genero,
        columna_direccion_ip,
        tiene_encabezado,
        eliminar_duplicados,
    )
    print("ZeroBounce send_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce send_file error: " + str(e))
```

* ####### Verificar el estado de un archivo enviado mediante el método _sendFile_
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

id_archivo = "<ID_DE_ARCHIVO>"  ### ID de archivo devuelto al llamar al método sendFile

try:
    response = zero_bounce.file_status(id_archivo)
    print("ZeroBounce file_status response: " + str(response))
except ZBException as e:
    print("ZeroBounce file_status error: " + str(e))
```

* ####### El API _getfile_ permite a los usuarios obtener el archivo con los resultados de validación del archivo enviado mediante el método _sendFile_
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

id_archivo = "<ID_DE_ARCHIVO>"  ### ID de archivo devuelto al llamar al método sendFile
ruta_descarga_local = "./archivo_descargado.csv"  ### Ruta donde se descargará el archivo

try:
    response = zero_bounce.get_file(id_archivo, ruta_descarga_local)
    print("ZeroBounce get_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_file error: " + str(e))
```

* ####### Eliminar el archivo que se envió mediante el método _sendFile_. El archivo solo se puede eliminar si su estado es `Completado`
```python
from zerobouncesdk import ZeroBounce,

 ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

id_archivo = "<ID_DE_ARCHIVO>"  ### ID de archivo devuelto al llamar al método sendFile

try:
    response = zero_bounce.delete_file(id_archivo)
    print("ZeroBounce delete_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce delete_file error: " + str(e))
```

##### API de puntuación de IA

* ####### El API _scoringSendFile_ permite enviar un archivo para puntuación de correos electrónicos en masa
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

ruta_archivo = './archivo_correos.csv'  ### Ruta del archivo CSV o TXT
columna_direccion_correo = 1  ### Índice de la columna "email" en el archivo (el índice comienza en 1)
url_retorno = "https://dominio.com/llamada/despues/procesar/solicitud"
tiene_encabezado = False  ### Si la primera fila del archivo es una fila de encabezado
eliminar_duplicados = True  ### Si deseas que el sistema elimine correos electrónicos duplicados

try:
    response = zero_bounce.scoring_send_file(
        ruta_archivo,
        columna_direccion_correo,
        url_retorno,
        tiene_encabezado,
        eliminar_duplicados,
    )
    print("ZeroBounce send_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce send_file error: " + str(e))
```

* ####### Verificar el estado de un archivo enviado mediante el método _scoringSendFile_
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

id_archivo = "<ID_DE_ARCHIVO>"  ### ID de archivo devuelto al llamar al método scoringSendFile

try:
    response = zero_bounce.scoring_file_status(id_archivo)
    print("ZeroBounce file_status response: " + str(response))
except ZBException as e:
    print("ZeroBounce file_status error: " + str(e))
```

* ####### El API _scoringGetFile_ permite a los usuarios obtener el archivo con los resultados de puntuación del archivo enviado mediante el método _scoringSendFile_
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

id_archivo = "<ID_DE_ARCHIVO>"  ### ID de archivo devuelto al llamar al método scoringSendFile
ruta_descarga_local = "./archivo_descargado.csv"  ### Ruta donde se descargará el archivo

try:
    response = zero_bounce.scoring_get_file(id_archivo, ruta_descarga_local)
    print("ZeroBounce get_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce get_file error: " + str(e))
```

* ####### Eliminar el archivo que se envió mediante el método _scoringSendFile_. El archivo solo se puede eliminar si su estado es `Completado`
```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

id_archivo = "<ID_DE_ARCHIVO>"  ### ID de archivo devuelto

 al llamar al método scoringSendFile

try:
    response = zero_bounce.scoring_delete_file(id_archivo)
    print("ZeroBounce delete_file response: " + str(response))
except ZBException as e:
    print("ZeroBounce delete_file error: " + str(e))
```
