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
from swap_trade import SwapTrade


class NewTradeDialog(QDialog):
  def __init__(self, prefill=None, parent=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("ui/qt/new_trade.ui", self)
    self.wallet = AppInstance.wallet
    
    self.wallet.update_wallet()
    self.waiting_txid = None
    self.asset_exists = True
    self.all_utxo = False #allow perfectly rounded UTXO's only when waiting from the start

    self.setWindowTitle("New Trade Order")
    self.cmbOwnAsset.setEditable(False)
    self.cmbOwnAsset.addItems(["{} [{}]".format(v, self.wallet.assets[v]["balance"]) for v in self.wallet.my_asset_names])
    self.cmbWantAsset.addItems(self.wallet.my_asset_names)
    self.cmbWantAsset.setCurrentText("")

    if prefill:
      self.cmbOwnAsset.setCurrentIndex(self.wallet.my_asset_names.index(prefill["asset"]))
      self.spinOwnQuantity.setValue(prefill["quantity"])
      self.asset_exists = True

    self.cmbOwnAsset.currentIndexChanged.connect(self.my_asset_changed)
    self.cmbWantAsset.currentIndexChanged.connect(self.update)
    self.cmbWantAsset.currentTextChanged.connect(self.asset_changed)
    self.spinOwnQuantity.valueChanged.connect(self.update)
    self.spinWantQuantity.valueChanged.connect(self.update)
    self.spinOrderCount.valueChanged.connect(self.update)

    self.btnCheckAvailable.clicked.connect(self.check_available)

    self.my_asset_changed()
    self.update()

  def my_asset_changed(self):
    asset_name = self.wallet.my_asset_names[self.cmbOwnAsset.currentIndex()]
    (want_admin, details) = asset_details(asset_name)
    if details:
      self.spinOwnQuantity.setDecimals(int(details["units"]))
      self.spinOwnQuantity.setMaximum(float(details["amount"]))#Set max to amount we own maybe?
      self.spinOwnQuantity.setMinimum(1 / pow(10, float(details["units"])))

  def check_available(self):
    #TODO: Save this asset data for later
    (want_admin, details) = asset_details(self.cmbWantAsset.currentText())
    self.asset_exists = True if details else False
    self.btnCheckAvailable.setEnabled(False)
    if self.asset_exists:
      self.spinWantQuantity.setEnabled(True)
      self.btnCheckAvailable.setText("Yes! - {} total".format(details["amount"]))
      self.spinWantQuantity.setDecimals(int(details["units"]))
      self.spinWantQuantity.setMaximum(float(details["amount"]))
      self.spinWantQuantity.setMinimum(1 / pow(10, float(details["units"])))
    else:
      self.spinWantQuantity.setEnabled(False)
      self.btnCheckAvailable.setText("No!")
    self.update()

  def asset_changed(self):
    self.asset_exists = False
    self.btnCheckAvailable.setText("Check Available")
    self.btnCheckAvailable.setEnabled(True)
    self.update()
      
  def update(self):
    #Read GUI
    self.own_quantity = self.spinOwnQuantity.value()
    self.want_quantity = self.spinWantQuantity.value()
    self.destination = self.txtDestination.text()
    self.order_count = self.spinOrderCount.value()
    self.valid_order = True

    self.own_asset_name = self.wallet.my_asset_names[self.cmbOwnAsset.currentIndex()]
    self.want_asset_name = self.cmbWantAsset.currentText()
    self.lblSummary.setText("Give: {:.8g}x [{}], Get: {:.8g}x [{}]".format(self.own_quantity, self.own_asset_name, self.want_quantity, self.want_asset_name))
    self.lblFinal.setText("Give: {:.8g}x [{}], Get: {:.8g}x [{}]".format(self.own_quantity * self.order_count, self.own_asset_name, self.want_quantity * self.order_count, self.want_asset_name))
    #Don't own the asset or enough of it
    if self.own_asset_name not in self.wallet.my_asset_names or self.own_quantity > self.wallet.assets[self.own_asset_name]["balance"]:
      self.valid_order = False

    #Not valid while waiting on a tx to confirm or if asset hasn't been confirmed yet
    if self.waiting_txid or not self.asset_exists:
      self.valid_order = False

    #Update GUI
    #Hide the button if we don't have a valid order
    if self.valid_order:
      self.btnDialogButtons.setStandardButtons(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
    else:
      self.btnDialogButtons.setStandardButtons(QDialogButtonBox.Cancel)

  def build_trade(self):
    return SwapTrade.create_trade("trade", self.own_asset_name, self.own_quantity, self.want_asset_name, self.want_quantity, self.order_count, self.destination)