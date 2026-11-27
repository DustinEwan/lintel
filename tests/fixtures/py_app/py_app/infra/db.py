import importlib

from ..app.checkout import checkout
from ..domain.order import Order


def connect():
    importlib.import_module("py_app.domain.order")
    importlib.import_module(".order", package="py_app.domain")
    return checkout(), Order
