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

from server_connection import *

PAGE_SIZE = 25

class ServerOrdersDialog(QDialog):
  def __init__(self, server_connection, parent=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("ui/qt/server_orders.ui", self)
    self.server = server_connection
    self.server_offset = 0
    self.actionRefresh.trigger()
    self.cmbOrderType.currentTextChanged.connect(self.full_reset)
    self.cmbOrderType.addItems(["All Orders", "Buy Orders Only", "Sell Orders Only", "Trade Orders Only"])

  def prev_page(self):
    if self.server_offset - PAGE_SIZE >= 0:
      self.server_offset -= PAGE_SIZE
    self.refresh_listings()

  def next_page(self):
    if self.server_offset + PAGE_SIZE < self.orders["totalCount"]:
      self.server_offset += PAGE_SIZE
    self.refresh_listings()

  def full_reset(self):
    self.server_offset = 0
    self.refresh_listings()

  def refresh_listings(self):
    swap_type = None
    #Have to reverse perspective when looking at external orders
    if self.cmbOrderType.currentText() == "Buy Orders Only":
      swap_type = SERVER_TYPE_SELL
    elif self.cmbOrderType.currentText() == "Sell Orders Only":
      swap_type = SERVER_TYPE_BUY
    elif self.cmbOrderType.currentText() == "Trade Orders Only":
      swap_type = SERVER_TYPE_TRADE

    self.orders = self.server.search_listings(asset_name=self.txtSearch.text(), swap_type=swap_type, offset=self.server_offset, page_size=PAGE_SIZE)
    self.swaps = self.orders["swaps"]
    self.lstServerOrders.clear()
    self.lblStatus.setText("{}-{}/{}".format(self.orders["offset"], self.orders["offset"] + len(self.swaps), self.orders["totalCount"] ))
    for swap in self.swaps:
      self.add_server_order(self.lstServerOrders, swap)
    
    self.btnPrev.setEnabled(self.server_offset > 0)
    self.btnNext.setEnabled(self.server_offset + PAGE_SIZE < self.orders["totalCount"])

  def execute_order(self, order):
    self.selected_order = order
    self.accept()

  def add_server_order(self, list, server_order):
    orderWidget = QServerOrderWidget(server_order)
    orderItem = QListWidgetItem(list)
    orderItem.setSizeHint(orderWidget.sizeHint())
    list.addItem(orderItem)
    list.setItemWidget(orderItem, orderWidget)
    orderWidget.btnActivate.clicked.connect(lambda _, order=server_order: self.execute_order(order))


class QServerOrderWidget (QWidget):
  def __init__ (self, server_listing, parent = None):
    super(QServerOrderWidget, self).__init__(parent)
    
    self.textQVBoxLayout = QVBoxLayout()
    self.upText    = QLabel()
    self.downText  = QLabel()
    #self.upText.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
    #self.downText.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
    self.textQVBoxLayout.addWidget(self.upText)
    self.textQVBoxLayout.addWidget(self.downText)
    self.allQHBoxLayout  = QHBoxLayout()
    self.btnActivate     = QPushButton()
    #self.btnActivate.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    self.allQHBoxLayout.addLayout(self.textQVBoxLayout, stretch=5)
    self.allQHBoxLayout.addWidget(self.btnActivate, stretch=1)
    self.setLayout(self.allQHBoxLayout)

    #Need to reverse perspective for external orders
    if server_listing["orderType"] == SERVER_TYPE_BUY:
      self.upText.setText("Sell: {}x [{}]".format(server_listing["outQuantity"], server_listing["outType"]))
      self.downText.setText("Price: {}x RVN".format(server_listing["inQuantity"]))
      self.btnActivate.setText("Sell {}".format(server_listing["outType"]))
    elif server_listing["orderType"] == SERVER_TYPE_SELL:
      self.upText.setText("Buy: {}x [{}]".format(server_listing["inQuantity"], server_listing["inType"]))
      self.downText.setText("Price: {}x RVN".format(server_listing["outQuantity"]))
      self.btnActivate.setText("Buy {}".format(server_listing["inType"]))
    elif server_listing["orderType"] == SERVER_TYPE_TRADE:
      self.upText.setText("Trade: {}x [{}]".format(server_listing["inQuantity"], server_listing["inType"]))
      self.downText.setText("Price: {}x [{}]".format(server_listing["outQuantity"], server_listing["outType"]))
      self.btnActivate.setText("Trade for {}".format(server_listing["inType"]))