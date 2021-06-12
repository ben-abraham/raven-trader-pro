from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic
from ui.ui_prompt import *

import sys, getopt, argparse, json, time, getpass, os, os.path, webbrowser, logging
from util import *


def test_rpc_status(first_launch=False):
  rpc = AppInstance.settings.rpc_details()
  if requires_unlock() and not rpc["unlock"]:
    show_error("Unlock phrase required.", "An unlock phrase has been set on this wallet, \r\n"+
    "but has not been configured in the settings for Raven-Trader-Pro.",
    "Settings file is located at: '{}'\r\n".format(AppInstance.settings.get_path()))
    return False
  
  #Then do a basic test of RPC, also can check it is synced here
  chain_info = do_rpc("getblockchaininfo", log_error=False)
  #If the headers and blocks are not within 5 of each other,
  #then the chain is likely still syncing
  chain_updated = False if not chain_info else\
    (chain_info["headers"] - chain_info["blocks"]) < 5
  
  if chain_info and chain_updated:
    #Determine if we are on testnet, and write back to settings.
    AppInstance.settings.rpc_set_testnet(chain_info["chain"] == "test")
    return True
  elif first_launch:
    open_settings =  show_prompt("First Launch Detected", 
    "First application launch detected.\r\n"+
    "Settings file is located at '{}'\r\n".format(AppInstance.settings.get_path())+
    "Would you like to open the settings file?")
    if open_settings == QMessageBox.Yes:
      open_file(AppInstance.settings.get_path())
  elif chain_info:
    show_error("Sync Error", 
    "Server appears to not be fully synchronized. Must be at the latest tip to continue.",
    "Network: {}\r\nCurrent Headers: {}\r\nCurrent Blocks: {}".format(chain_info["chain"], chain_info["headers"], chain_info["blocks"]))
  else:
    show_error("Error connecting", 
    "Error connecting to RPC server.\r\n{}".format(AppInstance.settings.rpc_url()), 
    "Settings file is located at: '{}'\r\n".format(AppInstance.settings.get_path())+
    "Close app when editing settings file!\r\n\r\n"+
    "Make sure the following configuration variables are in your raven.conf file"+
    "\r\n\r\nserver=1\r\nrpcuser={}\r\nrpcpassword={}".format(AppInstance.settings.rpc_details()["user"], AppInstance.settings.rpc_details()["password"]))
  return False

def do_rpc(method, log_error=True, **kwargs):
  req = Request(method, **kwargs)
  try:
    url = AppInstance.settings.rpc_url()
    resp = post(url, json=req, timeout=10)
    if resp.status_code != 200 and log_error:
      logging.error("RPC ==> {}".format(req))
      logging.error("RPC <== {}".format(resp.text))
    if resp.status_code != 200:
      return None
    return json.loads(resp.text)["result"]
  except TimeoutError:
    if log_error:
      #Any RPC timeout errors are totally fatal
      logging.error("RPC Timeout")
      AppInstance.on_exit()
      show_error("RPC Timeout", "Timeout contacting RPC")
      exit(-1)
      return None
    else:
      return None
  except Exception as ex:
    logging.error(ex)
    return None

def decode_full(txid):
  local_decode = do_rpc("getrawtransaction", log_error=False, txid=txid, verbose=True)
  if local_decode:
    result = local_decode
  else:
    rpc = AppInstance.settings.rpc_details()
    #TODO: Better way of handling full decode
    tx_url = "https://rvnt.cryptoscope.io/api/getrawtransaction/?txid={}&decode=1" if rpc["testnet"]\
      else "https://rvn.cryptoscope.io/api/getrawtransaction/?txid={}&decode=1"
    logging.info("Query Full: {}".format(tx_url.format(txid)))
    resp = get(tx_url.format(txid))
    if resp.status_code != 200:
      logging.info("Error fetching raw transaction")
    result = json.loads(resp.text)
  return result

def requires_unlock():
  #returns None if no password set
  phrase_test = do_rpc("help", command="walletpassphrase")
  return phrase_test and phrase_test.startswith("walletpassphrase")

def check_unlock(timeout = 10):
  rpc = AppInstance.settings.rpc_details()
  if requires_unlock():
    logging.info("Unlocking Wallet for {}s".format(timeout))
    do_rpc("walletpassphrase", passphrase=rpc["unlock"], timeout=timeout)

def dup_transaction(tx, vins=[], vouts={}):
  for old_vin in tx["vin"]:
    vins.append({"txid": old_vin["txid"], "vout": old_vin["vout"], "sequence": old_vin["sequence"]})
  for old_vout in sorted(tx["vout"], key=lambda vo: vo["n"]):
    vout_script = old_vout["scriptPubKey"]
    vout_addr = vout_script["addresses"][0]
    if("asset" in vout_script):
      vouts[vout_addr] = make_transfer(vout_script["asset"]["name"], vout_script["asset"]["amount"])
    else:
      vouts[vout_addr] = old_vout["value"]
  return vins, vouts

def search_swap_tx(utxo):
  (txid, vout) = split_utxo(utxo)
  wallet_tx = do_rpc("listtransactions", account="", count=10)
  for tx in wallet_tx:
    details = do_rpc("getrawtransaction", txid=tx["txid"], verbose=True)
    for tx_vin in details["vin"]:
      if ("txid" in tx_vin and "vout" in tx_vin) and \
        (tx_vin["txid"] == txid and tx_vin["vout"] == vout):
        return tx
  logging.info("Unable to find transaction for completed swap")
  return None #If we don't find it 10 blocks back, who KNOWS what happened to it

def asset_details(asset_name):
  asset_name = asset_name.replace("!", "")
  admin = False
  if(asset_name[-1:] == "!"):
    admin = True
    asset_name = asset_name[:-1]#Take all except !
  details = do_rpc("getassetdata", asset_name=asset_name)
  return (admin, details)

  
from app_instance import AppInstance