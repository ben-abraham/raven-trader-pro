from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path, logging

SETTINGS_STORAGE_PATH = "~/.raventrader/settings.json"

#Just copying to avoid cyclical dependency. TODO: Better
def ensure_directory(dir):
  if not os.path.exists(dir):
    os.makedirs(dir)

def load_json(path, hook, title, default=[]):
  if not os.path.isfile(path):
    #logging.info("No {} records.".format(title))
    return default
  fSwap = open(path, mode="r")
  swapJson = fSwap.read()
  fSwap.close()
  data = json.loads(swapJson, object_hook=hook)
  #logging.info("Loaded {} {} records from disk".format(len(data), title))
  return data

def save_json(path, data):
  dataJson = json.dumps(data, default=lambda o: o.__dict__, indent=2)
  fSwap = open(path, mode="w")
  fSwap.truncate()
  fSwap.write(dataJson)
  fSwap.flush()
  fSwap.close()

class AppSettings:

  def __init__ (self):
    super()
    self.settings = {}
  
  def on_load(self):
    self.load_settings()
    first_launch = self.load_defaults()
    self.save_settings() #Save any created defaults
    return first_launch
    

  def on_close(self):
    self.save_settings()

  def load_defaults(self):
    first_launch = (self.settings == {})

    self.init_setting("rpc_connections", [
      {"title": "Local Mainnet", "user": "", "password": "", "unlock": "", "host": "127.0.0.1", "port": 8766, "testnet": False},
      {"title": "Local Testnet", "user": "", "password": "", "unlock": "", "host": "127.0.0.1", "port": 18766, "testnet": True},
    ])

    self.init_setting("data_path", "~/.raventrader/data")
    self.init_setting("fee_rate", 0.0125)
    self.init_setting("default_destination", "")
    self.init_setting("locking_mode", True)
    self.init_setting("active_rpc", 0)
    self.init_setting("update_interval", 5000)
    self.init_setting("server_url", "https://raventrader.net")

    return first_launch
#
# File I/O
#

  def load_settings(self):
    self.settings = load_json(self.get_path(), None, "Settings", default={})
    return self.settings

  def save_settings(self):
    save_json(self.get_path(), self.settings)

  def get_path(self):
    path = os.path.expanduser(SETTINGS_STORAGE_PATH)
    ensure_directory(os.path.dirname(path))
    return path

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

  def rpc_index(self):
    return self.read("active_rpc")

  def set_rpc_index(self, new_index):
    return self.write("active_rpc", new_index)

  def rpc_details(self):
    rpc_connections = self.read("rpc_connections")
    return rpc_connections[self.rpc_index()]

  def rpc_url(self):
    rpc_details = self.rpc_details()
    return "http://{}:{}@{}:{}".format(rpc_details["user"], rpc_details["password"], rpc_details["host"], rpc_details["port"])

  def rpc_unlock(self):
    return self.rpc_details()["unlock"]

  def rpc_set_testnet(self, testnet):
    rpc_connections = self.read("rpc_connections")
    rpc_connections[self.rpc_index()]["testnet"] = testnet
    self.write("rpc_connections", rpc_connections)

  def rpc_save_path(self):
    rpc = self.rpc_details()
    return "{}_{}.json".format(rpc["host"].replace(".", "_"), rpc["port"])

  def rpc_mainnet(self):
    return self.rpc_details()["testnet"] == False

#
# Other helper
#

  def server_enabled(self):
    return True if self.read_setting("server_url") else False

  def lock_mode(self):
    return self.read_setting("locking_mode", True)

  def fee_rate(self):
    return self.read_setting("fee_rate")