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

from app_instance import AppInstance

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
    (txid, vout) = split_utxo(self.utxo)
    vin = {"txid":txid, "vout":vout, "sequence":0}
    if self.type == "buy":
      vout = {self.destination: make_transfer(self.out_type, self.out_quantity)}
    elif self.type == "sell":
      vout = {self.destination: self.total_price()}
    elif self.type == "trade":
      vout = {self.destination: make_transfer(self.out_type, self.out_quantity)}

    check_unlock()

    raw_tx = do_rpc("createrawtransaction", inputs=[vin], outputs=vout)

    #TODO: Better user interaction here
    signed_raw = do_rpc("signrawtransaction", hexstring=raw_tx, prevtxs=None, privkeys=None, sighashtype="SINGLE|ANYONECANPAY")

    self.raw = signed_raw["hex"]
    return self.raw

  #This is run by Bob when he wants to complete an order
  def complete_order(self):
    final_vin = [{"txid":self.decoded["vin"]["txid"], "vout":self.decoded["vin"]["vout"], "sequence":self.decoded["vin"]["sequence"]}]
    final_vout = {self.destination:self.decoded["vout_data"]}

    tx_allowed = False
    tx_final = None

    send_rvn = 0
    recv_rvn = 0

    #Create our destination for assets
    #NOTE: self.destination is where our raven is going, not our destination for assets
    target_addr = AppInstance.wallet.addresses.get_single_address("order_destination")
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
      fund_asset_transaction_raw(do_rpc, self.out_type, self.out_quantity, final_vin, final_vout)
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
      fund_asset_transaction_raw(do_rpc, self.out_type, self.out_quantity, final_vin, final_vout)

    ##  Unkown order type
    else:
      raise Exception("Unkown swap type {}".format(self.type))

    #We only have a single output when buying (the rvn) so no need to generate an addr in that case.
    #Just use the supplied one
    rvn_addr = target_addr if self.type == "buy" else AppInstance.wallet.addresses.get_single_address("change")

    #Add needed ins/outs needed to handle the rvn disbalance in the transaction
    funded_finale = fund_transaction_final(do_rpc, send_rvn, recv_rvn, rvn_addr, final_vin, final_vout, [self.raw])
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
  def composite_transactions(swaps):
    total_inputs = {}
    total_outputs = {}
    canceled_assets = {}
    for swap in swaps:
      total_inputs[swap.in_type] = (total_inputs[swap.in_type] if swap.in_type in total_inputs else 0) + swap.in_quantity
      total_outputs[swap.out_type] = (total_outputs[swap.out_type] if swap.out_type in total_outputs else 0) + swap.out_quantity
    print("Sub-Total: In {} - Out {}".format(total_inputs, total_outputs))
    #These assets need to be supplied by us (outputs) but were also supplied (inputs)
    for dup_asset in [asset for asset in total_outputs.keys() if asset in total_inputs]:
      if total_inputs[dup_asset] >= total_outputs[dup_asset]:
        #More was provided than we need to supply, net credit
        total_inputs[dup_asset] -= total_outputs[dup_asset]
        canceled_assets[dup_asset] = total_outputs[dup_asset]
        del total_outputs[dup_asset]
        print("Net Credit {}x [{}]".format(total_inputs[dup_asset], dup_asset))
      elif total_inputs[dup_asset] < total_outputs[dup_asset]:
        #More was requested than supplied in inputs, net debit
        total_outputs[dup_asset] -= total_inputs[dup_asset]
        canceled_assets[dup_asset] = total_inputs[dup_asset]
        del total_inputs[dup_asset]
        print("Net Debit {}x [{}]".format(total_outputs[dup_asset], dup_asset))
    print("Total: In {} - Out {} (Cancelled: {})".format(total_inputs, total_outputs, canceled_assets))

    mega_tx_vins = []
    mega_tx_vouts = {}

    for swap in swaps:
      swap_decoded = do_rpc("decoderawtransaction", log_error=False, hexstring=swap.raw)
      if "SINGLE|ANYONECANPAY" not in swap_decoded["vin"][0]["scriptSig"]["asm"]:
        print("Transaction not signed with SINGLE|ANYONECANPAY")
        return None
      dup_transaction(swap_decoded, mega_tx_vins, mega_tx_vouts)

    print("Un-Funded Inputs: ", mega_tx_vins)
    print("Un-Funded Outputs: ", mega_tx_vouts)

    send_rvn = 0
    recv_rvn = 0

    #Fund all requested assets in the transaction
    for supply_asset in total_outputs.keys():
      if supply_asset == "rvn":
        send_rvn = total_outputs["rvn"]
      else:
        fund_asset_transaction_raw(do_rpc, supply_asset, total_outputs[supply_asset], mega_tx_vins, mega_tx_vouts)

    for recieve_asset in total_inputs.keys():
      if recieve_asset == "rvn":
        recv_rvn = total_inputs["rvn"]
      else:
        asset_addr = AppInstance.wallet.addresses.get_single_address("change")
        mega_tx_vouts[asset_addr] = make_transfer(recieve_asset, total_inputs[recieve_asset])


    print("Asset-Funded Inputs: ", mega_tx_vins)
    print("Asset-Funded Outputs: ", mega_tx_vouts)

    original_hexs = [swap.raw for swap in swaps]

    final_addr = AppInstance.wallet.addresses.get_single_address("order_destination")
    funded = fund_transaction_final(do_rpc, send_rvn, recv_rvn, final_addr, mega_tx_vins, mega_tx_vouts, original_hexs)

    if not funded:
      raise Exception("Funding error")

    
    #Build final funded raw transaction
    final_raw = do_rpc("createrawtransaction", inputs=mega_tx_vins, outputs=mega_tx_vouts)
    #Merge the signed tx from the original order
    combined_raw = final_raw
    for hex in original_hexs:
      print(hex)
      combined_raw = do_rpc("combinerawtransaction", txs=[combined_raw, hex])
      print(combined_raw)
    #Sign our inputs/outputs
    signed_res = do_rpc("signrawtransaction", hexstring=combined_raw)
    signed_hex = signed_res["hex"]
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
      print(combined_raw)
      print("Signed Raw")
      print(signed_res)
      #if combined_raw:
      #  print("Decoded")
      #  print(do_rpc("decoderawtransaction", hexstring=combined_raw))
      print("!!Error!!")
      raise Exception("Error Building TX")
    

  @staticmethod
  def decode_swap(raw_swap):
    parsed = do_rpc("decoderawtransaction", log_error=False, hexstring=raw_swap)
    if parsed:
      if len(parsed["vin"]) != 1 or len(parsed["vout"]) != 1:
        return (False, "Invalid Transaction. Has more than one vin/vout")
      if "SINGLE|ANYONECANPAY" not in parsed["vin"][0]["scriptSig"]["asm"]:
        return (False, "Transaction not signed with SINGLE|ANYONECANPAY")

      swap_vin = parsed["vin"][0]
      swap_vout = parsed["vout"][0]

      #Decode full here because we liekly don't have this transaction in our mempool
      #And we probably aren't runnin a full node
      vin_tx = decode_full(swap_vin["txid"])
      
      #If nothing comes back this is likely a testnet tx on mainnet of vice-versa
      if not vin_tx:
        return (False, "Unable to find transaction. Is this for the correct network?")

      src_vout = vin_tx["vout"][swap_vin["vout"]]
      in_asset = "asset" in src_vout["scriptPubKey"]
      out_asset = "asset" in swap_vout["scriptPubKey"]
      order_type = "unknown"

      if in_asset and out_asset:
        order_type = "trade"
      elif in_asset:
        order_type = "sell"
      elif out_asset:
        order_type = "buy"

      if order_type == "unknown":
        return (False, "Uknonwn trade type")

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

      return (True, SwapTransaction({
        "in_type": in_type,
        "out_type": out_type,
        "in_quantity": in_qty,
        "out_quantity": out_qty,
        "own": False,
        "utxo": join_utxo(swap_vin["txid"], str(swap_vin["vout"])),
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
      }))
      
    else:
      return (False, "Invalid TX")


from wallet_manager import fund_asset_transaction_raw, fund_transaction_final