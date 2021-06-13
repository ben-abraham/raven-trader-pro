from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path, logging
from util import *
from rvn_rpc import *

from app_instance import AppInstance
from swap_transaction import SwapTransaction

class PreviewTransactionDialog(QDialog):
  def __init__(self, partial_swap, final_swap, preview_title="Confirm Transaction", parent=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("ui/qt/preview_order.ui", self)
    self.swap = partial_swap
    self.setWindowTitle(preview_title)
    self.txtRawFinal.setText(final_swap)
    

    self.decoded = do_rpc("decoderawtransaction", hexstring=final_swap)
    self.transaction_deltas = {}
    self.input_sent = 0
    self.output_sent = 0

    for vin in self.decoded["vin"]:
      #Have to use explorer API here because there is no guarantee that these transactions are local
      #vin_tx = do_rpc("getrawtransaction", txid=vin["txid"], verbose=True)
      local_vout = do_rpc("gettxout", txid=vin["txid"], n=int(vin["vout"]))
      if local_vout:
        vin_tx = do_rpc("getrawtransaction", txid=vin["txid"], verbose=True)
        src_vout = local_vout
      else:
        vin_tx = decode_full(vin["txid"])
        src_vout = vin_tx["vout"][vin["vout"]]
      src_addr = src_vout["scriptPubKey"]["addresses"][0]
      is_my_utxo = AppInstance.wallet.search_utxo(make_utxo(vin)) != None
      
      utxo_data = vout_to_utxo(src_vout, vin["txid"], vin["vout"])
      vin_type = "rvn" if utxo_data["type"] == "rvn" else utxo_data["asset"]
      
      if is_my_utxo:
        if vin_type not in self.transaction_deltas:
          self.transaction_deltas[vin_type] = 0
        self.transaction_deltas[vin_type] -= utxo_data["amount"] #If we provided the input, subtract from total

      if vin_type == "rvn":
        self.input_sent += utxo_data["amount"]

      self.add_tx_item(self.lstInputs, src_vout, is_my_utxo)

    for vout in self.decoded["vout"]:
      vout_addr = vout["scriptPubKey"]["addresses"][0]
      addr_check = do_rpc("validateaddress", address=vout_addr)
      is_my_out = addr_check["ismine"]
      
      utxo_data = vout_to_utxo(vout, self.decoded["txid"], vout["n"])
      vout_type = "rvn" if utxo_data["type"] == "rvn" else utxo_data["asset"]
      
      if is_my_out:
        if vout_type not in self.transaction_deltas:
          self.transaction_deltas[vout_type] = 0
        self.transaction_deltas[vout_type] += utxo_data["amount"] #If we received the output, keep it positive
      
      if vout_type == "rvn":
        self.output_sent += utxo_data["amount"]

      self.add_tx_item(self.lstOutputs, vout, is_my_out)
    
    debits = [(name, self.transaction_deltas[name]) for name in self.transaction_deltas.keys() if self.transaction_deltas[name] > 0]
    credits = [(name, self.transaction_deltas[name]) for name in self.transaction_deltas.keys() if self.transaction_deltas[name] < 0]

    final_text = ""
    if len(credits):
      final_text += "== Total Sent ==\n\n"
      for (credit_type, credit_amt) in credits:
        if credit_type == "rvn":
          final_text += "\t{:.8g} RVN\n".format(credit_amt)
        else:
          final_text += "\t{:.8g}x [{}]\n".format(credit_amt, credit_type)
    final_text += "\n\n"
    if len(debits):
      final_text += "== Total Received ==\n\n"
      for (debit_type, debit_amt) in debits:
        if debit_type == "rvn":
          final_text += "\t{:.8g} RVN\n".format(debit_amt)
        else:
          final_text += "\t{:.8g}x [{}]\n".format(debit_amt, debit_type)
    
    #This is just a dumb diff, ignores ownership
    final_text += "\n\nTotal Fees: {:.8g} RVN".format(self.input_sent - self.output_sent)

    self.lblTransactionSummary.setText(final_text)

    logging.info("Transaction Deltas: {}".format(self.transaction_deltas))
    self.timeout_start()


  def timeout_start(self):
    self.timeout_remaining = AppInstance.settings.read("preview_timeout")
    if self.timeout_remaining <= 0:
      self.timeout_remaining = 0
    else:
      self.tmrTimeout = QTimer(self)
      self.tmrTimeout.timeout.connect(self.timer_timeout)
      self.tmrTimeout.start(1000)

    self.update_timer_display()

  def timer_timeout(self):
    self.timeout_remaining -= 1
    self.update_timer_display()

  def update_timer_display(self):
    if self.timeout_remaining > 0:
      self.btnDialogButtons.button(QDialogButtonBox.Ok).setEnabled(False)
      self.btnDialogButtons.button(QDialogButtonBox.Ok).setText("Send ({})".format(self.timeout_remaining))
    else:
      self.btnDialogButtons.button(QDialogButtonBox.Ok).setEnabled(True)
      self.btnDialogButtons.button(QDialogButtonBox.Ok).setText("Send")
      self.tmrTimeout.stop()

  def add_tx_item(self, list, vout, mine):
    voutListItem = QListWidgetItem(list)
    voutListWidget = QTwoLineRowWidget.from_vout(vout, mine)
    voutListItem.setSizeHint(voutListWidget.sizeHint())
    list.addItem(voutListItem)
    list.setItemWidget(voutListItem, voutListWidget)