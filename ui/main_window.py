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

    self.actionExit.triggered.connect(self.close)
    self.actionRefresh.triggered.connect(self.refresh_main_window)

    self.actionNewBuy.triggered.connect(self.new_buy_order)
    self.actionNewSell.triggered.connect(self.new_sell_order)
    self.actionNewTrade.triggered.connect(self.new_trade_order)
    self.actionCompleteOrder.triggered.connect(self.complete_order)

    self.updateTimer = QTimer(self)
    self.updateTimer.timeout.connect(self.actionRefresh.trigger)
    self.updateTimer.start(10 * 1000)

    self.menu_context = {"type": None, "data": None}
    self.actionRefresh.trigger()

#
# Action callbacks
#

  def new_buy_order(self, prefill=None):
    if self.menu_context["type"] == "asset":
      prefill = make_prefill(self.menu_context["data"])
    buy_dialog = NewOrderDialog("buy", self.swap_storage, prefill=prefill, parent=self)
    if(buy_dialog.exec_()):
      buy_swap = buy_dialog.build_trade()
      self.created_order(buy_swap)

  def new_sell_order(self, prefill=None):
    if self.menu_context["type"] == "asset":
      prefill = make_prefill(self.menu_context["data"])
    sell_dialog = NewOrderDialog("sell", self.swap_storage, prefill=prefill, parent=self)
    if(sell_dialog.exec_()):
      sell_swap = sell_dialog.build_trade()
      self.created_order(sell_swap)

  def new_trade_order(self, prefill=None):
    if self.menu_context["type"] == "asset":
      prefill = make_prefill(self.menu_context["data"])
    trade_dialog = NewTradeDialog(self.swap_storage, prefill=prefill, parent=self)
    if(trade_dialog.exec_()):
      trade_swap = trade_dialog.build_trade()
      self.created_order(trade_swap)

  def created_order(self, trade):
    print("New {}: {}".format(trade.type, json.dumps(trade.__dict__)))
    self.swap_storage.add_swap(trade)
    self.swap_storage.save_data()
    self.update_lists()
    self.view_order_details(trade)

  def action_remove_trade(self):
    if self.menu_context["type"] != "trade":
      return

  def action_view_trade(self):
    if self.menu_context["type"] != "trade":
      return
    self.view_trade_details(self.menu_context["data"])

  def action_setup_trade(self):
    if self.menu_context["type"] != "trade":
      return
    self.setup_trades(self.menu_context["data"], true)

  def action_remove_order(self):
    if self.menu_context["type"] != "order":
      return

  def action_view_order(self):
    if self.menu_context["type"] != "order":
      return
    self.view_trade_details(self.menu_context["data"])
    
  def trade_double_clicked(self, row_widget):
    list = row_widget.listWidget()
    row = list.itemWidget(row_widget)
    self.menu_context = { "type": "trade", "data": row.get_data()}
    self.action_view_trade()
    
  def order_double_clicked(self, row_widget):
    list = row_widget.listWidget()
    row = list.itemWidget(row_widget)
    self.menu_context = { "type": "order", "data": row.get_data()}
    self.action_view_order()

#
# Context Menus
#

  def open_asset_menu(self, list, list_item, click_position, asset):
    menu = QMenu()
    widget_inner = list.itemWidget(list_item)
    menu.addAction(self.actionNewBuy)
    menu.addAction(self.actionNewSell)
    menu.addAction(self.actionNewTrade)
    self.menu_context = { "type": "asset", "data": asset }
    action = menu.exec_(widget_inner.mapToGlobal(click_position))
    
  def open_trade_menu(self, list, list_item, click_position, trade):
    menu = QMenu()
    widget_inner = list.itemWidget(list_item)
    menu.addAction(self.actionSetupTrade) if trade.missing_trades() > 0 else None
    menu.addAction(self.actionViewTrade) if len(trade.order_utxos) > 0 else None
    self.menu_context = { "type": "trade", "data": trade }
    action = menu.exec_(widget_inner.mapToGlobal(click_position))

  def open_order_menu(self, list, list_item, click_position, swap):
    menu = QMenu()
    widget_inner = list.itemWidget(list_item)
    menu.addAction(self.actionViewOrder)
    menu.addAction(self.actionRemoveOrder)
    self.menu_context = { "type": "order", "data": swap }
    menu.exec_(widget_inner.mapToGlobal(click_position))

#
# Sub-Dialogs
#

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

  def view_trade_details(self, trade, force_order=True):
    (success, result) = self.setup_trades(trade, force_order)
    #TODO: Wait for TXID if one was sent out here
    if success:
      if result == None:
        details = OrderDetailsDialog(trade, self.swap_storage, parent=self, dialog_mode="multiple")
        return details.exec_()
      elif result:
        show_dialog("Sent", "Transaction has been submitted. Please try again soon.", result, self)
    elif result:
      show_error("Error", "Transactions could not be setup for trade.", result, self)

  def view_order_details(self, swap):
    details = OrderDetailsDialog(swap, self.swap_storage, parent=self, dialog_mode="single")
    return details.exec_()

  def update_order_details(self, widget):
    list = widget.listWidget()
    swap_row = list.itemWidget(widget)
    details = OrderDetailsDialog(swap_row.get_data(), self.swap_storage, parent=self, dialog_mode="update")
    return (details.exec_(), details.spnUpdateUnitPrice.value())

#
# Updating
#

  def refresh_main_window(self):
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
    self.add_udpate_items(list, swap_list, lambda x: x.utxo, QTwoLineRowWidget.from_swap, self.open_order_menu)

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