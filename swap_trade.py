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
from config import *

class SwapTrade():
  def __init__(self, dict):
    vars(self).update(dict)

  def fill_trade_pool(self, swap_storage, allow_transactions = False):
    missing_trades = self.order_count - len(self.order_utxos)
    if missing_trades == 0:
      return True #Pool is filled

    ready_utxo = swap_storage.find_utxo_multiple_exact(self.in_type, self.in_quantity)
    available_utxos = len(ready_utxo)

    if available_utxos < missing_trades:
      #Need to create additional UTXO's to fill the pool
      if not allow_transactions:
        return False #If we are not creating, ignore
      #TODO: Create missing UTXO's
      print("Need to create transaction!")
      return False
    
    for use_utxo in ready_utxo[:missing_trades]:
      self.order_utxo.append(use_utxo)
      self.transactions.append(self.create_trade_transaction(use_utxo))
    return True #Pool now filled

  def create_trade_transaction(self, utxo):
    #TODO: Validate utxo is correctly sized
    
    return SwapTransaction({
      "in_type": self.in_type,
      "out_type": self.out_type,
      "in_quantity": self.in_quantity,
      "out_quantity": self.out_quantity,
      "own": True,
      "utxo": utxo,
      "destination": self.destination,
      "state": "new",
      "type": "trade",
      "raw": "--",
      "txid": ""
    })
    
  @staticmethod
  def create_trade(trade_type, in_type, in_quantity, out_type, out_quantity, order_count = 1, destination = None):
    return SwapTrade({
      "in_type": in_type,
      "out_type": out_type,
      "in_quantity": in_quantity,
      "out_quantity": out_quantity,
      "destination": destination,
      "type": trade_type,
      "order_count": order_count,
      "executed_count": 0,
      "order_utxos": [],
      "executed_utxos": [],
      "transactions": []
    })