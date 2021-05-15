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

class SwapStorage:
  def __init__ (self):
    super()
    self.swaps = []
  
  def load_swaps(self):
    global SWAP_STORAGE_PATH
    if not os.path.isfile(SWAP_STORAGE_PATH):
      return []
    fSwap = open(SWAP_STORAGE_PATH, mode="r")
    swapJson = fSwap.read()
    fSwap.close()
    self.swaps = json.loads(swapJson, object_hook=SwapTransaction)
    print("Loaded {} swaps from disk".format(len(self.swaps)))
    return self.swaps

  def load_utxos(self):
    #Locked UTXO's are excluded from the list command
    self.utxos = do_rpc("listunspent")
      
    #Pull list of assets for selecting
    self.assets = do_rpc("listmyassets", asset="", verbose=True)
    self.my_asset_names = [*self.assets.keys()]

    total_balance = 0
    for utxo in self.utxos:
      total_balance += utxo["amount"]
    self.balance = total_balance

  def find_utxo(self, type, quantity, name=None, exact=True):
    if type == "rvn":
      for rvn_utxo in self.utxos:
        if(self.is_taken(rvn_utxo)):
          continue
        if(float(rvn_utxo["amount"]) == float(quantity) and exact) or (rvn_utxo["amount"] >= quantity and not exact):
          return rvn_utxo
    elif type == "asset":
      matching_asset = self.assets[name]
      if(matching_asset):
        if(matching_asset["balance"] < quantity):
          return None
        for asset_utxo in matching_asset["outpoints"]:
          if(self.is_taken(asset_utxo)):
            continue
          if(float(asset_utxo["amount"]) == float(quantity) and exact) or (asset_utxo["amount"] >= quantity and not exact):
            return asset_utxo
    return None

  #check if a swap's utxo is still unspent
  #if not then the swap has been executed!
  def swap_utxo_unspent(self, utxo):
    utxo_parts = utxo.split("|")
    for utxo in self.utxos:
      if utxo["txid"] == utxo_parts[0] and utxo["vout"] == int(utxo_parts[1]):
        return True
    for asset_name in self.my_asset_names:
      for a_utxo in self.assets[asset_name]["outpoints"]:
        if a_utxo["txid"] == utxo_parts[0] and a_utxo["vout"] == int(utxo_parts[1]):
          return True
    return False

  def wallet_lock_all_swaps(self):
    #first unlock everything
    self.wallet_unlock_all()
    #now build all orders and send it in one go
    locked_utxos = []
    for swap in self.swaps:
      if swap.state == "new":
        utxo_parts = swap.utxo.split("|")
        locked_utxos.append({"txid":utxo_parts[0],"vout":int(utxo_parts[1])})
    print("Locking {} UTXO's for buy orders".format(len(locked_utxos)))
    do_rpc("lockunspent", unlock=False, transactions=locked_utxos)
  
  def wallet_lock_single(self, swap):
    utxo_parts = swap.utxo.split("|")
    lock_utxo = [{"txid":utxo_parts[0],"vout":int(utxo_parts[1])}]
    do_rpc("lockunspent", unlock=False, transactions=lock_utxo)

  def wallet_unlock_all(self):
    do_rpc("lockunspent", unlock=True)

  def is_taken(self, utxo):
    for swap in self.swaps:
      expected = "{}|{}".format(utxo["txid"], utxo["vout"])
      if swap.utxo == expected:
        return True
    return False

  def locaked_rvn(self):
    total = 0
    for swap in self.swaps:
      if swap.type == "buy" and swap.state == "new":
        total += swap.totalPrice()
    return total

  def locaked_assets(self):
    total = 0
    for swap in self.swaps:
      if swap.type == "sell" and swap.state == "new":
        total += swap.quantity
    return total

  def add_swap(self, swap):
    self.swaps.append(swap)

  def save_swaps(self):
    global SWAP_STORAGE_PATH
    fSwap = open(SWAP_STORAGE_PATH, mode="w")
    fSwap.truncate()
    json.dump(self.swaps, fSwap, default=lambda o: o.__dict__, indent=2)
    fSwap.flush()
    fSwap.close()