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
    self.locks = []
  
  def load_swaps(self):
    if not os.path.isfile(SWAP_STORAGE_PATH):
      return []
    fSwap = open(SWAP_STORAGE_PATH, mode="r")
    swapJson = fSwap.read()
    fSwap.close()
    self.swaps = json.loads(swapJson, object_hook=SwapTransaction)
    print("Loaded {} swaps from disk".format(len(self.swaps)))
    return self.swaps

  def save_swaps(self):
    swapJson = json.dumps(self.swaps, default=lambda o: o.__dict__, indent=2)
    fSwap = open(SWAP_STORAGE_PATH, mode="w")
    fSwap.truncate()
    fSwap.write(swapJson)
    fSwap.flush()
    fSwap.close()
  
  def load_locked(self):
    if not os.path.isfile(LOCK_STORAGE_PATH):
      return []
    fLock = open(LOCK_STORAGE_PATH, mode="r")
    lockJson = fLock.read()
    fLock.close()
    self.locks = json.loads(lockJson)
    print("Loaded {} locks from disk".format(len(self.locks)))
    return self.locks

  def save_locked(self):
    lockJson = json.dumps(self.locks, default=lambda o: o.__dict__, indent=2)
    fLock = open(LOCK_STORAGE_PATH, mode="w")
    fLock.truncate()
    fLock.write(lockJson)
    fLock.flush()
    fLock.close()

  def add_swap(self, swap):
    self.swaps.append(swap)
    utxo_parts = swap.utxo.split("|")
    self.add_lock(utxo_parts[0], int(utxo_parts[1]))

  def add_lock(self, txid, vout):
    for lock in self.locks:
      if txid == lock["txid"] and vout == lock["vout"]:
        return #Already added
    print("Locking UTXO {}|{}".format(txid, vout))
    for utxo in self.utxos:
      if txid == utxo["txid"] and vout == utxo["vout"]:
        self.locks.append({"txid": txid, "vout": vout, "type": "rvn", "amount": utxo["amount"]})
        return #Locking ravencoin
    for asset in self.my_asset_names:
      for a_utxo in self.assets[asset]["outpoints"]:
        if txid == a_utxo["txid"] and vout == a_utxo["vout"]:
          self.locks.append({"txid": txid, "vout": vout, "type": "asset", "asset": asset, "amount": a_utxo["amount"]})
          return #Locking assets

  def refresh_locks(self):
    for swap in self.swaps:
      if swap.state == "new":
        utxo_parts = swap.utxo.split("|")
        self.add_lock(utxo_parts[0], int(utxo_parts[1]))

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

  def find_utxo(self, type, quantity, name=None, exact=True, skip_locks=False):
    #print("Find UTXO: {} Exact: {} Skip Locks: {}".format(quantity, exact, skip_locks))
    if type == "rvn":
      for rvn_utxo in self.utxos:
        if(self.is_taken(rvn_utxo, skip_locks)):
          continue
        if(float(rvn_utxo["amount"]) == float(quantity) and exact) or (rvn_utxo["amount"] >= quantity and not exact):
          return rvn_utxo
    elif type == "asset":
      matching_asset = self.assets[name]
      if(matching_asset):
        if(matching_asset["balance"] < quantity):
          return None
        for asset_utxo in matching_asset["outpoints"]:
          if(self.is_taken(asset_utxo, skip_locks)):
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

  def is_taken(self, utxo, skip_locks=False):
    if not skip_locks:
      for lock in self.locks:
        if lock["txid"] == utxo["txid"] and lock["vout"] == utxo["vout"]:
          return True
    for swap in self.swaps:
      expected = "{}|{}".format(utxo["txid"], utxo["vout"])
      if swap.utxo == expected:
        return True
    return False

  def locaked_rvn(self, only_orders=True):
    total = 0
    if only_orders:
      for swap in self.swaps:
        if swap.type == "buy" and swap.state == "new":
          total += swap.totalPrice()
    else:
      for lock in self.locks:
        if lock["type"] == "rvn":
          total += lock["amount"]
    return total

  def locaked_assets(self, only_orders=True):
    total = 0
    if only_orders:
      for swap in self.swaps:
        if swap.type == "sell" and swap.state == "new":
          total += swap.quantity
    else:
      for lock in self.locks:
        if lock["type"] == "asset":
          total += lock["amount"]
    return total