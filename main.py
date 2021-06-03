from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path

from ui.preview_order import PreviewTransactionDialog
from ui.order_details import OrderDetailsDialog
from ui.new_order import NewOrderDialog
from ui.main_window import MainWindow

from swap_transaction import SwapTransaction
from swap_storage import SwapStorage
from app_settings import AppSettings

from util import *
from rvn_rpc import *


## Main app entry point
if __name__ == "__main__":
  #Load application settings completely first
  app_settings = AppSettings()
  app_settings.on_load()

  app = QApplication(sys.argv)

  if test_rpc_status():
    #Then init swap storage
    swap_storage = SwapStorage()
    swap_storage.on_load()
    #Finally init/run main window
    window = MainWindow(swap_storage)
    window.show()
    app.exec_()
    #Close in reverse order
    swap_storage.on_close()
    app_settings.on_close()
