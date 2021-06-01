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

from swap_transaction import SwapTransaction

class SwapTrade():
  def __init__(self, dict):
    vars(self).update(dict)

  def total_price(self):
    #Don't need to multiply 
    if self.type == "buy":
      return float(self.in_quantity)
    elif self.type == "sell":
      return float(self.out_quantity)
    elif self.type == "trade":
      return float(self.in_quantity) #In the case of a trade, consider the quantity of our asset, to be the "price"
    else:
      return 0

  def quantity(self):
    if self.type == "buy":
      return float(self.out_quantity)
    elif self.type == "sell":
      return float(self.in_quantity)
    elif self.type == "trade":
      return float(self.out_quantity) #In the case of a trade, consider the desired asset to be the quantity
    else:
      return 0

  def unit_price(self):
    qty = self.quantity()
    return (0 if qty == 0 else self.total_price() / qty)

  def set_unit_price(self, new_price):
    qty = self.quantity()
    if self.type == "buy":
      self.in_quantity = new_price * qty
    elif self.type == "sell":
      self.out_quantity = new_price * qty
    elif self.type == "trade":
      self.in_quantity = new_price * qty

  def asset(self):
    if self.type == "buy":
      return self.out_type
    elif self.type == "sell":
      return self.in_type
    elif self.type == "trade":
      return self.out_type #In the case of a trade, consider the desired asset to be the "asset" of the trade
    else:
      return "N/A"

  def attempt_fill_trade_pool(self, swap_storage, max_add = None):
    missing_trades = self.missing_trades()
    if missing_trades == 0:
      return True #Pool is filled

    ready_utxo = swap_storage.find_utxo_multiple_exact(self.in_type, self.in_quantity)
    available_utxos = len(ready_utxo)

    if available_utxos < missing_trades:
      #Need to create additional UTXO's to fill the pool
      return False

    if max_add: #Allow us to only add on-at-a-time if we want
      ready_utxo = ready_utxo[:max_add]
    
    for ready_utxo in ready_utxo[:missing_trades]:
      use_utxo = make_utxo(ready_utxo)
      self.order_utxos.append(use_utxo)
      self.transactions.append(self.create_trade_transaction(use_utxo))
      swap_storage.add_lock(utxo=use_utxo)
    return True #Pool now filled (/or there are enough items to fill it otherwise)

  def setup_trade(self, swap_storage, max_add=None):
    num_create = self.missing_trades()
    if max_add:
      num_create = min(max_add, num_create)
    quantity_required = self.in_quantity * num_create

    #TODO: MANY better ways to handle this.....
    #But for now I want to encourage address reuse especially with bulk trades
    addr_list = [addr["address"] for addr in do_rpc("listreceivedbyaddress")]

    if num_create > len(addr_list) + 2: #2 extra addrs for asset +  rvn change
      raise Exception("Not enough addresses")

    setup_vins = []
    setup_vouts = {}
    asset_total = 0
    
    for n in range(0, num_create):
      addr = addr_list[n]
      if self.type == "buy":
        setup_vouts[addr] = self.in_quantity #Create rvn vout for buying
      elif self.type == "sell":
        setup_vouts[addr] = make_transfer(self.in_type, self.in_quantity) #Create asset vouts for selling
      elif self.type == "trade":
        setup_vouts[addr] = make_transfer(self.in_type, self.in_quantity) #Create asset vouts for trading
    
    asset_change_addr = addr_list[num_create]
    rvn_change_addr = addr_list[num_create + 1]

    #Send any extra assets back to ourselves
    if self.in_type != "rvn":
      (asset_total, asset_vins) = swap_storage.find_utxo_set("asset", quantity_required, name=self.in_type, skip_locks = True)
      setup_vins = [utxo_copy(vin) for vin in asset_vins]
      if asset_total > quantity_required:
        setup_vouts[asset_change_addr] = make_transfer(self.in_type, asset_total - quantity_required)

    estimated_size = calculate_size(setup_vins, setup_vouts)
    estimated_fee = calculated_fee_from_size(estimated_size)

    raw_tx = do_rpc("createrawtransaction", inputs=setup_vins, outputs=setup_vouts)

    if self.type == "buy":
      funded_tx = fund_transaction_final(swap_storage, do_rpc, quantity_required, 0, \
        rvn_change_addr, setup_vins, setup_vouts, raw_tx)
    else:
      funded_tx = fund_transaction_final(swap_storage, do_rpc, 0, 0, \
        rvn_change_addr, setup_vins, setup_vouts, raw_tx)

    raw_tx = do_rpc("createrawtransaction", inputs=setup_vins, outputs=setup_vouts)
    sign_tx = do_rpc("signrawtransaction", hexstring=raw_tx)
    
    return sign_tx["hex"]

  def missing_trades(self):
    return self.order_count - len(self.order_utxos)

  def can_create_single_order(self, swap_storage):
    return self.attempt_fill_trade_pool(swap_storage, max_add=1)

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