from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path
from util import *
from config import *

def do_rpc(method, log_error=True, **kwargs):
  req = Request(method, **kwargs)
  try:
    resp = post(RPC_URL, json=req)
    if resp.status_code != 200:
      print("==>", end="")
      print(req)
      print("<== ERR:", end="")
      print(resp.text)
    return json.loads(resp.text)["result"]
  except:
    print("RPC Error")
    return None

def decode_full(txid):
  print("Query Full: {}".format(txid))
  resp = get(TX_QRY.format(txid))
  if resp.status_code != 200:
    print("Error fetching raw transaction")
  result = json.loads(resp.text)
  return result

def check_unlock(timeout = 10):
  phrase_test = do_rpc("help", command="walletpassphrase")
  #returns None if no password set
  if(phrase_test.startswith("walletpassphrase")):
    print("Unlocking Wallet for {}s".format(timeout))
    do_rpc("walletpassphrase", passphrase=RPC_UNLOCK_PHRASE, timeout=timeout)

def dup_transaction(tx):
  new_vin = []
  new_vout = {}
  for old_vin in tx["vin"]:
    new_vin.append({"txid": old_vin["txid"], "vout": old_vin["vout"], "sequence": old_vin["sequence"]})
  for old_vout in sorted(tx["vout"], key=lambda vo: vo["n"]):
    vout_script = old_vout["scriptPubKey"]
    vout_addr = vout_script["addresses"][0]
    if(vout_script["type"] == "transfer_asset"):
      new_vout[vout_addr] = make_transfer(vout_script["asset"]["name"], vout_script["asset"]["amount"])
    else:
      new_vout[vout_addr] = old_vout["value"]
  return new_vin, new_vout

def search_swap_tx(utxo):
  (txid, vout) = split_utxo(utxo)
  wallet_tx = do_rpc("listtransactions", account="", count=10)
  for tx in wallet_tx:
    details = do_rpc("getrawtransaction", txid=tx["txid"], verbose=True)
    for tx_vin in details["vin"]:
      if ("txid" in tx_vin and "vout" in tx_vin) and \
        (tx_vin["txid"] == txid and tx_vin["vout"] == vout):
        return tx_vin["txid"]
  print("Unable to find transaction for completed swap")
  return None #If we don't find it 10 blocks back, who KNOWS what happened to it