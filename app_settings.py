from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path
from util import *

SETTINGS_STORAGE_PATH = "~/.raventrader/settings.json"

class AppSettings:
  instance = None

  def __init__ (self):
    super()
    AppSettings.instance = self
    self.settings = {}
  
  def on_load(self):
    self.load_settings()
    self.load_defaults()

  def on_close(self):
    self.save_settings()

  def load_defaults(self):
    self.init_setting("rpc_connections", [
      {"title": "Local Testnet", "user": "", "password": "", "unlock": "", "host": "localhost", "port": 18766, "testnet": True},
      {"title": "Local Mainnet", "user": "", "password": "", "unlock": "", "host": "localhost", "port": 8766, "testnet": False},
    ])

    self.init_setting("data_path", "~/.raventrader/data")
    self.init_setting("fee_rate", 0.01)
    self.init_setting("default_destination", "")
    self.init_setting("locking_mode", True)

#
# File I/O
#

  def load_settings(self):
    load_path = os.path.expanduser(SETTINGS_STORAGE_PATH)
    self.settings = load_json(load_path, None, "Settings", default={})
    return self.settings

  def save_settings(self):
    save_path = os.path.expanduser(SETTINGS_STORAGE_PATH)
    ensure_directory(os.path.dirname(save_path))
    save_json(save_path, self.settings)

  def init_setting(self, setting_name, init_value):
    self.write_setting(setting_name, self.read_setting(setting_name, init_value))

  def read_setting(self, setting_name, default=None):
    return self.settings[setting_name] if setting_name in self.settings else default

  def write_setting(self, setting_name, new_value):
    self.settings[setting_name] = new_value
  
  read=read_setting
  write=write_setting

#
# RPC Settings
#

  def rpc_details(self):
    rpc_connections = self.read("rpc_connections")
    return rpc_connections[0]

  def rpc_url(self):
    rpc_details = self.rpc_details()
    return "http://{}:{}@{}:{}".format(rpc_details["user"], rpc_details["password"], rpc_details["host"], rpc_details["port"])

  def rpc_unlock(self):
    return self.rpc_details()["unlock"]

#
# Other helper
#

  def lock_mode(self):
    return self.read_setting("locking_mode", True)