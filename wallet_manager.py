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

from app_settings import AppSettings
from app_instance import AppInstance
from wallet_addresses import WalletAddresses

class WalletManager:

  def __init__ (self):
    super()
    self.waiting = [] #Waiting on confirmation
    self.addresses = WalletAddresses()
    self.trigger_cache = []
    self.on_swap_mempool = None
    self.on_swap_confirmed = None
    self.on_completed_mempool = None
    self.on_completed_confirmed = None
  
  def on_load(self):
    self.load_data()
    self.update_wallet()
    self.wallet_unlock_all()
    self.refresh_locks()

  def on_close(self):
    self.save_data()

#
# File I/O
#
  def load_data(self):
    #TODO: Replace all local member access with app_storage directly?
    self.swaps =     AppInstance.storage.swaps
    self.locks =     AppInstance.storage.locks
    self.history =   AppInstance.storage.history
    self.addresses.on_load()
    #TODO: Better way to handle post-wallet-load events
    self.check_missed_history()

  def save_data(self):
    #Needed?
    AppInstance.storage.swaps = self.swaps
    AppInstance.storage.locks = self.locks
    AppInstance.storage.history = self.history
    self.addresses.on_close()
    AppInstance.storage.save_data()

#
# Basic Operations
#

  def add_swap(self, swap_trade):
    self.swaps.append(swap_trade)

  def remove_swap(self, swap_trade):
    self.swaps.remove(swap_trade)
    for utxo in swap_trade.order_utxos:
      self.remove_lock(utxo=utxo)

  def add_completed(self, swap_transaction):
    if swap_transaction.utxo in [old_order.utxo for old_order in self.history]:
      print("Duplicate order add")
      return
    print("Adding to history...")
    self.history.append(swap_transaction)
    if swap_transaction.own:
      self.remove_lock(utxo=swap_transaction.utxo)

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

    self.available_balance = tuple(bal_avail)
    self.total_balance = tuple(bal_total)

  def rvn_balance(self):
    return self.available_balance[0]

  def asset_balance(self):
    return self.available_balance[2]

#
# Callbacks
#

  def __on_swap_mempool(self, transaction, trade):
    #TODO: Re-scan transaction to verify details of chain-executed trade
    trade.txid = transaction["txid"]
    trade.state = "pending"
    self.add_completed(trade)
    call_if_set(self.on_swap_mempool, transaction, trade)

  def __on_swap_confirmed(self, transaction, trade):
    trade.txid = transaction["txid"]
    trade.state = "completed"
    call_if_set(self.on_swap_confirmed, transaction, trade)

  def __on_completed_mempool(self, transaction, swap):
    swap.txid = transaction["txid"]
    swap.state = "pending"
    print(swap)
    self.add_completed(swap)
    call_if_set(self.on_completed_mempool, transaction, swap)

  def __on_completed_confirmed(self, transaction, swap):
    swap.txid = transaction["txid"]
    swap.state = "completed"
    call_if_set(self.on_completed_confirmed, transaction, swap)

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

  def swap_executed(self, swap, txid):
    self.add_waiting(txid, self.__on_completed_mempool, self.__on_completed_mempool, callback_data=swap)

  def num_waiting(self):
    return len(self.waiting)

  def add_waiting(self, txid, fnOnSeen=None, fnOnConfirm=None, callback_data=None):
    print("Waiting on txid: {}".format(txid))
    self.waiting.append((txid, fnOnSeen, fnOnConfirm, callback_data))

  def clear_waiting(self):
    self.waiting.clear()

  def check_waiting(self):
    for waiting in self.waiting:
      (txid, seen, confirm, callback_data) = waiting
      tx_data = do_rpc("getrawtransaction", txid=txid, verbose=True)
      if not tx_data:
        continue
      #TODO: Adjustable confirmations
      tx_confirmed = "confirmations" in tx_data and tx_data["confirmations"] >= 1
      
      if not tx_confirmed and txid not in self.trigger_cache:
        print("Waiting txid {} confirmed in mempool.".format(txid))
        self.trigger_cache.append(txid)
        call_if_set(seen, tx_data, callback_data)
      elif tx_confirmed and txid in self.trigger_cache:
        print("Waiting txid {} fully confirmed.".format(txid))
        self.trigger_cache.remove(txid)
        self.waiting.remove(waiting)
        call_if_set(confirm, tx_data, callback_data)
      elif tx_confirmed and txid not in self.trigger_cache:
        print("Missed memcache for txid {}, direct to confirm.".format(txid))
        self.waiting.remove(waiting)
        call_if_set(seen, tx_data, callback_data)
        call_if_set(confirm, tx_data, callback_data)
      
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
      wallet_utxos = []
      for lock in wallet_locks:
        txout = do_rpc("gettxout", txid=lock["txid"], n=int(lock["vout"]), include_mempool=True)
        if txout:
          utxo = vout_to_utxo(txout, lock["txid"], int(lock["vout"]))
          wallet_utxos.append(make_utxo(lock))
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
    self.trigger_cache = []
    self.my_asset_names = []
    self.total_balance = (0,0,0)
    self.available_balance = (0,0,0)
    self.clear_waiting()

  def update_wallet(self):
    self.check_waiting()
    #Locked UTXO's are excluded from the list command
    self.utxos = do_rpc("listunspent")
      
    #Pull list of assets for selecting
    self.assets = do_rpc("listmyassets", asset="", verbose=True)

    #Load details of wallet-locked transactions, inserted into self.utxos/assets
    self.load_wallet_locked()

    removed_orders = self.search_completed()
    for (trade, utxo) in removed_orders:
      finished_order = trade.order_completed(self, utxo)
      transaction = search_swap_tx(utxo)
      if transaction:
        txid = transaction["txid"]
        print("Order Completed: TXID {}".format(txid))
        self.add_waiting(txid, self.__on_swap_mempool, self.__on_swap_confirmed, callback_data=finished_order)
      else:
        print("Order executed on unknown transaction")

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
    print("Locking UTXO {}-{}".format(txid, vout))
    txout = do_rpc("gettxout", txid=txid, n=vout, include_mempool=True) #True means this will be None when spent in mempool
    if txout:
      utxo = vout_to_utxo(txout, txid, vout)
      self.locks.append(utxo)
      if AppSettings.instance.lock_mode():
        self.wallet_lock_single(txid, vout)

  def remove_lock(self, txid=None, vout=None, utxo=None):
    if utxo != None and txid == None and vout == None:
      (txid, vout) = split_utxo(utxo)
    found = False
    for lock in self.locks:
      if txid == lock["txid"] and vout == lock["vout"]:
        self.locks.remove(lock)
        found = True
    if not found:
      return
    print("Unlocking UTXO {}-{}".format(txid, vout))
    #in wallet-lock mode we need to return these to the wallet
    if AppSettings.instance.lock_mode():
      self.wallet_lock_single(txid, vout, lock=False)

  def refresh_locks(self, clear=False):
    if clear:
      self.wallet_unlock_all()
      self.locks = []
    for swap in self.swaps:
      for utxo in swap.order_utxos:
        self.add_lock(utxo=utxo)
    if AppSettings.instance.lock_mode():
      self.wallet_lock_all_swaps()

  def lock_quantity(self, type):
    if type == "rvn":
      return sum([float(lock["amount"]) for lock in self.locks if lock["type"] == "rvn"])
    else:
      return sum([float(lock["amount"]) for lock in self.locks if lock["type"] == "asset" and lock["name"] == type])

  def check_missed_history(self):
    #Re-Add listeners for incomplete orders, should be fully posted, but add events so full sequence can happen
    for pending_order in [hist_order for hist_order in self.history if hist_order.state != "completed"]:
      if pending_order.utxo not in self.trigger_cache:
        swap_tx = search_swap_tx(pending_order.utxo)
        if swap_tx:
          if pending_order.own:
            self.add_waiting(swap_tx["txid"], self.__on_swap_mempool, self.__on_swap_confirmed, pending_order)
          else:
            self.add_waiting(swap_tx["txid"], self.__on_completed_mempool, self.__on_completed_confirmed, pending_order)
        else:
          print("Failed to find transaction for presumably completed UTXO {}".format(pending_order.utxo))

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
      txout = do_rpc("gettxout", txid=txid, n=vout, include_mempool=in_mempool)
      return txout == None

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


#
#Chain helper functions
#

#2 hex chars = 1 byte, 0.01 RVN/kb feerate
def calculate_fee(transaction_hex):
  return calculated_fee_from_size(len(transaction_hex) / 2)

def calculated_fee_from_size(size):
  return AppSettings.instance.fee_rate() * (size / 1024)

#TransactionOverhead         = 12             // 4 version, 2 segwit flag, 1 vin, 1 vout, 4 lock time
#InputSize                   = 148            // 4 prev index, 32 prev hash, 4 sequence, 1 script size, ~107 script witness
#OutputOverhead              = 9              // 8 value, 1 script size
#P2PKHScriptPubkeySize       = 25             // P2PKH size
#P2PKHReplayScriptPubkeySize = 63             // P2PKH size with replay protection
def calculate_size(vins, vouts):
  return 12 + (len(vins) * 148) + (len(vouts) * (9 + 25))

def fund_asset_transaction_raw(fn_rpc, asset_name, quantity, vins, vouts, asset_change_addr=None):
  #Search for enough asset UTXOs
  (asset_utxo_total, asset_utxo_set) = AppInstance.wallet.find_utxo_set("asset", quantity, name=asset_name, include_locked=True)
  #Add our asset input(s)
  for asset_utxo in asset_utxo_set:
    vins.append({"txid":asset_utxo["txid"], "vout":asset_utxo["vout"]})

  if not asset_change_addr:
    asset_change_addr = AppInstance.wallet.addresses.get_single_address("asset_change")

  #Add asset change if needed
  if(asset_utxo_total > quantity):
    #TODO: Send change to address the asset UTXO was originally sent to
    print("Asset change being sent to {}".format(asset_change_addr))
    vouts[asset_change_addr] = make_transfer(asset_name, asset_utxo_total - quantity)

def fund_transaction_final(fn_rpc, send_rvn, recv_rvn, target_addr, vins, vouts, original_txs):
  cost = send_rvn #Cost represents rvn sent to the counterparty, since we adjust send_rvn later
  
  #If this is a swap, we need to add pseduo-funds for fee calc
  if recv_rvn == 0 and send_rvn == 0:
    #Add dummy output for fee calc
    vouts[target_addr] = round(sum([calculate_fee(tx) for tx in original_txs]) * 4, 8)
    
  if recv_rvn > 0 and send_rvn == 0:
    #If we are not supplying rvn, but expecting it, we need to subtract fees from that only
    #So add our output at full value first
    vouts[target_addr] = round(recv_rvn, 8)

  #Make an initial guess on fees, quadruple should be enough to estimate actual fee post-sign
  fee_guess = calculated_fee_from_size(calculate_size(vins, vouts)) * 4
  send_rvn += fee_guess #add it to the amount required in the UTXO set

  print("Funding Raw Transaction. Send: {:.8g} RVN. Get: {:.8g} RVN".format(send_rvn, recv_rvn))
  
  if send_rvn > 0:
    #Determine a valid UTXO set that completes this transaction
    (utxo_total, utxo_set) = AppInstance.wallet.find_utxo_set("rvn", send_rvn)
    if utxo_set is None:
      show_error("Not enough UTXOs", "Unable to find a valid UTXO set for {:.8g} RVN".format(send_rvn))
      return False
    send_rvn = utxo_total #Update for the amount we actually supplied
    for utxo in utxo_set:
      vins.append({"txid":utxo["txid"],"vout":utxo["vout"]})

  #Then build and sign raw to estimate fees
  sizing_raw = fn_rpc("createrawtransaction", inputs=vins, outputs=vouts)
  sizing_raw = fn_rpc("combinerawtransaction", txs=[sizing_raw] + original_txs)
  sizing_signed = fn_rpc("signrawtransaction", hexstring=sizing_raw) #Need to calculate fees against signed message
  fee_rvn = calculate_fee(sizing_signed["hex"])
  out_rvn = (send_rvn + recv_rvn) - cost - fee_rvn
  vouts[target_addr] = round(out_rvn, 8)

  print("Funding result: Send: {:.8g} Recv: {:.8g} Fee: {:.8g} Change: {:.8g}".format(send_rvn, recv_rvn, fee_rvn, out_rvn))

  return True



from swap_transaction import SwapTransaction
from swap_trade import SwapTrade