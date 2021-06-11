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

class PreviewTransactionDialog(QDialog):
  def __init__(self, partial_swap, final_swap, preview_title="Confirm Transaction", parent=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("ui/qt/preview_order.ui", self)
    self.swap = partial_swap
    self.setWindowTitle(preview_title)
    self.txtRawFinal.setText(final_swap)

    decoded = do_rpc("decoderawtransaction", hexstring=final_swap)
    
    for vin in decoded["vin"]:
      #Have to use explorer API here because there is no guarantee that these transactions are local
      #vin_tx = do_rpc("getrawtransaction", txid=vin["txid"], verbose=True)
      local_vout = do_rpc("gettxout", txid=vin["txid"], n=int(vin["vout"]))
      if local_vout:
        vin_tx = do_rpc("getrawtransaction", txid=vin["txid"], verbose=True)
        src_vout = local_vout
      else:
        vin_tx = decode_full(vin["txid"])
        src_vout = vin_tx["vout"][vin["vout"]]
      src_addr = src_vout["scriptPubKey"]["addresses"][0]
      is_my_utxo = False
      
      for my_utxo in AppInstance.wallet.utxos:
        if my_utxo["txid"] == vin["txid"] and my_utxo["vout"] == vin["vout"]:
          is_my_utxo = True
          break
      for my_asset in AppInstance.wallet.my_asset_names:
        for my_a_utxo in AppInstance.wallet.assets[my_asset]["outpoints"]:
          if my_a_utxo["txid"] == vin["txid"] and my_a_utxo["vout"] == vin["vout"]:
            is_my_utxo = True
            break
      
      self.add_swap_item(self.lstInputs, src_vout, is_my_utxo)

    for vout in decoded["vout"]:
      vout_addr = vout["scriptPubKey"]["addresses"][0]
      addr_check = do_rpc("validateaddress", address=vout_addr)
      is_my_out = addr_check["ismine"]
      
      self.add_swap_item(self.lstOutputs, vout, is_my_out)

  def add_swap_item(self, list, vout, mine):
    voutListWidget = QTwoLineRowWidget.from_vout(vout, mine)
    voutListItem = QListWidgetItem(list)
    voutListItem.setSizeHint(voutListWidget.sizeHint())
    list.addItem(voutListItem)
    list.setItemWidget(voutListItem, voutListWidget)