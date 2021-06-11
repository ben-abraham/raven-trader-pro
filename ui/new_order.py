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
from ui.ui_prompt import *

from app_instance import AppInstance
from swap_transaction import SwapTransaction
from swap_trade import SwapTrade

class NewOrderDialog(QDialog):
  def __init__(self, mode, prefill=None, parent=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("ui/qt/new_order.ui", self)
    self.mode = mode
    self.wallet = AppInstance.wallet
    if(self.mode != "buy" and self.mode != "sell"):
      raise "Invalid Order Mode"
    
    self.wallet.update_wallet()
    self.waiting_txid = None
    self.asset_exists = True
    self.all_utxo = False #allow perfectly rounded UTXO's only when waiting from the start

    if self.mode == "buy":
      self.setWindowTitle("New Buy Order")
      self.cmbAssets.setEditable(True)
      self.spinQuantity.setEnabled(False)
      self.btnCheckAvailable.clicked.connect(self.check_available)
      self.cmbAssets.addItems(self.wallet.my_asset_names)
      self.cmbAssets.currentTextChanged.connect(self.asset_changed)
      self.cmbAssets.setCurrentText("")
    elif self.mode == "sell":
      self.setWindowTitle("New Sell Order")
      self.cmbAssets.setEditable(False)
      self.cmbAssets.addItems(["{} [{}]".format(v, self.wallet.assets[v]["balance"]) for v in self.wallet.my_asset_names])
      self.cmbAssets.currentIndexChanged.connect(self.check_available)
      self.btnCheckAvailable.setVisible(False)
      self.check_available()

    if prefill:
      if self.mode == "buy":
        self.cmbAssets.setCurrentText(prefill["asset"])
      elif self.mode == "sell":
        self.cmbAssets.setCurrentIndex(self.wallet.my_asset_names.index(prefill["asset"]))
      self.spinQuantity.setValue(prefill["quantity"])
      self.spinUnitPrice.setValue(prefill["unit_price"])
      self.asset_exists = True

    self.spinQuantity.valueChanged.connect(self.update)
    self.spinUnitPrice.valueChanged.connect(self.update)
    self.spinOrderCount.valueChanged.connect(self.update)
    self.update()

  def check_available(self):
    if self.mode == "buy":
      asset_name = self.cmbAssets.currentText()
    elif self.mode == "sell":
      asset_name = self.wallet.my_asset_names[self.cmbAssets.currentIndex()]
    (want_admin, details) = asset_details(asset_name)
    self.asset_exists = True if details else False
    self.btnCheckAvailable.setEnabled(False)
    if self.asset_exists:
      if self.mode == "buy":
        self.spinQuantity.setEnabled(True)
        self.btnCheckAvailable.setText("Yes! - {} total".format(details["amount"]))
      
      self.spinQuantity.setDecimals(int(details["units"]))
      self.spinQuantity.setMaximum(float(details["amount"]))
      self.spinQuantity.setMinimum(1 / pow(10, float(details["units"])))
    else:
      if self.cmbAssets.currentText().islower():
        show_error("Error","Asset does not exist! Assets are case-sensitive.")
      self.btnCheckAvailable.setText("Asset does not exist!")
    self.update()

  def asset_changed(self):
    self.asset_exists = False
    self.btnCheckAvailable.setText("Check Available")
    self.btnCheckAvailable.setEnabled(True)
    self.spinQuantity.setEnabled(False)

  def update(self):
    #Read GUI
    self.quantity = self.spinQuantity.value()
    self.price = self.spinUnitPrice.value()
    self.destination = self.txtDestination.text()
    self.order_count = self.spinOrderCount.value()
    self.total_price = self.quantity * self.price
    self.valid_order = True
    if self.mode == "buy":
      self.asset_name = self.cmbAssets.currentText()
      #don't have enough rvn for the order
      if self.total_price > self.wallet.rvn_balance():
        self.valid_order = False
    else:
      self.asset_name = self.wallet.my_asset_names[self.cmbAssets.currentIndex()]
      #Don't own the asset or enough of it
      if self.asset_name not in self.wallet.my_asset_names or self.quantity > self.wallet.assets[self.asset_name]["balance"]:
        self.valid_order = False

    #Not valid while waiting on a tx to confirm or if asset hasn't been confirmed yet
    if self.waiting_txid or not self.asset_exists:
      self.valid_order = False

    #valid_order check doesn't cover UTXO existing b/c valid_order determins if we enable the UTXO button or not
    #Update GUI
    self.lblTotalDisplay.setText("{:.8g} RVN".format(self.total_price))
    if self.mode == "buy":
      self.lblFinal.setText("{:.8g} RVN".format(self.total_price * self.order_count))
    elif self.mode == "sell":
      self.lblFinal.setText("{:.8g} [{}]".format(self.quantity * self.order_count, self.asset_name))
    #Hide the button if we don't have a valid order
    if self.valid_order:
      self.btnDialogButtons.setStandardButtons(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
    else:
      self.btnDialogButtons.setStandardButtons(QDialogButtonBox.Cancel)

  def build_trade(self):
    if self.mode == "buy":
      return SwapTrade.create_trade("buy", "rvn", self.total_price, self.asset_name, self.quantity, self.order_count, self.destination)
    elif self.mode == "sell":
      return SwapTrade.create_trade("sell", self.asset_name, self.quantity, "rvn", self.total_price, self.order_count, self.destination)
