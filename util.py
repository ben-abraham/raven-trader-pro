from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path, datetime, shutil
from config import *

#
#Chain helper functions
#

#2 hex chars = 1 byte, 0.01 RVN/kb feerate
def calculate_fee(transaction_hex):
  num_kb = len(transaction_hex) / 2 / 1024
  fee = 0.0125 * num_kb
  #print("{} bytes => {} RVN".format(num_kb * 1024, fee))
  return fee

def fund_asset_transaction_raw(swap_storage, fn_rpc, asset_name, quantity, vins, vouts):
  #Search for enough asset UTXOs
  (asset_utxo_total, asset_utxo_set) = swap_storage.find_utxo_set("asset", quantity, name=asset_name, skip_locks=True)
  #Add our asset input(s)
  for asset_utxo in asset_utxo_set:
    vins.append({"txid":asset_utxo["txid"], "vout":asset_utxo["vout"]})

  #Add asset change if needed
  if(asset_utxo_total > quantity):
    #TODO: Send change to address the asset UTXO was originally sent to
    asset_change_addr = fn_rpc("getnewaddress") #cheat to get rpc in this scope
    print("Asset change being sent to {}".format(asset_change_addr))
    vouts[asset_change_addr] = make_transfer(asset_name, asset_utxo_total - quantity)

def fund_transaction_final(swap_storage, fn_rpc, send_rvn, recv_rvn, target_addr, vins, vouts, original_tx):
  cost = send_rvn #Cost represents rvn sent to the counterparty, since we adjust send_rvn later
  
  #If this is a swap, we need to add pseduo-funds for fee calc
  if recv_rvn == 0 and send_rvn == 0:
    #Add dummy output for fee calc
    vouts[target_addr] = round(calculate_fee(original_tx) * 4, 8)
    #Test sizing for fees, overkill to actually sign but :shrug:
    sizing_raw = fn_rpc("createrawtransaction", inputs=vins, outputs=vouts)
    send_rvn = calculate_fee(sizing_raw) * 4 #Quadruple fee should be enough to estimate actual fee
    
  if recv_rvn > 0 and send_rvn == 0:
    #If we are not supplying rvn, but expecting it, we need to subtract fees from that only
    #So add our output at full value first
    vouts[target_addr] = recv_rvn

  print("Funding Raw Transaction. Send: {:.8g} RVN. Get: {:.8g} RVN".format(send_rvn, recv_rvn))
  
  if send_rvn > 0:
    #Determine a valid UTXO set that completes this transaction
    (utxo_total, utxo_set) = swap_storage.find_utxo_set("rvn", send_rvn)
    if utxo_set is None:
      show_error("Not enough UTXOs", "Unable to find a valid UTXO set for {:.8g} RVN".format(send_rvn))
      return False
    send_rvn = utxo_total #Update for the amount we actually supplied
    for utxo in utxo_set:
      vins.append({"txid":utxo["txid"],"vout":utxo["vout"]})

  #Then build and sign raw to estimate fees
  sizing_raw = fn_rpc("createrawtransaction", inputs=vins, outputs=vouts)
  sizing_raw = fn_rpc("combinerawtransaction", txs=[sizing_raw, original_tx])
  sizing_signed = fn_rpc("signrawtransaction", hexstring=sizing_raw) #Need to calculate fees against signed message
  fee_rvn = calculate_fee(sizing_signed["hex"])
  out_rvn = round((send_rvn + recv_rvn) - cost - fee_rvn, 8)
  vouts[target_addr] = out_rvn

  print("Funding result: Send: {:.8g} Recv: {:.8g} Fee: {:.8g} Change: {:.8g}".format(send_rvn, recv_rvn, fee_rvn, out_rvn))

  return True

def vout_to_utxo(vout, txid, n):
  if "scriptPubKey" in vout:
    if "type" in vout["scriptPubKey"] and vout["scriptPubKey"]["type"] == "transfer_asset":
      return {"txid": txid, "vout": n, "type": "asset", "amount": vout["scriptPubKey"]["asset"]["amount"], "asset": vout["scriptPubKey"]["asset"]["name"]}
    else:
      return {"txid": txid, "vout": n, "type": "rvn", "amount": vout["value"]}
  else:
    return {"txid": txid, "vout": n, "type": "unknown"}

#
#Helper function
#

def make_transfer(name, quantity):
  return {"transfer":{name:round(float(quantity), 8)}}

def show_dialog_inner(title, message, buttons, icon=QMessageBox.Information, message_extra="", parent=None):
  msg = QMessageBox(parent)
  msg.setIcon(icon)

  msg.setText(message)
  if(message_extra):
    msg.setInformativeText(message_extra)
  msg.setWindowTitle(title)
  msg.setStandardButtons(buttons)
	
  return msg.exec_()

def show_error(title, message, message_extra="", parent=None):
  return show_dialog_inner(title, message, QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Critical, message_extra=message_extra, parent=parent)

def show_dialog(title, message, message_extra="", parent=None):
  return show_dialog_inner(title, message, QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Information, message_extra=message_extra, parent=parent)

def show_prompt(title, message, message_extra="", parent=None):
  return show_dialog_inner(title, message, QMessageBox.Yes | QMessageBox.No, QMessageBox.Information, message_extra=message_extra, parent=parent)

def backup_remove_file(file_path):
  (root, ext) = os.path.splitext(file_path)
  new_name = "old_{}_{}.{}".format(file_path, datetime.datetime.now().strftime('%Y%m%d%H%M%S'), ext) 
  print("Discarding/moving file [{}] into backup location [{}]".format(file_path, new_name))

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
    # setStyleSheet
    self.textUpQLabel.setStyleSheet('''
        color: rgb(0, 0, 255);
    ''')
    self.textDownQLabel.setStyleSheet('''
        color: rgb(255, 0, 0);
    ''')
   

  @staticmethod
  def from_swap(swap, **kwargs):
    row = QTwoLineRowWidget()
    row.swap = swap
    if swap.own: #If this is OUR trade, the default language can be used
      if swap.type == "buy":
        row.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
          "Buy", swap.quantity(), swap.asset(), swap.total_price(), swap.unit_price()))
      elif swap.type == "sell":
        row.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
          "Sell", swap.quantity(), swap.asset(), swap.total_price(), swap.unit_price()))
      elif swap.type == "trade":
        row.setTextUp("{} {:.8g}x [{}] for {:.8g} [{}] ({:.8g}x [{}] each)".format(
          "Trade", swap.total_price(), swap.in_type, swap.quantity(), swap.asset(), swap.unit_price(), swap.in_type))
    else: #If this is someone else's trade, then we need to invert the language
      #also all listed external orders are already executed, so past-tense
      if swap.type == "buy":
        row.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
          "Sold", swap.quantity(), swap.asset(), swap.total_price(), swap.unit_price()))
      elif swap.type == "sell":
        row.setTextUp("{} {:.8g}x [{}] for {:.8g} RVN ({:.8g} each)".format(
          "Bought", swap.quantity(), swap.asset(), swap.total_price(), swap.unit_price()))
      elif swap.type == "trade":
        row.setTextUp("{} {:.8g}x [{}] for {:.8g} [{}] ({:.8g}x [{}] each)".format(
          "Exchanged", swap.total_price(), swap.in_type, swap.quantity(), swap.asset(), swap.unit_price(), swap.in_type))

    if swap.state == "pending":
      row.setTextDown("Pending in mempool")
    elif swap.state == "completed":
      if not swap.own:
        row.setTextDown("Completed: {}".format(swap.txid))
      else:
        row.setTextDown("Executed: {}".format(swap.txid))
    elif swap.state == "removed":
      row.setTextDown("Removed")
    return row

  @staticmethod
  def from_vout(vout, ismine):
    row = QTwoLineRowWidget()
    row.vout = vout
    row.ismine = ismine
    
    spk = vout["scriptPubKey"]

    if(spk["type"] == "transfer_asset"):
      row.setTextUp("{:.8g}x [{}]".format(float(spk["asset"]["amount"]),spk["asset"]["name"]))
    else:
      row.setTextUp("{:.8g} RVN".format(float(row.vout["value"])))
    
    if(ismine):
      row.setTextDown("** {}".format(spk["addresses"][0]))
    else:  
      row.setTextDown(spk["addresses"][0])

    return row

  @staticmethod
  def from_asset(asset_data):
    row = QTwoLineRowWidget()
    row.asset_data = asset_data

    row.setTextUp("[{}] {:.8g}".format(asset_data["name"], asset_data["balance"]))

    return row

  def getSwap (self):
    return self.swap

  def getAsset(self):
    return self.asset_data

  def setTextUp (self, text):
    self.textUpQLabel.setText(text)

  def setTextDown (self, text):
    self.textDownQLabel.setText(text)

  def setIcon (self, imagePath):
    self.iconQLabel.setPixmap(QPixmap(imagePath))
