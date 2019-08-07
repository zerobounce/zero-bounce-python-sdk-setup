from setuptools import setup

setup(
    name='zerobouncesdk',
    version='0.0.6',
    description='The ZeroBounce SDK for Python programming language',
    license='MIT',
    packages=['zerobouncesdk'],
    author='ZeroBounce',
    author_email='integrations@zerobounce.net',
    keywords=['zero', 'bounce', 'sdk'],
    url='https://github.com/zerobounce-llc/zero-bounce-python-sdk-setup', install_requires=['requests', 'requests_toolbelt']
)
