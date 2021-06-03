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

from ui.preview_order import PreviewTransactionDialog
from ui.order_details import OrderDetailsDialog
from ui.new_trade import NewTradeDialog
from ui.new_order import NewOrderDialog

from swap_transaction import SwapTransaction
from swap_storage import SwapStorage
from app_settings import AppSettings

class MainWindow(QMainWindow):
  def __init__(self, storage, *args, **kwargs):
    super().__init__(*args, **kwargs)
    uic.loadUi("ui/qt/main_window.ui", self)
    self.setWindowTitle("Raven Trader Pro")

    self.settings = AppSettings.instance
    self.swap_storage = storage

    self.btnNewBuyOrder.clicked.connect(self.new_buy_order)
    self.btnNewSellOrder.clicked.connect(self.new_sell_order)
    self.btnNewTradeOrder.clicked.connect(self.new_trade_order)
    self.btnCompleteOrder.clicked.connect(self.complete_order)

    self.lstAllOrders.itemDoubleClicked.connect(self.view_order_details)
    self.lstPastOrders.itemDoubleClicked.connect(self.view_order_details)
    self.lstCompletedOrders.itemDoubleClicked.connect(self.view_order_details)

    self.updateTimer = QTimer(self)
    self.updateTimer.timeout.connect(self.mainWindowUpdate)
    self.updateTimer.start(10 * 1000)
    
    self.mainWindowUpdate()

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
        self.swap_storage.save_data()
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
        self.swap_storage.save_data()
        self.update_lists()
    elif action == removeHardAction:
      if(show_dialog("Hard Remove Trade Order?", 
      "Would you like to hard-remove this trade order?\r\n"+
      "A created order can be executed at any time once it has been announced, as long as the original UTXO remains valid.\r\n"+
      "A soft-remove simply stops locking the UTXO and ignores it in software (anyone who recieved the order can still complete it).\r\n"+
      "A hard remove will invalidate the previously-used UTXO by sending yourself a transaction using it.")):
        print("Hard Remove Trade Order")
          
        setup_utxo = swap.consutrct_invalidate_tx(self.swap_storage)
        preview_dialog = PreviewTransactionDialog(swap, setup_utxo["hex"], self.swap_storage, preview_title="Invalidate Order", parent=self)
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
      self.swap_storage.save_data()
      self.update_lists()
  
  def open_trade_menu(self, list, list_item, click_position, trade):
    menu = QMenu()
    widget_inner = list.itemWidget(list_item)
    setupTradesAction = menu.addAction("Setup Trade") if trade.missing_trades() > 0 else None
    tradeDetailsAction = menu.addAction("Trade Details") if len(trade.order_utxos) > 0 else None
    action = menu.exec_(widget_inner.mapToGlobal(click_position))
    if action == None:
      return
    elif action == tradeDetailsAction:
      self.view_order_details(None, trade)
    elif action == setupTradesAction:
      self.setup_trades(trade, True)

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
      buy_swap = buy_dialog.build_trade()
      self.created_order(buy_swap)

  def new_sell_order(self, prefill=None):
    sell_dialog = NewOrderDialog("sell", self.swap_storage, prefill=prefill, parent=self)
    if(sell_dialog.exec_()):
      sell_swap = sell_dialog.build_trade()
      self.created_order(sell_swap)

  def new_trade_order(self, prefill_swap=None):
    prefill = None
    trade_dialog = NewTradeDialog(self.swap_storage, prefill=prefill, parent=self)
    if(trade_dialog.exec_()):
      trade_swap = trade_dialog.build_trade()
      self.created_order(trade_swap)

  def setup_trades(self, trade, force_create):
    filled = trade.attempt_fill_trade_pool(self.swap_storage)
    if not filled and force_create:
      setup_all = QMessageBox.Yes if trade.missing_trades() == 1 else\
        show_prompt_3("Setup All Trades?", "Would you like to setup all trades right now? If not, you can continue to make them one-by-one.")
      if setup_all != QMessageBox.Cancel:
        check_unlock()
        try:
          setup_trade = trade.setup_trade(self.swap_storage, max_add=None if setup_all == QMessageBox.Yes else 1)
          if setup_trade:
            setup_txid = self.preview_complete(setup_trade, "Setup Trade Order")
            if setup_txid:
              return (True, setup_txid)
              #Wait for confirmation, then run this again.
            else:
              return (False, "Transaction Error: {}".format(setup_txid))
          else:
            return (False, "Invalid Trade")
        except Exception as e:
          print(e)
          raise e
          return (False, "Trade Error: {}".format(e))
      else:
        return (False, None)
    else: #Pool has been filled
      return (True, None)


  def created_order(self, trade):
    print("New {}: {}".format(trade.type, json.dumps(trade.__dict__)))
    self.swap_storage.add_swap(trade)
    self.swap_storage.save_data()
    self.update_lists()
    self.view_order_details(None, swap=trade)

  def complete_order(self):
    order_dialog = OrderDetailsDialog(None, self.swap_storage, parent=self, dialog_mode="complete")
    if(order_dialog.exec_()):
      partial_swap = order_dialog.build_order()
      finished_swap = partial_swap.complete_order(self.swap_storage)
      if finished_swap:
        print("Swap: ", json.dumps(partial_swap.__dict__))
        sent_txid = self.preview_complete(finished_swap, "Confirm Transaction [2/2]")
        if sent_txid:
          partial_swap.txid = sent_txid
          partial_swap.state = "completed" #TODO: Add waiting on confirmation phase
          #Add a completed swap to the list.
          #it's internally tracked from an external source
          self.swap_storage.add_completed(partial_swap)
          self.update_lists()
  
  def preview_complete(self, raw_tx, message, swap=None):
    preview_dialog = PreviewTransactionDialog(swap, raw_tx, self.swap_storage, preview_title=message, parent=self)
    if preview_dialog.exec_():
      print("Transaction Approved. Sending!")
      submitted_txid = do_rpc("sendrawtransaction", hexstring=raw_tx)
      return submitted_txid
    return None

  def view_order_details(self, widget, swap=None, force_order=True):
    if not swap:
      list = widget.listWidget()
      swap_row = list.itemWidget(widget)
      swap = swap_row.get_data()
    (success, result) = self.setup_trades(swap, force_order)
    #TODO: Wait for TXID if one was sent out here
    if success:
      if result == None:
        details = OrderDetailsDialog(swap, self.swap_storage, parent=self, dialog_mode="multiple")
        return details.exec_()
      elif result:
        show_dialog("Sent", "Transaction has been submitted. Please try again soon.", result, self)
    elif result:
      show_error("Error", "Transactions could not be setup for trade.", result, self)

  def update_order_details(self, widget):
    list = widget.listWidget()
    swap_row = list.itemWidget(widget)
    details = OrderDetailsDialog(swap_row.get_data(), self.swap_storage, parent=self, dialog_mode="update")
    return (details.exec_(), details.spnUpdateUnitPrice.value())
    
  def clear_list(self, list):
    for row in range(0, list.count()):
      list.takeItem(0) #keep removing idx 0

  def mainWindowUpdate(self):
    self.swap_storage.update_wallet()

    avail_balance = self.swap_storage.available_balance
    total_balance = self.swap_storage.total_balance

    self.lblBalanceTotal.setText("Total Balance: {:.8g} RVN [{:.8g} Assets]".format(total_balance[0], total_balance[2]))
    self.lblBalanceAvailable.setText("Total Available: {:.8g} RVN [{:.8g} Assets]".format(avail_balance[0], avail_balance[2]))
    self.update_lists()

  def update_lists(self):
    self.add_update_trade_items(self.lstAllOrders, self.swap_storage.swaps)

    self.add_update_swap_items(self.lstPastOrders,      [swap for swap in self.swap_storage.history if (swap.state in ["pending", "completed"]) and swap.own      ])
    self.add_update_swap_items(self.lstCompletedOrders, [swap for swap in self.swap_storage.history if (swap.state in ["pending", "completed"]) and not swap.own  ])

    self.add_update_asset_items(self.lstMyAssets,       [self.swap_storage.assets[asset_name] for asset_name in self.swap_storage.my_asset_names])

  def add_update_asset_items(self, list, asset_list):
    self.add_udpate_items(list, asset_list, lambda x: x["name"], QTwoLineRowWidget.from_asset, self.open_asset_menu)

  def add_update_swap_items(self, list, swap_list):
    self.add_udpate_items(list, swap_list, lambda x: x.utxo, QTwoLineRowWidget.from_swap, self.open_swap_menu)

  def add_update_trade_items(self, list, swap_list):
    self.add_udpate_items(list, swap_list, \
      lambda x: "{}{}{}{}".format(x.in_quantity,x.in_type,x.out_quantity,x.out_type)\
      , QTwoLineRowWidget.from_trade, self.open_trade_menu)

  def add_udpate_items(self, list_widget, item_list, fn_key_selector, fn_row_factory, fn_context_menu):
    existing_rows = {}
    seen_keys = []
    for idx in range(0, list_widget.count()):
      row = list_widget.item(idx)
      row_widget = list_widget.itemWidget(row)
      row_data = row_widget.get_data()
      row_key = fn_key_selector(row_data)
      existing_rows[row_key] = row
      row_widget.refresh() #Trigger update function
    existing_keys = [*existing_rows.keys()]
    for current_item in item_list:
      item_key = fn_key_selector(current_item)
      seen_keys.append(item_key)
      if item_key not in existing_keys:
        self.add_update_list_widget(list_widget, current_item, fn_row_factory, fn_context_menu)
        existing_keys.append(item_key)
    for old_key in [key for key in existing_keys if key not in seen_keys]:
      item_row = list_widget.row(existing_rows[old_key])
      list_widget.takeItem(item_row)

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