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
  def __init__(self, swap, swap_storage, parent=None, dialog_mode="details", **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("order_details.ui", self)
    self.swap = swap
    self.swap_storage = swap_storage
    self.dialog_mode = dialog_mode
    print(self.swap)
    if self.dialog_mode == "details":
      self.setWindowTitle("Order Details")
      self.update_for_swap(self.swap)
      self.txtSigned.setText(self.swap.raw)
      self.buttonBox.removeButton(self.buttonBox.button(QDialogButtonBox.Cancel))
    elif self.dialog_mode == "complete":
      self.setWindowTitle("Preview Completion [1/2]")
      #Allow user to edit and register listener for changes
      self.txtSigned.setReadOnly(False)
      self.txtSigned.textChanged.connect(self.raw_tx_changed)
      self.buttonBox.removeButton(self.buttonBox.button(QDialogButtonBox.Ok))
      self.confirm_button = self.buttonBox.addButton("Confirm", QDialogButtonBox.AcceptRole)
    elif self.dialog_mode == "update":
      self.setWindowTitle("Order Price")
      self.spnUpdateUnitPrice.setReadOnly(False)
      self.spnUpdateUnitPrice.valueChanged.connect(self.update_labels)
      self.update_for_swap(self.swap)

  def update_for_swap(self, swap):
    self.lblMine.setText("Yes" if swap.own else "No")
    self.lblStatus.setText(swap.state)
    if swap.own:
      self.lblType.setText("Buy - You want to purchase" if swap.type == "buy" else "Sell - You want to sell")
    else:
      self.lblType.setText("Sale - You want to sell to a buyer" if swap.type == "buy" else "Purchase - You want to buy someone's sale")
    self.lblAsset.setText(swap.asset)
    self.lblQuantity.setText(str(swap.quantity))
    self.lblUTXO.setText(swap.utxo)
    self.spnUpdateUnitPrice.setValue(swap.unit_price)
    self.lblTotalPrice.setText("{:.8g} RVN".format(swap.totalPrice()))
    self.txtDestination.setText(swap.destination)

  def update_labels(self):
    new_price = self.spnUpdateUnitPrice.value()
    self.lblTotalPrice.setText("{:.8g} RVN".format(new_price * self.swap.quantity))

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
    if self.dialog_mode != "complete":
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