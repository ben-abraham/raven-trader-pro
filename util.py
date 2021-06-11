from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import os, sys, getopt, argparse, json, time, getpass, os.path, datetime, shutil, base64, webbrowser, subprocess, logging

from ui.ui_prompt import *

def join_utxo(txid, n):
  return "{}-{}".format(txid, n)
  
def make_utxo(order):
  return "{}-{}".format(order["txid"], order["vout"])

def split_utxo(utxo):
  (txid, n) = utxo.split("-")
  return (txid, int(n))

def utxo_copy(vin):
  if "sequence" in vin:
    return { "txid": vin["txid"], "vout": int(vin["vout"]), "sequence": int(vin["sequence"]) }
  else:
    return { "txid": vin["txid"], "vout": int(vin["vout"]) }

def vout_to_utxo(vout, txid, n):
  if "scriptPubKey" in vout:
    if "asset" in vout["scriptPubKey"]:
      return {"txid": txid, "vout": n, "type": "asset", "amount": vout["scriptPubKey"]["asset"]["amount"], "asset": vout["scriptPubKey"]["asset"]["name"]}
    else:
      return {"txid": txid, "vout": n, "type": "rvn", "amount": vout["value"]}
  else:
    return {"txid": txid, "vout": n, "type": "unknown"}

def make_prefill(asset, quantity=1, unit_price=1):
  return { "asset": asset["name"], "quantity": quantity, "unit_price": unit_price }

#
#Helper function
#

def open_file(filename):
  logging.info("Opening system file for editing: {}".format(filename))
  if sys.platform == "win32":
    os.startfile(filename)
  else:
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.call([opener, filename])

def do_url(url):
  webbrowser.open(url)

def call_if_set(fn_call, *args):
  if fn_call != None:
    fn_call(*args)

def make_transfer(name, quantity):
  return {"transfer":{name:round(float(quantity), 8)}}

def backup_remove_file(file_path):
  (root, ext) = os.path.splitext(file_path)
  new_name = "old_{}_{}.{}".format(file_path, datetime.datetime.now().strftime('%Y%m%d%H%M%S'), ext) 
  logging.info("Discarding/moving file [{}] into backup location [{}]".format(file_path, new_name))

def ensure_directory(dir):
  if not os.path.exists(dir):
    os.makedirs(dir)

def load_json(path, hook, title, default=[]):
  if not os.path.isfile(path):
    #logging.info("No {} records.".format(title))
    return default
  fSwap = open(path, mode="r")
  swapJson = fSwap.read()
  fSwap.close()
  data = json.loads(swapJson, object_hook=hook)
  #logging.info("Loaded {} {} records from disk".format(len(data), title))
  return data

def save_json(path, data):
  dataJson = json.dumps(data, default=lambda o: o.__dict__, indent=2)
  fSwap = open(path, mode="w")
  fSwap.truncate()
  fSwap.write(dataJson)
  fSwap.flush()
  fSwap.close()

def init_list(items, hook):
  return [hook(item) for item in items]

def b64_to_hex(b64_str):
  d = base64.b64decode(b64_str)
  return ''.join(['{:02x}'.format(i) for i in d])

#
#Helper Classes
#

class QTwoLineRowWidget (QWidget):
  def __init__ (self, parent = None):
    super(QTwoLineRowWidget, self).__init__(parent)
    self.textQVBoxLayout = QVBoxLayout()
    self.textUpQLabel    = QLabel()
    self.textDownQLabel  = QLabel()
    self.textQVBoxLayout.addWidget(self.textUpQLabel)
    self.textQVBoxLayout.addWidget(self.textDownQLabel)
    self.allQHBoxLayout  = QHBoxLayout()
    self.iconQLabel      = QLabel()
    self.allQHBoxLayout.addWidget(self.iconQLabel, 0)
    self.allQHBoxLayout.addLayout(self.textQVBoxLayout, 1)
    self.setLayout(self.allQHBoxLayout)
   
  def update_swap(self):
    if self.swap.own: #If this is OUR trade, the default language can be used
      if self.swap.type == "buy":
        self.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
          "Buy", self.swap.quantity(), self.swap.asset(), self.swap.total_price(), self.swap.unit_price()))
      elif self.swap.type == "sell":
        self.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
          "Sell", self.swap.quantity(), self.swap.asset(), self.swap.total_price(), self.swap.unit_price()))
      elif self.swap.type == "trade":
        self.setTextUp("{} {:.8g}x [{}] for {:.8g} [{}] ({:.8g}x [{}] each)".format(
          "Trade", self.swap.total_price(), self.swap.in_type, self.swap.quantity(), self.swap.asset(), self.swap.unit_price(), self.swap.in_type))
    else: #If this is someone else's trade, then we need to invert the language
      #also all listed external orders are already executed, so past-tense
      if self.swap.type == "buy":
        self.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
          "Sold", self.swap.quantity(), self.swap.asset(), self.swap.total_price(), self.swap.unit_price()))
      elif self.swap.type == "sell":
        self.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
          "Bought", self.swap.quantity(), self.swap.asset(), self.swap.total_price(), self.swap.unit_price()))
      elif self.swap.type == "trade":
        self.setTextUp("{} {:.8g}x [{}] for {:.8g} [{}] ({:.8g}x [{}] each)".format(
          "Exchanged", self.swap.total_price(), self.swap.in_type, self.swap.quantity(), self.swap.asset(), self.swap.unit_price(), self.swap.in_type))

    if self.swap.state == "pending":
      self.setTextDown("Pending in mempool", "pending")
    elif self.swap.state == "completed":
      if not self.swap.own:
        self.setTextDown("Completed: {}".format(self.swap.txid), "confirmed")
      else:
        self.setTextDown("Executed: {}".format(self.swap.txid), "confirmed")
    elif self.swap.state == "removed":
      self.setTextDown("Removed")

  def update_trade(self):
    if self.trade.type == "buy":
      self.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
        "Buy", self.trade.out_quantity, self.trade.out_type, self.trade.in_quantity, self.trade.in_quantity / self.trade.out_quantity))
    elif self.trade.type == "sell":
      self.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
        "Sell", self.trade.in_quantity, self.trade.in_type, self.trade.out_quantity, self.trade.out_quantity / self.trade.in_quantity))
    elif self.trade.type == "trade":
      self.setTextUp("{} {:.8g}x [{}] for {:.8g} [{}] ({:.8g}x [{}] each)".format(
        "Trade", self.trade.in_quantity, self.trade.in_type, self.trade.out_quantity, self.trade.out_type, self.trade.in_quantity / self.trade.out_quantity, self.trade.in_type))
    
    qty_msg = "Ready: {}/{}".format(len(self.trade.order_utxos), self.trade.order_count)
    if self.trade.executed_count > 0:
      qty_msg = "{} [{} Executed]".format(qty_msg, self.trade.executed_count)
    if self.trade.missing_trades():
      qty_msg = "{} [{} Missing Trades]".format(qty_msg, self.trade.missing_trades())
    self.setTextDown(qty_msg)

  def update_asset(self):

    self.setTextUp("[{}] {:.8g}/{:.8g}".format(self.asset_data["name"], self.asset_data["available_balance"], self.asset_data["balance"]))

  @staticmethod
  def from_swap(swap, **kwargs):
    row = QTwoLineRowWidget()
    row.swap = swap
    row.update_swap()
    return row

  @staticmethod
  def from_trade(trade, **kwargs):
    row = QTwoLineRowWidget()
    row.trade = trade
    row.update_trade()
    return row

  @staticmethod
  def from_asset(asset_data):
    row = QTwoLineRowWidget()
    row.asset_data = asset_data
    row.update_asset()
    return row

  @staticmethod
  def from_vout(vout, ismine):
    row = QTwoLineRowWidget()
    row.vout = vout
    row.ismine = ismine
    
    spk = vout["scriptPubKey"]

    if("asset" in spk):
      row.setTextUp("{:.8g}x [{}]".format(float(spk["asset"]["amount"]),spk["asset"]["name"]))
    else:
      row.setTextUp("{:.8g} RVN".format(float(row.vout["value"])))
    
    if(ismine):
      row.setTextDown("** {}".format(spk["addresses"][0]))
    else:  
      row.setTextDown(spk["addresses"][0])

    return row

  def get_data(self):
    for data_prop in ["swap", "trade", "asset_data"]:
      if hasattr(self, data_prop):
        return getattr(self, data_prop)

  def refresh(self):
    if hasattr(self, "swap"):
      self.update_swap()
    elif hasattr(self, "trade"):
      self.update_trade()
    if hasattr(self, "asset_data"):
      self.update_asset()

  def setTextUp (self, text):
    self.textUpQLabel.setText(text)

  def setTextDown (self, text, status=None):
    self.textDownQLabel.setText(text)
    current_status = self.textDownQLabel.property("status")
    if status != current_status:
      self.textDownQLabel.setProperty("status", status)
      self.textDownQLabel.style().unpolish(self.textDownQLabel)
      self.textDownQLabel.style().polish(self.textDownQLabel)

  def setIcon (self, imagePath):
    self.iconQLabel.setPixmap(QPixmap(imagePath))
