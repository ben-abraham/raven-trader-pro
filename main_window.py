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
from new_trade import NewTradeDialog

class MainWindow(QMainWindow):
  def __init__(self, storage, *args, **kwargs):
    super().__init__(*args, **kwargs)
    uic.loadUi("main_window.ui", self)
    self.setWindowTitle("Raven Trader Pro")

    self.swap_storage = storage

    self.btnNewBuyOrder.clicked.connect(self.new_buy_order)
    self.btnNewSellOrder.clicked.connect(self.new_sell_order)
    self.btnNewTradeOrder.clicked.connect(self.new_trade_order)
    self.btnCompleteOrder.clicked.connect(self.complete_order)

    self.lstBuyOrders.itemDoubleClicked.connect(self.view_order_details)
    self.lstSellOrders.itemDoubleClicked.connect(self.view_order_details)
    self.lstTradeOrders.itemDoubleClicked.connect(self.view_order_details)
    self.lstPastOrders.itemDoubleClicked.connect(self.view_order_details)
    self.lstCompletedOrders.itemDoubleClicked.connect(self.view_order_details)

    self.updateTimer = QTimer(self)
    self.updateTimer.timeout.connect(self.mainWindowUpdate)
    self.updateTimer.start(10 * 1000)
    #try:
    self.mainWindowUpdate()
    #except:
    #  print("ERROR: Initial grid update failed. This is usually due to a new order format json. Backing up and clearing old data.")
    #  backup_remove_file(SWAP_STORAGE_PATH)
    #  backup_remove_file(LOCK_STORAGE_PATH)

  def open_swap_menu(self, list, list_item, click_position, swap):
    menu = QMenu()
    widget_inner = list.itemWidget(list_item)
    deatilsAction = menu.addAction("View Details")
    updateAction = menu.addAction("Update Price") if swap.state == "new" else None
    removeSoftAction = menu.addAction("Remove Order - Soft") if swap.state == "new" else None
    removeHardAction = menu.addAction("Remove Order - Hard") if swap.state == "new" else None
    removeCompletedAction = menu.addAction("Remove Order") if swap.state == "completed" else None
    action = menu.exec_(widget_inner.mapToGlobal(click_position))
    if action == None:
      return
    elif action == deatilsAction:
      print("View Details")
      self.view_order_details(list_item)
    elif action == updateAction:
      (response, new_price) = self.update_order_details(list_item)
      if response:
        print("Updated Order - Old:{:.8g} RVN \t New:{:.8g} RVN".format(swap.unit_price(), new_price))
        swap.set_unit_price(new_price)
        swap.sign_partial()
        self.swap_storage.save_swaps()
        self.view_order_details(list_item)
        self.update_lists()
    elif action == removeSoftAction:
      if(show_dialog("Soft Remove Trade Order?", 
      "Would you like to soft-remove this trade order?\r\n"+
      "A created order can be executed at any time once it has been announced, as long as the original UTXO remains valid.\r\n"+
      "A soft-remove simply stops locking the UTXO and ignores it in software (anyone who recieved the order can still complete it).\r\n"+
      "A hard remove will invalidate the previously-used UTXO by sending yourself a transaction using it.")):
        print("Soft Removing Trade Order")
        #TODO: Hide these instead of deleting. Needs to unlock UTXO as well
        self.swap_storage.remove_swap(swap)
        self.swap_storage.save_swaps()
        self.update_lists()
    elif action == removeHardAction:
      if(show_dialog("Hard Remove Trade Order?", 
      "Would you like to hard-remove this trade order?\r\n"+
      "A created order can be executed at any time once it has been announced, as long as the original UTXO remains valid.\r\n"+
      "A soft-remove simply stops locking the UTXO and ignores it in software (anyone who recieved the order can still complete it).\r\n"+
      "A hard remove will invalidate the previously-used UTXO by sending yourself a transaction using it.")):
        print("Hard Remove Trade Order")
          
        setup_utxo = swap.consutrct_invalidate_tx(self.swap_storage)
        preview_dialog = PreviewTransactionDialog(swap, setup_utxo["hex"], self.swap_storage, parent=self)
        if preview_dialog.exec_():
          print("Send Invalidate!")
          sent_txid = do_rpc("sendrawtransaction", hexstring=setup_utxo["hex"])
          update_response = show_prompt("Update Price?", "Sent! TXID: {}".format(sent_txid), "Would you like to create a new order against the invalidated UTXO?", parent=self)
          if update_response == QMessageBox.Yes:
            if swap.type == "buy":
              self.new_buy_order({"asset": swap.asset(), "quantity": swap.out_quantity, "unit_price": swap.unit_price(), "waiting": sent_txid})
            elif swap.type == "sell":
              self.new_sell_order({"asset": swap.asset(), "quantity": swap.out_quantity, "unit_price": swap.unit_price(), "waiting": sent_txid})
            elif swap.type == "trade":
              self.new_trade_order(swap)
        else:
          print("Dont Invalidate!")
    elif action == removeCompletedAction:
      print("Removing Order")
      self.swap_storage.remove_swap(swap)
      self.swap_storage.save_swaps()
      self.update_lists()

  def open_asset_menu(self, list, list_item, click_position, asset):
    menu = QMenu()
    widget_inner = list.itemWidget(list_item)
    sellAction = menu.addAction("Sell")
    buyAction = menu.addAction("Buy")
    action = menu.exec_(widget_inner.mapToGlobal(click_position))
    if action == sellAction:
      self.new_sell_order({"asset": asset["name"], "quantity": 1, "unit_price": 1})
    elif action == buyAction:
      self.new_buy_order({"asset": asset["name"], "quantity": 1, "unit_price": 1})

  def new_buy_order(self, prefill=None):
    buy_dialog = NewOrderDialog("buy", self.swap_storage, prefill=prefill, parent=self)
    if(buy_dialog.exec_()):
      buy_swap = buy_dialog.build_order()
      if not buy_swap.destination:
        buy_swap.destination = do_rpc("getnewaddress")

      buy_swap.sign_partial()
      print("New Buy: ", json.dumps(buy_swap.__dict__))
      self.swap_storage.add_swap(buy_swap)
      self.swap_storage.save_swaps()
      self.update_lists()
      details = OrderDetailsDialog(buy_swap, self.swap_storage, parent=self, dialog_mode="details")
      details.exec_()

  def new_sell_order(self, prefill=None):
    sell_dialog = NewOrderDialog("sell", self.swap_storage, prefill=prefill, parent=self)
    if(sell_dialog.exec_()):
      sell_swap = sell_dialog.build_order()
      if not sell_swap.destination:
        sell_swap.destination = do_rpc("getnewaddress")

      sell_swap.sign_partial()
      print("New Sell: ", json.dumps(sell_swap.__dict__))
      self.swap_storage.add_swap(sell_swap)
      self.swap_storage.save_swaps()
      self.update_lists()
      details = OrderDetailsDialog(sell_swap, self.swap_storage, parent=self, dialog_mode="details")
      details.exec_()

  def new_trade_order(self, prefill_swap=None):
    prefill = None
    trade_dialog = NewTradeDialog(self.swap_storage, prefill=prefill, parent=self)
    if(trade_dialog.exec_()):
      trade_swap = trade_dialog.build_order()
      if not trade_swap.destination:
        trade_swap.destination = do_rpc("getnewaddress")

      trade_swap.sign_partial()
      print("New Trade: ", json.dumps(trade_swap.__dict__))
      self.swap_storage.add_swap(trade_swap)
      self.swap_storage.save_swaps()
      self.update_lists()
      details = OrderDetailsDialog(trade_swap, self.swap_storage, parent=self, dialog_mode="details")
      details.exec_()

  def complete_order(self):
    order_dialog = OrderDetailsDialog(None, self.swap_storage, parent=self, dialog_mode="complete")
    if(order_dialog.exec_()):
      partial_swap = order_dialog.build_order()
      finished_swap = partial_swap.complete_order(self.swap_storage)
      if finished_swap:
        print("Swap: ", json.dumps(partial_swap.__dict__))
        
        preview_dialog = PreviewTransactionDialog(partial_swap, finished_swap, self.swap_storage, parent=self)

        if(preview_dialog.exec_()):
          print("Transaction Approved. Sending!")
          submitted_txid = do_rpc("sendrawtransaction", hexstring=finished_swap)
          partial_swap.txid = submitted_txid
          partial_swap.state = "completed" #TODO: Add waiting on confirmation phase
          #Add a completed swap to the list.
          #it's internally tracked from an external source
          self.swap_storage.add_swap(partial_swap)
          self.update_lists()
        else:
          print("Transaction Rejected")

  def view_order_details(self, widget):
    list = widget.listWidget()
    swap_row = list.itemWidget(widget)
    details = OrderDetailsDialog(swap_row.getSwap(), self.swap_storage, parent=self, dialog_mode="details")
    return details.exec_()

  def update_order_details(self, widget):
    list = widget.listWidget()
    swap_row = list.itemWidget(widget)
    details = OrderDetailsDialog(swap_row.getSwap(), self.swap_storage, parent=self, dialog_mode="update")
    return (details.exec_(), details.spnUpdateUnitPrice.value())
    
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

    self.add_update_swap_items(self.lstBuyOrders,       [swap for swap in self.swap_storage.swaps if swap.state == "new" and swap.type == "buy"  ])
    self.add_update_swap_items(self.lstSellOrders,      [swap for swap in self.swap_storage.swaps if swap.state == "new" and swap.type == "sell" ])
    self.add_update_swap_items(self.lstTradeOrders,     [swap for swap in self.swap_storage.swaps if swap.state == "new" and swap.type == "trade"])
    self.add_update_swap_items(self.lstPastOrders,      [swap for swap in self.swap_storage.swaps if swap.state == "completed" and swap.own      ])
    self.add_update_swap_items(self.lstCompletedOrders, [swap for swap in self.swap_storage.swaps if swap.state == "completed" and not swap.own  ])
    
    self.add_update_asset_items(self.lstMyAssets,       [self.swap_storage.assets[asset_name] for asset_name in self.swap_storage.my_asset_names])

  def add_update_asset_items(self, list, asset_list):
    existing_rows = {}
    seen_assets = []
    for idx in range(0, list.count()):
      row = list.item(idx)
      asset_details = list.itemWidget(row).getAsset()
      existing_rows[asset_details["name"]] = self.add_update_list_widget(list, asset_details, QTwoLineRowWidget.from_asset, self.open_asset_menu, existing=row)
    existing_assets = [*existing_rows.keys()]
    for asset in asset_list:
      seen_assets.append(asset["name"])
      if asset["name"] not in existing_assets:
        self.add_update_list_widget(list, asset, QTwoLineRowWidget.from_asset, self.open_asset_menu)
    for old_name in [name for name in existing_assets if name not in seen_assets]:
      item_row = list.row(existing_rows[old_name])
      list.takeItem(item_row)

  def add_update_swap_items(self, list, swap_list):
    existing_rows = {}
    seen_utxos = []
    for idx in range(0, list.count()):
      row = list.item(idx)
      swap_details = list.itemWidget(row).getSwap()
      existing_rows[swap_details.utxo] = self.add_update_list_widget(list, swap_details, QTwoLineRowWidget.from_swap, self.open_swap_menu, existing=row)
    existing_utxos = [*existing_rows.keys()]
    for swap in swap_list:
      seen_utxos.append(swap.utxo)
      if swap.utxo not in existing_utxos:
        self.add_update_list_widget(list, swap, QTwoLineRowWidget.from_swap, self.open_swap_menu)
    for old_utxo in [utxo for utxo in existing_utxos if utxo not in seen_utxos]:
      item_row = list.row(existing_rows[old_utxo])
      list.takeItem(item_row)

  def add_update_list_widget(self, list, widget_data, fn_widget_generator, fn_context_menu, existing=None):
    if existing:
      list.removeItemWidget(existing)

    list_widget = fn_widget_generator(widget_data)
    list_item = existing if existing else QListWidgetItem(list)
    list_item.setSizeHint(list_widget.sizeHint())

    list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
    list_widget.customContextMenuRequested.connect(lambda pt: fn_context_menu(list, list_item, pt, widget_data))
    
    if not existing:
      list.addItem(list_item)

    list.setItemWidget(list_item, list_widget)
    return list_item