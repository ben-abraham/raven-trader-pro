from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path
from util import *
from rvn_rpc import *

class AppInstance:
  settings = None
  storage = None
  wallet = None
  server = None

  @staticmethod
  def on_init():
    AppInstance.storage = AppStorage()
    AppInstance.wallet = WalletManager()
    AppInstance.server = ServerConnection()
    AppInstance.storage.on_load()
    AppInstance.wallet.on_load()
    #AppInstance.server.on_load()

  @staticmethod
  def on_exit(error=None):
    AppInstance.wallet.on_close()
    AppInstance.storage.on_close()


from swap_transaction import SwapTransaction
from swap_trade import SwapTrade
from app_settings import AppSettings
from app_storage import AppStorage
from wallet_manager import WalletManager
from server_connection import ServerConnection