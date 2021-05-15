from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path

from preview_order import PreviewTransactionDialog
from swap_transaction import SwapTransaction
from order_details import OrderDetailsDialog
from swap_storage import SwapStorage
from new_order import NewOrderDialog
from main_window import MainWindow

from util import *
from rvn_rpc import *
from config import *
    

## Main app entry point
if __name__ == "__main__":
  chain_info = do_rpc("getblockchaininfo")
  app = QApplication(sys.argv)

  #If the headers and blocks are not within 5 of each other,
  #then the chain is likely still syncing
  chain_updated = False if not chain_info else\
    (chain_info["headers"] - chain_info["blocks"]) < 5

  if chain_info and chain_updated:
    swap_storage = SwapStorage()
    swap_storage.load_swaps()
    swap_storage.load_utxos()

    window = MainWindow(swap_storage)
    window.show()
    app.exec_()

    swap_storage.save_swaps()
  elif chain_info:
    show_error("Sync Error", 
    "Server appears to not be fully synchronized. Must be at the latest tip to continue.",
    "Network: {}\r\nCurrent Headers: {}\r\nCurrent Blocks: {}".format(chain_info["chain"], chain_info["headers"], chain_info["blocks"]))
  else:
    show_error("Error connecting", 
    "Error connecting to RPC server.\r\n{}".format(RPC_URL), 
    "Make sure the following configuration variables are in your raven.conf file"+
    "\r\n\r\nserver=1\r\nrpcuser={}\r\nrpcpassword={}".format(RPC_USERNAME, RPC_PASSWORD))
