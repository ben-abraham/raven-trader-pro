from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path, logging
from util import load_json, save_json, init_list
from rvn_rpc import *

from swap_transaction import SwapTransaction
from swap_trade import SwapTrade
from app_instance import AppInstance

class AppStorage:

  def __init__ (self):
    super()
    self.swaps = []
    self.locks = []
    self.history = []
    self.addresses = []
  
  def on_load(self):
    self.load_data()

  def on_close(self):
    self.save_data()

#
# File I/O
#
  def load_data(self):
    loaded_data = load_json(self.get_path(), dict, "Storage")
    self.swaps =     init_list(loaded_data["trades"],         SwapTrade) if "trades"   in loaded_data else []
    self.locks =     init_list(loaded_data["locks"],               dict) if "locks"    in loaded_data else []
    self.history =   init_list(loaded_data["history"],  SwapTransaction) if "history"  in loaded_data else []
    self.addresses = init_list(loaded_data["addresses"],           dict) if "addresses"in loaded_data else [{"name": "default", "addresses": []}]

  def save_data(self):
    save_payload = {
      "trades": self.swaps,
      "locks": self.locks,
      "history": self.history,
      "addresses": self.addresses
    }
    save_json(self.get_path(), save_payload)

  def get_path(self):
    base_path = os.path.expanduser(AppInstance.settings.read("data_path"))
    ensure_directory(base_path)
    return os.path.join(base_path, AppInstance.settings.rpc_save_path())