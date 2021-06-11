from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path, logging
from util import *
from rvn_rpc import *

from app_settings import AppSettings
from app_instance import AppInstance

class WalletAddresses:

  def __init__ (self):
    super()
    self.address_pools = []
  
  def on_load(self):
    self.address_pools = AppInstance.storage.addresses

  def on_close(self):
    AppInstance.storage.addresses = self.address_pools

  def create_new_address(self):
    return do_rpc("getnewaddress")

  def get_pool(self, pool_name="default", create=False):
    for pool in self.address_pools:
      if pool["name"] == pool_name:
        return pool
    if create:
      pool = {"name": pool_name, "addresses": []}
      self.address_pools.append(pool)
      return pool
    return None

  def add_to_pool(self, address, pool_name="default"):
    pool = self.get_pool(pool_name, create=True)
    if address in pool["addresses"]:
      return
    pool["addresses"].append(address)
    logging.info("Adding new address {} to pool [{}]".format(address, pool_name))
    
  def get_single_address(self, pool_name="default", avoid=[]):
    return self.get_address_set(1, pool_name, avoid)[0]
  
  def get_address_set(self, num_addresses=1, pool_name="default", avoid=[]):
    pool = self.get_pool(pool_name, create=True)
    valid_addrs = [addr for addr in pool["addresses"] if addr not in avoid]
    missing_addrs = num_addresses - len(valid_addrs)
    if missing_addrs > 0:
      for i in range(0, missing_addrs):
        new_addr = self.create_new_address()
        self.add_to_pool(new_addr, pool_name)
    #Re-Get latest list
    valid_addrs = [addr for addr in pool["addresses"] if addr not in avoid]
    return valid_addrs[:num_addresses]
