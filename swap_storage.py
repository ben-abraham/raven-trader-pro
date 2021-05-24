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

  def remove_swap(self, swap):
    utxo_parts = swap.utxo.split("|")
    self.remove_lock(utxo_parts[0], int(utxo_parts[1]))
    self.swaps.remove(swap)

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

  def remove_lock(self, txid, vout):
    for lock in self.locks:
      if txid == lock["txid"] and vout == lock["vout"]:
        self.locks.remove(lock)

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
    #Cheat a bit and embed the asset name in it's metadata. This simplified things later
    for name in self.my_asset_names:
      self.assets[name]["name"] = name

    total_balance = 0
    for utxo in self.utxos:
      total_balance += utxo["amount"]
    self.balance = total_balance

  def find_utxo(self, type, quantity, name=None, exact=True, skip_locks=False, skip_rounded=True, sort_utxo=False):
    #print("Find UTXO: {} Exact: {} Skip Locks: {}".format(quantity, exact, skip_locks))
    if type == "rvn":
      utxo_src = sorted([utxo for utxo in self.utxos], key=lambda utxo: utxo["amount"]) if sort_utxo else self.utxos
      for rvn_utxo in utxo_src:
        if(self.is_taken(rvn_utxo, skip_locks)):
          continue
        utxo_amount = float(rvn_utxo["amount"])
        if(skip_rounded and round(utxo_amount, 0) == utxo_amount):
          continue #Default-Optionally skip ravencoin transfers of exact amounts. there are *likely* missed trade UTXO's
        if(utxo_amount == float(quantity) and exact) or (rvn_utxo["amount"] >= quantity and not exact):
          return rvn_utxo
    elif type == "asset":
      matching_asset = self.assets[name]
      if(matching_asset):
        if(matching_asset["balance"] < quantity):
          return None
        utxo_src = sorted(matching_asset["outpoints"], key=lambda a_utxo: a_utxo["amount"]) if sort_utxo else matching_asset["outpoints"]
        for asset_utxo in matching_asset["outpoints"]:
          if(self.is_taken(asset_utxo, skip_locks)):
            continue
          if(float(asset_utxo["amount"]) == float(quantity) and exact) or (asset_utxo["amount"] >= quantity and not exact):
            return asset_utxo
    return None

  def find_utxo_set(self, type, quantity, mode="combine", name=None, skip_locks=False):
    print("Finding UTXO set for {} {}".format(quantity, type))
    found_set = None
    total = 0

    sorted_set = []
    if type == "rvn":
      sorted_set = sorted([utxo for utxo in self.utxos], key=lambda utxo: utxo["amount"])
    elif type == "asset":
      sorted_set = sorted(self.assets[name]["outpoints"], key=lambda utxo: utxo["amount"])

    if mode == "combine":
      #Try to combine as many UTXO's as possible into a single Transaction
      #This raises your transaction fees slighty (more data) but is ultimately a good thing for the network
      #Don't need to do anything actualy b/c default behavior is to go smallest-to-largest
      #However, if we have a single, unrounded UTXO that is big enough. it's always more efficient to use that instead
      quick_check = self.find_utxo(type, quantity, name=name, skip_locks=skip_locks, exact=False, sort_utxo=True)
      if quick_check:
        #If we have a single UTXO big enough, just use it and get change. sort_utxo ensures we find the smallest first
        found_set = [quick_check]
        total = quick_check["amount"]
    elif mode == "minimize":
      #Minimize the number of UTXO's used, to reduce transaction fees
      #This minimizes transaction fees but
      quick_check = self.find_utxo(type, quantity, name=name, skip_locks=skip_locks, exact=False, sort_utxo=True)
      quick_check_2 = self.find_utxo(type, quantity, name=name, skip_locks=skip_locks, exact=False, skip_rounded=False, sort_utxo=True)
      if quick_check:
        #If we have a single UTXO big enough, just use it and get change. sort_utxo ensures we find the smallest first
        found_set = [quick_check]
        total = quick_check["amount"]
      elif quick_check_2:
        #In this case we had a large enough single UTXO but it was an evenly rounded one (and no un-rounded ones existed)
        found_set = [quick_check_2]
        total = quick_check_2["amount"]
      else:
        #Just need to reverse the search to make it build from the fewest UTXO's
        sorted_set.reverse()

    if found_set == None:
      found_set = []
      while total < quantity and len(sorted_set) > 0:
        removed = sorted_set.pop(0)
        total += removed["amount"]
        found_set.append(removed)

    if total >= quantity:
      print("Num UTXO: {}".format(len(found_set)))
      print("Total: {}".format(total))
      print("Change: {}".format(total - quantity))
      return (total, found_set)
    else:
      print("Not enough funds found")
      print("Total: {}".format(total))
      print("Missing: {}".format(total - quantity))
      return (None, None)

  #check if a swap's utxo is still unspent
  #if not then the swap has been executed!
  def swap_utxo_unspent(self, utxo):
    return self.search_utxo(utxo) != None

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

  def search_utxo(self, utxo):
    utxo_parts = utxo.split("|")
    for utxo in self.utxos:
      if utxo["txid"] == utxo_parts[0] and utxo["vout"] == int(utxo_parts[1]):
        return {"type": "rvn", "utxo": utxo}
    for asset_name in self.my_asset_names:
      for a_utxo in self.assets[asset_name]["outpoints"]:
        if a_utxo["txid"] == utxo_parts[0] and a_utxo["vout"] == int(utxo_parts[1]):
          return {"type": "asset", "utxo": a_utxo, "name": asset_name}
    return None

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