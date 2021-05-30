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

  #This is run by Alice when she wants to create an order
  def sign_partial(self):
    utxo_parts = self.utxo.split("|")
    vin = {"txid":utxo_parts[0], "vout":int(utxo_parts[1]), "sequence":0}
    if self.type == "buy":
      vout = {self.destination: make_transfer(self.out_type, self.out_quantity)}
    elif self.type == "sell":
      vout = {self.destination: self.total_price()}
    elif self.type == "trade":
      vout = {self.destination: make_transfer(self.out_type, self.out_quantity)}

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
      lock_vout = { out_addr: self.total_price() }
    elif self_utxo["type"] == "asset": #Sell order means we need to invalide asset utxo
      lock_vout = { out_addr: make_transfer(self_utxo["name"], self.in_quantity) }

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

    send_rvn = 0
    recv_rvn = 0

    #Create our destination for assets
    #NOTE: self.destination is where our raven is going, not our destination for assets
    #hence the call to getnewaddress. Should support explicitly setting from the user
    target_addr = do_rpc("getnewaddress")
    print("Output is being sent to {}".format(target_addr))


    #Unlock for signing during fee calc + sending
    check_unlock(10)

    ##
    ##  Complete sell Orders (we are buying an asset with rvn)
    ##
    if self.type == "sell":
      print("You are purchasing {} x [{}] for {} RVN".format(self.in_quantity, self.asset(), self.total_price()))

      #Send output assets to target_addr
      final_vout[target_addr] = make_transfer(self.asset(), self.quantity())
      #This much rvn must be supplied at the end
      send_rvn = self.total_price()

    ##
    ##  Complete buy orders (we are selling an asset for rvn)
    ##
    elif self.type == "buy":
      #Buy order means WE are selling, We need to provide assets
      print("You are selling {} x [{}] for {} RVN"\
        .format(self.out_quantity, self.asset(), self.total_price()))
      
      #Add needed asset inputs
      fund_asset_transaction_raw(swap_storage, do_rpc, self.out_type, self.out_quantity, final_vin, final_vout)
      #Designate how much rvn we expect to get      
      recv_rvn = self.total_price()
      

    ##
    ##  Complete trade orders (We are exchange assets for assets)
    ##
    elif self.type == "trade":
      #Trade order means WE are providing and reciving assets
      print("You are trading {}x of YOUR [{}] for {}x of THEIR [{}]"\
        .format(self.out_quantity, self.out_type, self.in_quantity, self.in_type))
      
      #Send output assets to target_addr
      final_vout[target_addr] = make_transfer(self.in_type, self.in_quantity)
      #Add needed asset inputs
      fund_asset_transaction_raw(swap_storage, do_rpc, self.out_type, self.out_quantity, final_vin, final_vout)

    ##  Unkown order type
    else:
      raise Exception("Unkown swap type {}".format(self.type))

    #We only have a single output when buying (the rvn) so no need to generate an addr in that case.
    #Just use the supplied one
    rvn_addr = target_addr if self.type == "buy" else do_rpc("getnewaddress")

    #Add needed ins/outs needed to handle the rvn disbalance in the transaction
    funded_finale = fund_transaction_final(swap_storage, do_rpc, send_rvn, recv_rvn, rvn_addr, final_vin, final_vout, self.raw)
    if not funded_finale:
      raise Exception("Funding raw transaction failed")

    #Build final funded raw transaction
    final_raw = do_rpc("createrawtransaction", inputs=final_vin, outputs=final_vout)
    #Merge the signed tx from the original order
    combined_raw = do_rpc("combinerawtransaction", txs=[final_raw, self.raw])
    #Sign our inputs/outputs
    signed_hex = do_rpc("signrawtransaction", hexstring=combined_raw)["hex"]
    #Finally, Test mempool acceptance
    mem_accept = do_rpc("testmempoolaccept", rawtxs=[signed_hex])

    if(mem_accept and mem_accept[0]["allowed"]):
      print("Accepted to mempool!")
      tx_allowed = True
      tx_final = signed_hex
    elif(mem_accept and mem_accept[0]["reject-reason"]=="66: min relay fee not met"):
      print("Min fee not met")
      #raise Exception("Fee Error")
      tx_allowed = True
      tx_final = signed_hex
    else:
      print(mem_accept)
      print("Final Raw")
      print(final_raw)
      if final_raw:
        print("Decoded")
        print(do_rpc("decoderawtransaction", hexstring=final_raw))
      print("!!Error!!")
      raise Exception("Error Building TX")

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

      #Decode full here because we liekly don't have this transaction in our mempool
      #And we probably aren't runnin a full node
      vin_tx = decode_full(swap_vin["txid"])
      
      #If nothing comes back this is likely a testnet tx on mainnet of vice-versa
      if not vin_tx:
        print("Unable to find transaction. Is this for the correct network?")
        return None

      src_vout = vin_tx["vout"][swap_vin["vout"]]
      in_type = src_vout["scriptPubKey"]["type"]
      out_type = swap_vout["scriptPubKey"]["type"]
      order_type = "unknown"

      print("In: {}, Out: {}".format(in_type, out_type))

      if in_type == "transfer_asset" and out_type == "transfer_asset":
        order_type = "trade"
      elif in_type == "transfer_asset":
        order_type = "sell"
      elif out_type == "transfer_asset":
        order_type = "buy"

      if order_type == "unknown":
        raise Exception("Uknonwn trade type")

      in_type = ""
      out_type = ""
      in_qty = 0
      out_qty = 0

      #Pull asset data based on order type
      if order_type == "buy":
        asset_data = swap_vout["scriptPubKey"]["asset"]
        vout_data = make_transfer(asset_data["name"], asset_data["amount"])

        in_type = "rvn"
        in_qty = src_vout["value"]
        out_type = asset_data["name"]
        out_qty = asset_data["amount"]
      elif order_type == "sell":
        asset_data = src_vout["scriptPubKey"]["asset"]
        vout_data = swap_vout["value"]

        in_type = asset_data["name"]
        in_qty = asset_data["amount"]
        out_type = "rvn"
        out_qty = swap_vout["value"]
      elif order_type == "trade":
        asset_data = swap_vout["scriptPubKey"]["asset"]
        vout_data = make_transfer(asset_data["name"], asset_data["amount"])
        
        in_type = src_vout["scriptPubKey"]["asset"]["name"]
        in_qty = src_vout["scriptPubKey"]["asset"]["amount"]
        out_type = swap_vout["scriptPubKey"]["asset"]["name"]
        out_qty = swap_vout["scriptPubKey"]["asset"]["amount"]

      return SwapTransaction({
        "in_type": in_type,
        "out_type": out_type,
        "in_quantity": in_qty,
        "out_quantity": out_qty,
        "own": False,
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