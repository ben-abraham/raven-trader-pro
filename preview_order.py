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

class PreviewTransactionDialog(QDialog):
  def __init__(self, partial_swap, final_swap, swap_storage, parent=None, **kwargs):
    super().__init__(parent, **kwargs)
    uic.loadUi("previeworder.ui", self)
    self.swap = partial_swap
    self.setWindowTitle("Confirm Transaction [2/2]")
    self.txtRawFinal.setText(final_swap)

    decoded = do_rpc("decoderawtransaction", hexstring=final_swap)
    
    for vin in decoded["vin"]:
      #Have to use explorer API here because there is no guarantee that these transactions are local
      #vin_tx = do_rpc("getrawtransaction", txid=vin["txid"], verbose=True)
      vin_tx = decode_full(vin["txid"])
      src_vout = vin_tx["vout"][vin["vout"]]
      src_addr = src_vout["scriptPubKey"]["addresses"][0]
      is_my_utxo = False
      
      for my_utxo in swap_storage.utxos:
        if my_utxo["txid"] == vin["txid"] and my_utxo["vout"] == vin["vout"]:
          is_my_utxo = True
          break
      for my_asset in swap_storage.my_asset_names:
        for my_a_utxo in swap_storage.assets[my_asset]["outpoints"]:
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