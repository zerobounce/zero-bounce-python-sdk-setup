#### INSTALACIÓN
```bash
pip install zerobouncesdk
```

#### USO
Importa el SDK en tu archivo:

```python
from zerobouncesdk import ZeroBounce
```

Inicializa el SDK con tu clave de API. Puedes opcionalmente especificar una URL base para usar una región de API diferente o un endpoint personalizado:

**Por defecto**: Usa el endpoint predeterminado de ZeroBounce API
```python
from zerobouncesdk import ZeroBounce

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")
```

**Usando regiones de API predefinidas**: Usa una de las regiones de API disponibles
```python
from zerobouncesdk import ZeroBounce, ZBApiUrl

# Usar región USA
zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>", base_url=ZBApiUrl.API_USA_URL)

# Usar región EU
zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>", base_url=ZBApiUrl.API_EU_URL)

# Usar región predeterminada (explícita)
zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>", base_url=ZBApiUrl.API_DEFAULT_URL)
```

**Usando una URL personalizada**: Proporciona tu propia URL base
```python
zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>", base_url="https://custom-api.example.com/v2")
```

**Regiones de API disponibles:**
- `ZBApiUrl.API_DEFAULT_URL` - API predeterminada de ZeroBounce (https://api.zerobounce.net/v2/)
- `ZBApiUrl.API_USA_URL` - API de región USA (https://api-us.zerobounce.net/v2/)
- `ZBApiUrl.API_EU_URL` - API de región EU (https://api-eu.zerobounce.net/v2/)

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


* ####### Encontrar el formato de correo electrónico correcto cuando proporcionas un nombre y un dominio o nombre de empresa

```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

# Opción 1: Usar find_email_format con dominio
dominio = "example.com"  # El dominio de correo electrónico para encontrar el formato
nombre = "John"          # El nombre de la persona cuyo formato de correo se está buscando
segundo_nombre = "Quill"  # Opcional: El segundo nombre de la persona
apellido = "Doe"          # Opcional: El apellido de la persona

try:
    response = zero_bounce.find_email_format(
        first_name=nombre,
        domain=dominio,
        middle_name=segundo_nombre,
        last_name=apellido
    )
    print("Correo: " + str(response.email))
    print("Confianza del correo: " + str(response.email_confidence))
except ZBException as e:
    print("Error de ZeroBounce find_email_format: " + str(e))
```

```python
# Opción 2: Usar find_email_format con company_name
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

nombre_empresa = "Acme Corp"  # El nombre de la empresa para encontrar el formato de correo
nombre = "Jane"                # El nombre de la persona

try:
    response = zero_bounce.find_email_format(
        first_name=nombre,
        company_name=nombre_empresa
    )
    print("Correo: " + str(response.email))
    print("Dominio: " + str(response.domain))
    print("Empresa: " + str(response.company_name))
except ZBException as e:
    print("Error de ZeroBounce find_email_format: " + str(e))
```

```python
# Opción 3: Usar find_domain para descubrir formatos de correo para un dominio
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

dominio = "example.com"  # El dominio de correo electrónico a analizar

try:
    response = zero_bounce.find_domain(domain=dominio)
    print("Dominio: " + str(response.domain))
    print("Formato: " + str(response.format))
    print("Confianza: " + str(response.confidence))
    print("Otros formatos: " + str(len(response.other_domain_formats)))
except ZBException as e:
    print("Error de ZeroBounce find_domain: " + str(e))
```

```python
# Opción 4: Usar find_domain con company_name
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

nombre_empresa = "Acme Corp"  # El nombre de la empresa a analizar

try:
    response = zero_bounce.find_domain(company_name=nombre_empresa)
    print("Dominio: " + str(response.domain))
    print("Empresa: " + str(response.company_name))
    print("Formato: " + str(response.format))
    print("Confianza: " + str(response.confidence))
    for fmt in response.other_domain_formats:
        print(f"  Alternativa: {fmt.format} (confianza: {fmt.confidence})")
except ZBException as e:
    print("Error de ZeroBounce find_domain: " + str(e))
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

* ####### (Deprecado) Identificar el formato de correo electrónico correcto cuando proporcionas un nombre y un dominio de correo electrónico

> **⚠️ Deprecado:** El método `guess_format` está deprecado y se eliminará en futuras versiones. Use `find_email_format` o `find_domain` en su lugar (vea los ejemplos arriba).

```python
from zerobouncesdk import ZeroBounce, ZBException

zero_bounce = ZeroBounce("<TU_CLAVE_DE_API>")

domain = "example.com" # El dominio de correo electrónico para encontrar el formato de correo
first_name = "John" # El nombre de la persona cuyo formato de correo se está buscando
middle_name = "Quill" # El segundo nombre de la persona cuyo formato de correo se está buscando
last_name = "Doe" # El apellido de la persona cuyo formato de correo se está buscando

try:
    response = zero_bounce.guess_format(domain, first_name, middle_name, last_name)
    print("ZeroBounce guess format response: " + response)
except ZBException as e:
    print("ZeroBounce guess format error: " + str(e))
```
