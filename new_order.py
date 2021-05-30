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

class NewOrderDialog(QDialog):
  def __init__(self, mode, swap_storage, prefill=None, parent=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("new_order.ui", self)
    self.mode = mode
    self.swap_storage = swap_storage
    if(self.mode != "buy" and self.mode != "sell"):
      raise "Invalid Order Mode"
    
    self.swap_storage.load_utxos()
    self.waiting_txid = None
    self.asset_exists = True
    self.all_utxo = False #allow perfectly rounded UTXO's only when waiting from the start

    if self.mode == "buy":
      self.setWindowTitle("New Buy Order")
      self.cmbAssets.setEditable(True)
      self.spinQuantity.setEnabled(False)
      self.btnCheckAvailable.clicked.connect(self.check_available)
      self.cmbAssets.currentTextChanged.connect(self.asset_changed)
      self.cmbAssets.addItems(self.swap_storage.my_asset_names)
      self.cmbAssets.setCurrentText("")
    elif self.mode == "sell":
      self.setWindowTitle("New Sell Order")
      self.cmbAssets.setEditable(False)
      self.cmbAssets.addItems(["{} [{}]".format(v, self.swap_storage.assets[v]["balance"]) for v in self.swap_storage.my_asset_names])
      self.btnCheckAvailable.setVisible(False)

    if prefill:
      self.cmbAssets.setCurrentText(prefill["asset"])
      self.spinQuantity.setValue(prefill["quantity"])
      self.spinUnitPrice.setValue(prefill["unit_price"])
      self.asset_exists = True
      if "waiting" in prefill:
        self.waiting_txid = prefill["waiting"]
        self.all_utxo = True
        self.start_waiting()
        self.wait_timer()

    self.cmbAssets.currentIndexChanged.connect(self.update)
    self.spinQuantity.valueChanged.connect(self.update)
    self.spinUnitPrice.valueChanged.connect(self.update)
    self.btnCreateUTXO.clicked.connect(self.create_utxo)
    self.lblWhatUTXO.mousePressEvent = self.show_utxo_help #apparently this event is jenky?
    self.update()

  def show_utxo_help(self, *args):
    show_dialog("UTXO Explanation", 
    "Blockchain balances are comprised of the sum of many individual unspent transaction outputs (UTXO's). "+
      "These can be of any quantity/denomination, but ALL of it must be spent in whole during a transaction. "+
      "Any leftovers are returned to another address as change",
    "To construct a one-sided market order, you must have a single UTXO of the exact amount you would like to advertise.",
    parent=self)

  def check_available(self):
    #TODO: Save this asset data for later
    details = do_rpc("getassetdata", asset_name=self.cmbAssets.currentText())
    self.asset_exists = True if details else False
    self.btnCheckAvailable.setEnabled(False)
    if self.asset_exists:
      self.spinQuantity.setEnabled(True)
      self.btnCheckAvailable.setText("Yes! - {} total".format(details["amount"]))
      self.spinQuantity.setMaximum(float(details["amount"]))
    else:
      if self.cmbAssets.currentText().islower():
        show_error("Error","Asset does not exist! Assets are case-sensitive.")
      self.spinQuantity.setEnabled(False)
      self.btnCheckAvailable.setText("Asset does not exist!")
    self.update()

  def asset_changed(self):
    self.asset_exists = False
    self.btnCheckAvailable.setText("Check Available")
    self.btnCheckAvailable.setEnabled(True)

  def create_utxo(self):
    summary = "Send yourself {} to costruct a {} order?"  

    if self.mode == "buy":
      summary = summary.format("{:.8g} RVN".format(self.total_price), self.mode)
    elif self.mode == "sell":
      summary = summary.format("{:.8g}x [{}]".format(self.quantity, self.asset_name), self.mode)

    if(show_dialog("Are you sure?", "This involves sending yourself an exact amount of RVN/Assets to produce the order. This wil encur a smal transaction fee", summary, self)):
      #This makes sure all known swaps UTXO's are locked and won't be used when a transfer is requested
      #Could also smart-lock even-valued UTXO's but that's a whole thing...
      self.swap_storage.wallet_lock_all_swaps()

      try:
        if self.mode == "buy":
          print("Creating self RVN transaction")
          check_unlock()

          new_change_addr = do_rpc("getnewaddress")
          self.waiting_txid = do_rpc("sendtoaddress", address=new_change_addr, amount=self.total_price)
        elif self.mode == "sell":
          print("Creating self asset transaction")
          check_unlock()

          new_change_addr = do_rpc("getnewaddress")
          rvn_change_addr = do_rpc("getnewaddress")
          asset_change_addr = do_rpc("getnewaddress")
          transfer_self_txid = do_rpc("transfer", asset_name=self.asset_name, 
                    to_address=new_change_addr, qty=self.quantity, message="",
                    change_address=rvn_change_addr, asset_change_address=asset_change_addr)

          self.waiting_txid = transfer_self_txid[0]
      finally:
        #Unlock everything when done, locking causes too many problems.
        self.swap_storage.wallet_unlock_all()

      if(self.waiting_txid):
        show_dialog("Success!", "Transaction {} submitted successfully.".format(self.waiting_txid), "Waiting for confirmation")
        self.start_waiting()
        self.wait_timer()
      else:
        show_dialog("Error", "Transaction not submitted. Check logs")

      self.update()

  def start_waiting(self):
    if hasattr(self, "udpateTimer") and self.updateTimer:
      self.updateTimer.stop()

    self.wait_count = 0
    self.updateTimer = QTimer(self)
    self.updateTimer.timeout.connect(self.wait_timer)
    self.updateTimer.start(5 * 1000)

  def wait_timer(self):
    tx_status = do_rpc("getrawtransaction", txid=self.waiting_txid, verbose=True)
    confirmed = tx_status["confirmations"] >= 1 if "confirmations" in tx_status else False
    if confirmed:
      print("UTXO Setup Confirmed!")
      self.waiting_txid = None
      self.btnCreateUTXO.setText("Create Order UTXO")
      self.updateTimer.stop()
      self.updateTimer = None
      self.swap_storage.load_utxos() #need to re-load UTXO's to find the new one
      self.update()
      #Lock the newly created UTXO
      self.swap_storage.add_lock(self.order_utxo["txid"], self.order_utxo["vout"])
    else:
      self.wait_count = (self.wait_count + 1) % 5
      self.btnCreateUTXO.setText("Waiting on confirmation" + ("." * self.wait_count))
      
  def update(self):
    #Read GUI
    self.quantity = self.spinQuantity.value()
    self.price = self.spinUnitPrice.value()
    self.destination = self.txtDestination.text()
    self.total_price = self.quantity * self.price
    self.valid_order = True
    if self.mode == "buy":
      self.asset_name = self.cmbAssets.currentText()
      self.order_utxo = self.swap_storage.find_utxo("rvn", self.total_price, skip_locks=True, skip_rounded=False)
      self.chkUTXOReady.setText("UTXO Ready ({:.8g} RVN)".format(self.total_price))
      #don't have enough rvn for the order
      if self.total_price > self.swap_storage.balance:
        self.valid_order = False
    else:
      self.asset_name = self.swap_storage.my_asset_names[self.cmbAssets.currentIndex()]
      self.order_utxo = self.swap_storage.find_utxo("asset", self.quantity, name=self.asset_name, skip_locks=True, skip_rounded=False)
      self.chkUTXOReady.setText("UTXO Ready ({:.8g}x [{}])".format(self.quantity, self.asset_name))
      #Don't own the asset or enough of it
      if self.asset_name not in self.swap_storage.my_asset_names or self.quantity > self.swap_storage.assets[self.asset_name]["balance"]:
        self.valid_order = False

    #Not valid while waiting on a tx to confirm or if asset hasn't been confirmed yet
    if self.waiting_txid or not self.asset_exists:
      self.valid_order = False

    #valid_order check doesn't cover UTXO existing b/c valid_order determins if we enable the UTXO button or not
    #Update GUI
    self.lblTotalDisplay.setText("{:.8g} RVN".format(self.total_price))
    self.chkUTXOReady.setChecked(self.order_utxo is not None)
    if self.waiting_txid:
      self.btnCreateUTXO.setEnabled(False)
    else:
      self.btnCreateUTXO.setEnabled(self.order_utxo is None)
    #Hide the button if we don't have a valid order
    if self.order_utxo and self.valid_order:
      self.btnDialogButtons.setStandardButtons(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
    else:
      self.btnDialogButtons.setStandardButtons(QDialogButtonBox.Cancel)

  def build_order(self):
    return SwapTransaction({
      "in_type": self.asset_name if self.mode == "sell" else "rvn", 
      "out_type": self.asset_name if self.mode == "buy" else "rvn",
      "in_quantity": self.quantity if self.mode == "sell" else self.price,
      "out_quantity": self.quantity if self.mode == "buy" else self.quantity * self.price,
      "own": True,
      "utxo": self.order_utxo["txid"] + "|" + str(self.order_utxo["vout"]),
      "destination": self.destination,
      "state": "new",
      "type": self.mode,
      "raw": "--",
      "txid": ""
    })
