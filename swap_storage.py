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

from swap_transaction import SwapTransaction
from swap_trade import SwapTrade
from app_settings import AppSettings

class SwapStorage:

  def __init__ (self):
    super()
    self.swaps = []
    self.locks = []
    self.history = []
    self.on_swap_executed = None
    self.on_utxo_spent = None
  
  def on_load(self):
    self.load_data()
    self.update_wallet()
    self.wallet_unlock_all()
    self.refresh_locks()

  def on_close(self):
    self.save_data()

  def call_if_set(self, fn_call, item):
    if fn_call != None:
      fn_call(item)

#
# File I/O
#
  def load_data(self):
    loaded_data = load_json(self.get_path(), dict, "Storage")
    self.swaps = init_list(loaded_data["trades"], SwapTrade) if "trades" in loaded_data else []
    self.locks = init_list(loaded_data["locks"], dict) if "locks" in loaded_data else []
    self.history = init_list(loaded_data["history"], SwapTransaction) if "history" in loaded_data else []

  def save_data(self):
    save_payload = {
      "trades": self.swaps,
      "locks": self.locks,
      "history": self.history
    }
    save_json(self.get_path(), save_payload)

  def get_path(self):
    base_path = os.path.expanduser(AppSettings.instance.read("data_path"))
    ensure_directory(base_path)
    return os.path.join(base_path, AppSettings.instance.rpc_save_path())

#
# Basic Operations
#

  def add_swap(self, swap_trade):
    self.swaps.append(swap_trade)

  def remove_swap(self, swap_trade):
    self.swaps.remove(swap_trade)

  def add_completed(self, swap_transaction):
    self.history.append(swap_transaction)

  def remove_completed(self, swap_transaction):
    self.history.remove(swap_transaction)

#
# Balance Calculation
#

  def calculate_balance(self):
    bal_total = [0, 0, 0] #RVN, Unique Assets, Asset Total
    for utxo in self.utxos:
      bal_total[0] += utxo["amount"]
    for asset in self.my_asset_names:
      bal_total[1] += 1
      asset_total = 0
      for outpoint in self.assets[asset]["outpoints"]:
        asset_total += outpoint["amount"]
      self.assets[asset]["balance"] = self.assets[asset]["available_balance"] = asset_total
      bal_total[2] += asset_total
    bal_avail = bal_total[:]

    for my_lock in self.locks:
      if my_lock["type"] == "rvn":
        bal_avail[0] -= my_lock["amount"]
      elif my_lock["type"] == "asset":
        bal_avail[2] -= my_lock["amount"]
        self.assets[my_lock["asset"]]["available_balance"] -= my_lock["amount"]
      continue

    self.available_balance = tuple(bal_avail)
    self.total_balance = tuple(bal_total)

  def rvn_balance(self):
    return self.available_balance[0]

  def asset_balance(self):
    return self.available_balance[2]

#
# Wallet Interaction
#

  def wallet_prepare_transaction(self):
    print("Preparing for a transaction")
    if AppSettings.instance.lock_mode():
      print("Locking")
    else:
      print("Non-Locking")

  def wallet_completed_transaction(self):
    print("Completed a transaction")
    if AppSettings.instance.lock_mode():
      print("Locking")
    else:
      print("Non-Locking")

  def wallet_lock_all_swaps(self):
    #first unlock everything
    self.wallet_unlock_all()
    #now build all orders and send it in one go
    locked_utxos = []
    for swap in self.swaps:
      for utxo in swap.order_utxos:
        locked_utxos.append(utxo)
    print("Locking {} UTXO's from orders".format(len(locked_utxos)))
    self.wallet_lock_utxos(locked_utxos)

  def wallet_lock_utxos(self, utxos=[], lock = True):
    txs = []
    for utxo in utxos:
      (txid, vout) = split_utxo(utxo)
      txs.append({"txid":txid,"vout":vout})
    do_rpc("lockunspent", unlock=not lock, transactions=txs)

  def wallet_lock_single(self, txid=None, vout=None, utxo=None, lock = True):
    if utxo != None and txid == None and vout == None:
      (txid, vout) = split_utxo(utxo)
    do_rpc("lockunspent", unlock=not lock, transactions=[{"txid":txid,"vout":vout}])

  def load_wallet_locked(self):
    if AppSettings.instance.lock_mode():
      wallet_locks = do_rpc("listlockunspent")
      for lock in wallet_locks:
        txout = do_rpc("gettxout", txid=lock["txid"], n=int(lock["vout"]), include_mempool=True)
        if txout:
          utxo = vout_to_utxo(txout, lock["txid"], int(lock["vout"]))
          if utxo["type"] == "rvn":
            self.utxos.append(utxo)
          elif utxo["type"] == "asset":
            if utxo["asset"] not in self.assets:
              self.assets[utxo["asset"]] = {"balance": 0, "outpoints":[]}
            self.assets[utxo["asset"]]["balance"] += utxo["amount"]
            self.assets[utxo["asset"]]["outpoints"].append(utxo)

  def wallet_unlock_all(self):
    do_rpc("lockunspent", unlock=True)

  def invalidate_all(self):
    self.utxos = []
    self.assets = {}
    self.my_asset_names = []
    self.total_balance = (0,0,0)
    self.available_balance = (0,0,0)

  def update_wallet(self):
    #Locked UTXO's are excluded from the list command
    self.utxos = do_rpc("listunspent")
      
    #Pull list of assets for selecting
    self.assets = do_rpc("listmyassets", asset="", verbose=True)

    removed_orders = self.search_completed()
    for (trade, utxo) in removed_orders:
      #TODO: Notify via event here
      print("Order removed: ", utxo)
      #If we find a matching order in the tx list, add it to history
      #TODO: search chain for used UTXO
      finished_order = trade.order_completed(self, utxo, None)

    #Load details of wallet-locked transactions, inserted into self.utxos/assets
    self.load_wallet_locked()

    self.my_asset_names = [*self.assets.keys()]
    #Cheat a bit and embed the asset name in it's metadata. This simplified things later
    for name in self.my_asset_names:
      self.assets[name]["name"] = name

    self.calculate_balance()

#
# Lock Management
#

  def add_lock(self, txid=None, vout=None, utxo=None):
    if utxo != None and txid == None and vout == None:
      (txid, vout) = split_utxo(utxo)
    for lock in self.locks:
      if txid == lock["txid"] and vout == lock["vout"]:
        return #Already added
    print("Locking UTXO {}|{}".format(txid, vout))
    txout = do_rpc("gettxout", txid=txid, n=vout, include_mempool=True) #True means this will be None when spent in mempool
    if txout:
      utxo = vout_to_utxo(txout, txid, vout)
      self.locks.append(utxo)
      if AppSettings.instance.lock_mode():
        self.wallet_lock_single(txid, vout)

  def remove_lock(self, txid=None, vout=None, utxo=None):
    if utxo != None and txid == None and vout == None:
      (txid, vout) = split_utxo(utxo)
    for lock in self.locks:
      if txid == lock["txid"] and vout == lock["vout"]:
        self.locks.remove(lock)
    print("Unlocking UTXO {}|{}".format(txid, vout))
    #in wallet-lock mode we need to return these to the wallet
    if AppSettings.instance.lock_mode():
      self.wallet_lock_single(txid, vout, lock=False)

  def refresh_locks(self, clear=False):
    if clear:
      print("Clearing")
      print(len(self.locks))
      self.wallet_unlock_all()
      self.locks = []
    for swap in self.swaps:
      for utxo in swap.order_utxos:
        self.add_lock(utxo=utxo)
    if AppSettings.instance.lock_mode():
      self.wallet_lock_all_swaps()
    print(len(self.locks))

  def lock_quantity(self, type):
    if type == "rvn":
      return sum([float(lock["amount"]) for lock in self.locks if lock["type"] == "rvn"])
    else:
      return sum([float(lock["amount"]) for lock in self.locks if lock["type"] == "asset" and lock["name"] == type])

  def search_completed(self, include_mempool=True):
    all_found = []
    for trade in self.swaps:
      for utxo in trade.order_utxos:
        if self.swap_utxo_spent(utxo, in_mempool=include_mempool, check_cache=False):
          all_found.append((trade, utxo))
    return all_found
          
#
# UTXO Searching
#

  def find_utxo(self, type, quantity, name=None, exact=True, include_locked=False, skip_rounded=True, sort_utxo=False):
    print("Find {} UTXO: {} Exact: {} Include Locks: {}".format(type, quantity, exact, include_locked))
    available = self.get_utxos(type, name, include_locked=include_locked)
    for utxo in available:
      if(float(utxo["amount"]) == float(quantity) and exact) or (float(utxo["amount"]) >= quantity and not exact):
          return utxo
    return None

  def find_utxo_multiple_exact(self, type, quantity, name=None, include_locked=False):
    print("Find UTXO Multiple Exact: {} {} {} Include Locks: {}".format(quantity, type, name, include_locked))
    return [utxo for utxo in self.get_utxos(type, name=name, include_locked=include_locked) if utxo["amount"] == quantity]

  def get_utxos(self, type, name=None, include_locked=False):
    results = []
    if type == "rvn":
      results = [utxo for utxo in self.utxos]
    elif type == "asset":
      results = [utxo for utxo in self.assets[name]["outpoints"]]
    else: #Use the type name itself
      results = [utxo for utxo in self.assets[type]["outpoints"]]
    if include_locked:
      return results
    else:
      return [utxo for utxo in results if not self.is_locked(utxo)]

  def find_utxo_set(self, type, quantity, mode="combine", name=None, include_locked=False):
    found_set = None
    total = 0
    

    sorted_set = sorted(self.get_utxos(type, name, include_locked=include_locked), key=lambda utxo: utxo["amount"])

    if mode == "combine":
      #Try to combine as many UTXO's as possible into a single Transaction
      #This raises your transaction fees slighty (more data) but is ultimately a good thing for the network
      #Don't need to do anything actualy b/c default behavior is to go smallest-to-largest
      #However, if we have a single, unrounded UTXO that is big enough. it's always more efficient to use that instead
      quick_check = self.find_utxo(type, quantity, name=name, include_locked=include_locked, exact=False, sort_utxo=True)
      if quick_check:
        #If we have a single UTXO big enough, just use it and get change. sort_utxo ensures we find the smallest first
        found_set = [quick_check]
        total = quick_check["amount"]
    elif mode == "minimize":
      #Minimize the number of UTXO's used, to reduce transaction fees
      #This minimizes transaction fees but
      quick_check = self.find_utxo(type, quantity, name=name, include_locked=include_locked, exact=False, sort_utxo=True)
      quick_check_2 = self.find_utxo(type, quantity, name=name, include_locked=include_locked, exact=False, skip_rounded=False, sort_utxo=True)
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
      print("{} UTXOs: {} Requested: {:.8g} Total: {:.8g} Change: {:.8g}".format(type, len(found_set), quantity, total, total - quantity))
      return (total, found_set)
    else:
      print("Not enough {} funds found. Requested: {:.8g} Total: {:.8g} Missing: {:.8g}".format(type, quantity, total, total-quantity))
      return (None, None)

  #check if a swap's utxo has been spent
  #if so then the swap has been executed!
  def swap_utxo_spent(self, utxo, in_mempool=True, check_cache=True):
    if check_cache:
      return self.search_utxo(utxo) == None #This will always go away immediately w/ mempool. so in_mempool doesnt work here
    else:
      (txid, vout) = split_utxo(utxo)
      return do_rpc("gettxout", txid=txid, n=vout, include_mempool=in_mempool) == None

  def search_utxo(self, utxo):
    (txid, vout) = split_utxo(utxo)
    for utxo in self.utxos:
      if utxo["txid"] == txid and utxo["vout"] == vout:
        return {"type": "rvn", "utxo": utxo}
    for asset_name in self.my_asset_names:
      for a_utxo in self.assets[asset_name]["outpoints"]:
        if a_utxo["txid"] == txid and a_utxo["vout"] == vout:
          return {"type": "asset", "utxo": a_utxo, "name": asset_name}
    return None

  def is_locked(self, utxo):
    for lock in self.locks:
      if lock["txid"] == utxo["txid"] and lock["vout"] == utxo["vout"]:
        return True
    return False

  def is_taken(self, utxo, ignore_locks=False):
    expected = join_utxo(utxo["txid"], utxo["vout"])
    if not ignore_locks:
      if sel.is_locked(utxo):
        return True
    for swap in self.swaps:
      if expected in swap.order_utxos:
        return True
    return False