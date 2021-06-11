from jsonrpcclient.requests import Request
from requests import post, get
from decimal import *

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5 import uic

import sys, getopt, argparse, json, time, getpass, os.path, re, logging
from util import *
from rvn_rpc import *
from ui.ui_prompt import *

from app_instance import AppInstance
from swap_transaction import SwapTransaction

class OrderDetailsDialog(QDialog):
  def __init__(self, swap, parent=None, raw_prefill=None, dialog_mode="details", **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("ui/qt/order_details.ui", self)
    self.swap = swap
    self.wallet = AppInstance.wallet
    self.dialog_mode = dialog_mode
    self.current_number = 0
    self.last_text = ""
    logging.info(self.swap)
    if self.dialog_mode == "single":
      self.setWindowTitle("Order Details")
      self.update_for_swap(self.swap) #SwapTransaction
      self.txtSigned.setText(self.swap.raw)
      self.buttonBox.removeButton(self.buttonBox.button(QDialogButtonBox.Cancel))
    elif self.dialog_mode == "multiple":
      self.trade = self.swap
      self.spnOrderNumber.setEnabled(True)
      self.spnOrderNumber.setMinimum(1)
      self.spnOrderNumber.setMaximum(len(self.trade.order_utxos))
      self.trade_number_changed(1)
      self.spnOrderNumber.valueChanged.connect(self.trade_number_changed)
      self.buttonBox.removeButton(self.buttonBox.button(QDialogButtonBox.Cancel))
    elif self.dialog_mode == "complete":
      self.setWindowTitle("Preview Completion [1/2]")
      #Allow user to edit and register listener for changes
      self.buttonBox.removeButton(self.buttonBox.button(QDialogButtonBox.Ok))
      self.confirm_button = self.buttonBox.addButton("Confirm", QDialogButtonBox.AcceptRole)
      self.txtSigned.setReadOnly(False)
      self.txtSigned.textChanged.connect(self.raw_tx_changed)
      self.txtSigned.setText(raw_prefill) #This happens last as it will trigger the update event
    elif self.dialog_mode == "update":
      self.setWindowTitle("Order Price")
      self.spnUpdateUnitPrice.setReadOnly(False)
      self.spnUpdateUnitPrice.valueChanged.connect(self.update_labels)
      self.update_for_swap(self.swap)

  def trade_number_changed(self, swap_index):
    self.current_number = swap_index - 1
    new_swap = self.trade.transactions[self.current_number]
    self.swap = new_swap
    self.setWindowTitle("Order Details [{}/{}]".format(self.current_number + 1, len(self.trade.order_utxos))) #SwapTrade
    self.update_for_swap(new_swap)

  def update_for_swap(self, swap):
    self.lblMine.setText("Yes" if swap.own else "No")
    #self.lblStatus.setText(swap.state)
    self.lblAsset.setText(swap.asset())
    
    if swap.type == "buy":
      self.lblTotalPrice.setText("{:.8g} RVN".format(swap.total_price()))
      if swap.own:
        self.lblType.setText("Buy - You want to purchase.")
      else:
        self.lblType.setText("Sale - You want to sell to a buyer.")
    
    elif swap.type == "sell":
      self.lblTotalPrice.setText("{:.8g} RVN".format(swap.total_price()))
      if swap.own:
        self.lblType.setText("Sell - You want to sell.")
      else:
        self.lblType.setText("Purchase - You want to buy someone's sale.")
    
    elif swap.type == "trade":
      self.spnUpdateUnitPrice.setSuffix(" {}/{}".format(swap.out_type.upper(), swap.in_type.upper()) )
      self.lblTotalPrice.setText("{:.8g} {}".format(swap.total_price(), swap.in_type.upper()))
      if swap.own:
        self.lblType.setText("Trade - You want to trade assets of your own, for different assets.")
      else:
        self.lblType.setText("Exchange - You want to exchange assets with another party.")
        
    self.lblQuantity.setText(str(swap.quantity()))
    self.lblUTXO.setText(swap.utxo)
    self.spnUpdateUnitPrice.setValue(swap.unit_price())
    self.txtDestination.setText(swap.destination)
    self.txtSigned.setText(swap.raw)

  def update_labels(self):
    new_price = self.spnUpdateUnitPrice.value()
    self.lblTotalPrice.setText("{:.8g} {}".format(new_price * self.swap.quantity(), self.swap.out_type.upper()))

  def swap_error(self):
    #Sell order means we are buying
    asset_needed = None
    asset_qty = 0
    rvn_qty = 0

    #if this is our swap, we need to provide inputs
    if self.swap.own:
      if self.swap.in_type == "rvn":
        rvn_qty += self.swap.in_quantity #RVN Input
      else:
        asset_needed = self.swap.in_type
        asset_qty = self.swap.in_quantity
    #If this is a completing order, we need the outputs
    else:
      if self.swap.out_type == "rvn":
        rvn_qty += self.swap.out_quantity
      else:
        asset_needed = self.swap.out_type
        asset_qty = self.swap.out_quantity

    if asset_needed:
      if asset_needed not in self.wallet.my_asset_names:
        return "You don't own the asset [{}].".format(asset_needed)
      if asset_qty > self.wallet.assets[asset_needed]["balance"]:
        return "You don't own enough of that asset. Own {}, Need {}".format(self.wallet.assets[asset_needed]["balance"], asset_qty)
    if rvn_qty > self.wallet.rvn_balance():
      return "You don't have enough RVN to purchase."
    return None

  def raw_tx_changed(self):
    if self.dialog_mode != "complete":
      return
    new_text = self.txtSigned.toPlainText()
    if new_text == self.last_text:
      return
    self.last_text = new_text
    if not re.search("^[0-9a-fA-F]*$", new_text):
      return

    (parsed, response) = SwapTransaction.decode_swap(new_text)
    if parsed:
      self.swap = response
      self.update_for_swap(self.swap)
      err = self.swap_error()
      if err:
        show_error("Error!", err, parent=self)
        self.confirm_button.setVisible(False)
      else:
        self.confirm_button.setVisible(True)
    else:
      show_error("Transaction Error!", response, parent=self)
      self.confirm_button.setVisible(False)


    self.confirm_button.setEnabled(self.swap is not None)

  def build_order(self):
    return self.swap