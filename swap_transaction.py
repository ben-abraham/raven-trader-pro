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

class SwapTransaction():
  def __init__(self, dict, decoded=None):
    self.decoded = decoded
    vars(self).update(dict)

  def totalPrice(self):
    return self.quantity * self.unit_price

  #This is run by Alice when she wants to create an order
  def sign_partial(self):
    utxo_parts = self.utxo.split("|")
    vin = {"txid":utxo_parts[0], "vout":int(utxo_parts[1]), "sequence":0}
    vout = {self.destination: make_transfer(self.asset, self.quantity)} if self.type == "buy"\
      else {self.destination: self.totalPrice()}

    check_unlock()

    raw_tx = do_rpc("createrawtransaction", inputs=[vin], outputs=vout)

    #TODO: Better user interaction here
    print("Signing Partial Transaction")
    signed_raw = do_rpc("signrawtransaction", hexstring=raw_tx, prevtxs=None, privkeys=None, sighashtype="SINGLE|ANYONECANPAY")
    print("Done!")

    self.raw = signed_raw["hex"]
    return self.raw

  def consutrct_invalidate_tx(self, swap_storage, new_destination=None):
    self_utxo = swap_storage.search_utxo(self.utxo)
    print(self_utxo)
    lock_vin = [{"txid":self_utxo["utxo"]["txid"],"vout":self_utxo["utxo"]["vout"]}]
    lock_vout = None
    out_addr = new_destination if new_destination else self.destination

    #Make sure to use local properties here in case we updated before invalidating (changed order size/amount)
    if self_utxo["type"] == "rvn":
      lock_vout = { out_addr: self.totalPrice() }
    elif self_utxo["type"] == "asset": #Sell order means we need to invalide asset utxo
      lock_vout = { out_addr: make_transfer(self_utxo["name"], self.quantity) }

    new_tx = do_rpc("createrawtransaction", inputs=lock_vin, outputs=lock_vout)
    funded_tx = do_rpc("fundrawtransaction", hexstring=new_tx, options={"changePosition": 1})
    signed_raw = do_rpc("signrawtransaction", hexstring=funded_tx["hex"])

    return signed_raw

  #This is run by Bob when he wants to complete an order
  def complete_order(self, swap_storage):
    final_vin = [{"txid":self.decoded["vin"]["txid"], "vout":self.decoded["vin"]["vout"], "sequence":self.decoded["vin"]["sequence"]}]
    final_vout = {self.destination:self.decoded["vout_data"]}

    tx_allowed = False
    tx_final = None

    #Check for unlock here and for extended duration because the fee checks are jenky and can take time
    check_unlock(240)

    if self.type == "sell":
      #Sale order means WE are purchasing
      print("You are purchasing {} x [{}] for {} RVN".format(self.quantity, self.asset, self.totalPrice()))

      #Add our destination for assets
      #NOTE: self.destination is where our raven is going, not our destination for assets
      #hence the call to getnewaddress. Should support explicitly setting from the user
      target_addr = do_rpc("getnewaddress")
      print("Assets are being sent to {}".format(target_addr))
      final_vout[target_addr] = make_transfer(self.asset, self.quantity)

      quick_fee = 2 * (0.01 * len(self.raw) / 2/ 1024) #Double the cost of the 1vin:1vout should be good enough to find a utxo set
      change_addr = do_rpc("getnewaddress")
      print("Change is being sent to {}".format(change_addr))
      final_vout[change_addr] = round(quick_fee, 8)

      utxo_set = swap_storage.find_utxo_set("rvn", self.totalPrice() + quick_fee)
      for utxo in utxo_set:
        final_vin.append({"txid":utxo["txid"],"vout":utxo["vout"]})

      #Build final combined raw transaction
      final_raw = do_rpc("createrawtransaction", inputs=final_vin, outputs=final_vout)

      #Fund the transaction, this will cover both the purchase debit and any fees
#      funded_tx = do_rpc("fundrawtransaction", hexstring=final_raw, options={'changePosition':1})

      funded_dec = do_rpc("decoderawtransaction", hexstring=final_raw)#funded_tx["hex"])
      funded_vin, funded_vout = dup_transaction(funded_dec)
      vout_keys = [*funded_vout.keys()]

      estimated_fee = 0.01 * len(final_raw) / 2 / 1024 #2 hex chars = 1 byte

      calculated_change = funded_vout[change_addr]
      fee_test = calculated_change - estimated_fee

      print("Funded TX")
      print(final_raw)

      #Jenky AF, no great way to estimate raw fee from rpc, so lower and test in mempool until good
      while fee_test > 0:
        funded_vout[change_addr] = round(fee_test, 8)

        dup_funded = do_rpc("createrawtransaction", inputs=funded_vin, outputs=funded_vout)

        #Merge the signed tx from the original order
        combined_raw = do_rpc("combinerawtransaction", txs=[dup_funded, self.raw])

        #Sign the final transaction
        signed_final = do_rpc("signrawtransaction", hexstring=combined_raw)
        signed_hex = signed_final["hex"]
        
        mem_accept = do_rpc("testmempoolaccept", rawtxs=[signed_hex])

        if(mem_accept and mem_accept[0]["allowed"]):
          print("Accepted to mempool!")
          tx_allowed = True
          tx_final = signed_hex
          break
        elif(mem_accept and mem_accept[0]["reject-reason"]=="66: min relay fee not met"):
          fee_test -= 0.0001
        else:
          print(mem_accept)
          print("Raw")
          print(combined_raw)
          print("Signed")
          print(signed_final)
          print("!!Error!!")
          break
    elif self.type == "buy":
      #Buy order means WE are selling
      print("You are selling {} x [{}] for {} RVN".format(self.quantity, self.asset, self.totalPrice()))
      
      #Search for valid UTXO, no need for exact match
      asset_utxo = swap_storage.find_utxo("asset", self.quantity, name=self.asset, exact=False, skip_locks=True)
      if(not asset_utxo):
        print("Unable to find a single UTXO for purchasing. Does not combine automatically yet")
        exit()

      #Add our asset input
      final_vin.append({"txid":asset_utxo["txid"], "vout":asset_utxo["vout"]})

      #NOTE: self.destination is where the assets are going, not our wallet
      #hence the call to getnewaddress. Should support explicitly setting from the user
      target_addr = do_rpc("getnewaddress")
      print("Funds are being sent to {}".format(target_addr))

      #Add asset change if needed
      if(asset_utxo["amount"] > self.quantity):
        asset_change_addr = do_rpc("getnewaddress")
        print("Asset change being sent to {}".format(asset_change_addr))
        final_vout[asset_change_addr] = make_transfer(self.asset, asset_utxo["amount"] - self.quantity)
      
      final_vout[target_addr] = 0

      print("Final Vin: ", final_vin)
      print("Final Vout: ", final_vout)
        
      test_create = do_rpc("createrawtransaction", inputs=final_vin, outputs=final_vout)
      estimated_fee = 0.01 * len(test_create) / 2 / 1024 #2 hex chars = 1 byte

      fee_test = float(self.decoded["src_vout"]["value"]) - estimated_fee

      #Jenky AF, no great way to estimate raw fee from rpc, so lower and test in mempool until good
      while fee_test > 0:
        final_vout[target_addr] = round(fee_test, 8)

        #Build final combined raw transaction
        final_raw = do_rpc("createrawtransaction", inputs=final_vin, outputs=final_vout)
        
        #Merge the signed tx from the original order
        combined_raw = do_rpc("combinerawtransaction", txs=[final_raw, self.raw])
        
        #Sign our part with our keys
        signed_raw = do_rpc("signrawtransaction", hexstring=combined_raw)
        signed_hex = signed_raw["hex"]

        mem_accept = do_rpc("testmempoolaccept", rawtxs=[signed_hex])

        if(mem_accept and mem_accept[0]["allowed"]):
          print("Accepted to mempool!")
          tx_allowed = True
          tx_final = signed_hex
          break
        elif(mem_accept and mem_accept[0]["reject-reason"]=="66: min relay fee not met"):
          fee_test -= 0.0001
        else:
          print(mem_accept)
          print("Test Create")
          print(test_create)
          print("Final Raw")
          print(final_raw)
          print("!!Error!!")
          break

    #remove this so it doesn't get encoded to json later
    del(self.decoded)
    return tx_final
    
  @staticmethod
  def decode_swap(raw_swap):
    parsed = do_rpc("decoderawtransaction", log_error=False, hexstring=raw_swap)
    if parsed:
      if len(parsed["vin"]) != 1 or len(parsed["vout"]) != 1:
        print("Invalid Transaction. Has more than one vin/vout")
        return None
      if "SINGLE|ANYONECANPAY" not in parsed["vin"][0]["scriptSig"]["asm"]:
        print("Transaction not signed with SINGLE|ANYONECANPAY")
        return None

      swap_vin = parsed["vin"][0]
      swap_vout = parsed["vout"][0]

      order_type = "buy" if swap_vout["scriptPubKey"]["type"] == "transfer_asset" else "sell"
      #Decode full here because we liekly don't have this transaction in our mempool
      #And we probably aren't runnin a full node
      vin_tx = decode_full(swap_vin["txid"])
      
      #If nothing comes back this is likely a testnet tx on mainnet of vice-versa
      if not vin_tx:
        print("Unable to find transaction. Is this for the correct network?")
        return None

      src_vout = vin_tx["vout"][swap_vin["vout"]]
      
      #Pull asset data based on order type
      if order_type == "sell":
        vout_data = swap_vout["value"]
        asset_data = src_vout["scriptPubKey"]["asset"]
        total_price = vout_data
      else:
        asset_data = swap_vout["scriptPubKey"]["asset"]
        vout_data = make_transfer(asset_data["name"], asset_data["amount"])
        total_price = src_vout["value"]

      unit_price = float(total_price) / float(asset_data["amount"])

      return SwapTransaction({
        "asset": asset_data['name'], 
        "own": False,
        "quantity": float(asset_data['amount']),
        "unit_price": unit_price,
        "utxo": swap_vin["txid"] + "|" + str(swap_vin["vout"]),
        "destination": swap_vout["scriptPubKey"]["addresses"][0],
        "state": "new",
        "type": order_type,
        "raw": raw_swap,
        "txid": ""
      },{
        "vin": swap_vin,
        "vout": swap_vout,
        "src_vout": src_vout,
        "vout_data": vout_data,
        "from_tx": vin_tx
      })
      
    else:
      print("Invalid TX")
      return None