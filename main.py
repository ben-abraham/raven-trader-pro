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
from config import *
    

## Main app entry point
if __name__ == "__main__":
  #Load application settings completely first
  app_settings = AppSettings()
  app_settings.on_load()

  #Then do a basic test of RPC, also can check it is synced here
  chain_info = do_rpc("getblockchaininfo")
  app = QApplication(sys.argv)

  #If the headers and blocks are not within 5 of each other,
  #then the chain is likely still syncing
  chain_updated = False if not chain_info else\
    (chain_info["headers"] - chain_info["blocks"]) < 5

  if chain_info and chain_updated:
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
  elif chain_info:
    show_error("Sync Error", 
    "Server appears to not be fully synchronized. Must be at the latest tip to continue.",
    "Network: {}\r\nCurrent Headers: {}\r\nCurrent Blocks: {}".format(chain_info["chain"], chain_info["headers"], chain_info["blocks"]))
  else:
    show_error("Error connecting", 
    "Error connecting to RPC server.\r\n{}".format(AppSettings.instance.rpc_url()), 
    "Make sure the following configuration variables are in your raven.conf file"+
    "\r\n\r\nserver=1\r\nrpcuser={}\r\nrpcpassword={}".format(AppSettings.instance.rpc_details()["user"], AppSettings.instance.rpc_details()["password"]))
