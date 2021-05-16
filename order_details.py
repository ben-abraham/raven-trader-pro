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

class OrderDetailsDialog(QDialog):
  def __init__(self, swap, swap_storage, parent=None, complete_mode=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("order_details.ui", self)
    self.swap = swap
    self.swap_storage = swap_storage
    self.complete_mode = complete_mode

    if not self.complete_mode:
      self.setWindowTitle("Order Details")
      self.update_for_swap(self.swap)
      self.txtSigned.setText(self.swap.raw)
      self.buttonBox.removeButton(self.buttonBox.button(QDialogButtonBox.Cancel))
    else:
      self.setWindowTitle("Preview Completion [1/2]")
      #Allow user to edit and register listener for changes
      self.txtSigned.setReadOnly(False)
      self.txtSigned.textChanged.connect(self.raw_tx_changed)
      self.buttonBox.removeButton(self.buttonBox.button(QDialogButtonBox.Ok))
      self.confirm_button = self.buttonBox.addButton("Confirm", QDialogButtonBox.AcceptRole)

  def update_for_swap(self, swap):
    self.lblMine.setText("Yes" if swap.own else "No")
    self.lblStatus.setText(swap.state)
    if swap.own:
      self.lblType.setText("Buy" if swap.type == "buy" else "Sell")
    else:
      self.lblType.setText("Sale" if swap.type == "buy" else "Purchase")
    self.lblAsset.setText(swap.asset)
    self.lblQuantity.setText(str(swap.quantity))
    self.lblUnitPrice.setText("{:.8g} RVN".format(swap.unit_price))
    self.lblUTXO.setText(swap.utxo)
    self.lblTotalPrice.setText("{:.8g} RVN".format(swap.totalPrice()))
    self.txtDestination.setText(swap.destination)

  def swap_error(self):
    #Sell order means we are buying
    if self.swap.type == "sell":
      if self.swap.totalPrice() > self.swap_storage.balance:
        return "You don't have enough RVN to purchase."
    else:
      if self.swap.asset not in self.swap_storage.my_asset_names:
        return "You don't own that asset."
      if self.swap.quantity > self.swap_storage.assets[self.swap.asset]["balance"]:
        return "You don't own enough of that asset."

  def raw_tx_changed(self):
    if not self.complete_mode:
      return

    parsed = SwapTransaction.decode_swap(self.txtSigned.toPlainText())
    if parsed:
      self.swap = parsed
      self.update_for_swap(self.swap)
      err = self.swap_error()
      if err:
        show_error("Error!", err, parent=self)
        self.confirm_button.setVisible(False)
      else:
        self.confirm_button.setVisible(True)

    self.confirm_button.setEnabled(self.swap is not None)

  def build_order(self):
    return self.swap