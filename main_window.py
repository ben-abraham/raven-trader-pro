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
from config import *

from preview_order import PreviewTransactionDialog
from swap_transaction import SwapTransaction
from order_details import OrderDetailsDialog
from swap_storage import SwapStorage
from new_order import NewOrderDialog

class MainWindow(QMainWindow):
  def __init__(self, storage, *args, **kwargs):
    super().__init__(*args, **kwargs)
    uic.loadUi("main_window.ui", self)
    self.setWindowTitle("Raven Trader Pro")

    self.swap_storage = storage

    self.btnNewBuyOrder.clicked.connect(self.new_buy_order)
    self.btnNewSellOrder.clicked.connect(self.new_sell_order)
    self.btnCompleteOrder.clicked.connect(self.complete_order)

    self.lstBuyOrders.itemDoubleClicked.connect(self.view_order_details)
    self.lstSellOrders.itemDoubleClicked.connect(self.view_order_details)
    self.lstPastOrders.itemDoubleClicked.connect(self.view_order_details)

    self.updateTimer = QTimer(self)
    self.updateTimer.timeout.connect(self.mainWindowUpdate)
    self.updateTimer.start(10 * 1000)
    self.mainWindowUpdate()

  def open_swap_menu(self, list, list_item, click_position, swap):
    menu = QMenu()
    widget_inner = list.itemWidget(list_item)
    deatilsAction = menu.addAction("View Details")
    removeSoftAction = menu.addAction("Remove Order - Soft")
    removeHardAction = menu.addAction("Remove Order - Hard")
    action = menu.exec_(widget_inner.mapToGlobal(click_position))
    if action == deatilsAction:
      print("View Details")
      self.view_order_details(list_item)
    elif action == removeSoftAction:
      if(show_dialog("Soft Remove Trade Order?", 
      "Would you like to soft-remove this trade order?\r\n"+
      "A created order can be executed at any time once it has been announced, as long as the original UTXO remains valid.\r\n"+
      "A soft-remove simply stops locking the UTXO and ignores it in software (anyone who recieved the order can still complete it).\r\n"+
      "A hard remove will invalidate the previously-used UTXO by sending yourself a transaction using it.")):
        print("Soft Removing Trade Order")

    elif action == removeHardAction:
      if(show_dialog("Hard Remove Trade Order?", 
      "Would you like to hard-remove this trade order?\r\n"+
      "A created order can be executed at any time once it has been announced, as long as the original UTXO remains valid.\r\n"+
      "A soft-remove simply stops locking the UTXO and ignores it in software (anyone who recieved the order can still complete it).\r\n"+
      "A hard remove will invalidate the previously-used UTXO by sending yourself a transaction using it.")):
        print("Hard Remove Trade Order")

  def new_buy_order(self):
    buy_dialog = NewOrderDialog("buy", self.swap_storage, parent=self)
    if(buy_dialog.exec_()):
      buy_swap = buy_dialog.build_order()
      if not buy_swap.destination:
        buy_swap.destination = do_rpc("getnewaddress")

      buy_swap.sign_partial()
      print("New Buy: ", json.dumps(buy_swap.__dict__))
      self.swap_storage.add_swap(buy_swap)
      self.swap_storage.save_swaps()
      self.update_lists()
      details = OrderDetailsDialog(buy_swap, self.swap_storage, parent=self)
      details.exec_()

  def new_sell_order(self):
    sell_dialog = NewOrderDialog("sell", self.swap_storage, parent=self)
    if(sell_dialog.exec_()):
      sell_swap = sell_dialog.build_order()
      if not sell_swap.destination:
        sell_swap.destination = do_rpc("getnewaddress")

      sell_swap.sign_partial()
      print("New Sell: ", json.dumps(sell_swap.__dict__))
      self.swap_storage.add_swap(sell_swap)
      self.swap_storage.save_swaps()
      self.update_lists()
      details = OrderDetailsDialog(sell_swap, self.swap_storage, parent=self)
      details.exec_()

  def complete_order(self):
    order_dialog = OrderDetailsDialog(None, self.swap_storage, complete_mode=True, parent=self)
    if(order_dialog.exec_()):
      partial_swap = order_dialog.build_order()
      finished_swap = partial_swap.complete_order(self.swap_storage)
      print("Swap: ", json.dumps(partial_swap.__dict__))
      
      preview_dialog = PreviewTransactionDialog(partial_swap, finished_swap, self.swap_storage, parent=self)

      if(preview_dialog.exec_()):
        print("Transaction Approved. Sending!")
        submitted_txid = do_rpc("sendrawtransaction", hexstring=finished_swap)
        partial_swap.txid = submitted_txid
        partial_swap.state = "completed"
        #Add a completed swap to the list.
        #it's internally tracked from an external source
        self.swap_storage.add_swap(partial_swap)

      else:
        print("Transaction Rejected")


  def view_order_details(self, widget):
    list = widget.listWidget()
    swap_row = list.itemWidget(widget)
    details = OrderDetailsDialog(swap_row.getSwap(), self.swap_storage, parent=self)
    details.exec_()
    
  def clear_list(self, list):
    for row in range(0, list.count()):
      list.takeItem(0) #keep removing idx 0

  def mainWindowUpdate(self):
    self.swap_storage.load_utxos()

    asset_total = 0
    for asset_name in self.swap_storage.my_asset_names:
      asset_total += self.swap_storage.assets[asset_name]["balance"]

    avail_balance = self.swap_storage.balance - self.swap_storage.locaked_rvn()
    avail_assets = asset_total - self.swap_storage.locaked_assets()

    self.lblBalanceTotal.setText("Total Balance: {:.8g} RVN [{:.8g} Assets]".format(self.swap_storage.balance, asset_total))
    self.lblBalanceAvailable.setText("Total Available: {:.8g} RVN [{:.8g} Assets]".format(avail_balance, avail_assets))
    self.update_lists()

  def update_lists(self):
    #Check for state changes, by looking over UTXO's
    for swap in self.swap_storage.swaps:
      if swap.state == "new" and swap.own:
        #if its no longer unspent, the swap has been executed
        #and this should be moved to completed
        if not self.swap_storage.swap_utxo_unspent(swap.utxo):
          swap_txid = search_swap_tx(swap.utxo)
          print("Swap Completed! txid: ", swap_txid)
          swap.state = "completed"
          swap.txid = swap_txid
          self.swap_storage.save_swaps()

    self.add_update_swap_items(self.lstBuyOrders,       [swap for swap in self.swap_storage.swaps if swap.state == "new" and swap.type == "buy" ])
    self.add_update_swap_items(self.lstSellOrders,      [swap for swap in self.swap_storage.swaps if swap.state == "new" and swap.type == "sell"])
    self.add_update_swap_items(self.lstPastOrders,      [swap for swap in self.swap_storage.swaps if swap.state == "completed" and swap.own     ])
    self.add_update_swap_items(self.lstCompletedOrders, [swap for swap in self.swap_storage.swaps if swap.state == "completed" and not swap.own ])

  def add_update_swap_items(self, list, swap_list):
    udpated_utxos = []
    for idx in range(0, list.count()):
      row = list.item(idx)
      swap_details = list.itemWidget(row).getSwap()
      self.add_update_swap_item(list, swap_details, existing=row)
      udpated_utxos.append(swap_details.utxo)
    for swap in swap_list:
      if swap.utxo not in udpated_utxos:
        self.add_update_swap_item(list, swap)

  def add_update_swap_item(self, list, swap_details, existing=None):
    if existing:
      list.removeItemWidget(existing)

    swapListWidget = QTwoLineRowWidget.from_swap(swap_details)
    swapListItem = existing if existing else QListWidgetItem(list)
    swapListItem.setSizeHint(swapListWidget.sizeHint())

    swapListWidget.setContextMenuPolicy(Qt.CustomContextMenu)
    swapListWidget.customContextMenuRequested.connect(lambda pt: self.open_swap_menu(list, swapListItem, pt, swap_details))
    
    if not existing:
      list.addItem(swapListItem)

    list.setItemWidget(swapListItem, swapListWidget)