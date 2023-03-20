import requests

class ApiError(Exception):
    """An error originated from the API"""

class HttpRequest:
    """Http helper to manage all calls to the Zero Bounce V2 API"""

    def _process_response(response: requests.Response):
        try:
            return response.json()
        except ValueError:
            return {}

    @classmethod
    def get(cls, url, params=None):
        # req = requests.Request("GET", url, params=params)
        # prepared = req.prepare()
        # pretty_print_post(prepared)
        response = requests.get(url, params=params)
        return cls._process_response(response)

    @classmethod
    def post(cls, url, data, files=None):
        if files:
            response = requests.post(url, data=data, files=files)
        else:
            response = requests.post(url, json=data)
        
        return cls._process_response(response)
    
    @staticmethod
    def parse_response(response, response_class):
        try:
            return response_class(response)
        except KeyError:
            raise ApiError(response["error"])
        

# def pretty_print_post(req):
#     print('{}\n{}\n{}\n\n{}'.format(
#         '-----------START-----------',
#         req.method + ' ' + req.url,
#         '\n'.join('{}: {}'.format(k, v) for k, v in req.headers.items()),
#         str(req.body).replace("\\r\\n", "\n"),
#     ))